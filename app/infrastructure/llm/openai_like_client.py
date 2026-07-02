from __future__ import annotations

import json
import logging
import random
import re
import time as time_module

import httpx2

from app.core.config import Settings
from app.infrastructure.llm.base import BasePageGenerationClient, PagePlanResult, PageGenerationResult
from app.infrastructure.llm.concurrency import get_global_semaphore
from app.infrastructure.llm.prompt_builder import PageAnalysisPromptBuilder


logger = logging.getLogger(__name__)


class OpenAILikePageGenerationClient(BasePageGenerationClient):
    def __init__(self, settings: Settings, prompt_builder: PageAnalysisPromptBuilder) -> None:
        self.settings = settings
        self.prompt_builder = prompt_builder

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_base_url and self.settings.llm_model)

    @property
    def _api_url(self) -> str:
        base = self.settings.llm_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return f"{base}/chat/completions"

    def _call_llm(
        self,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        use_json: bool = False,
        stream: bool = True,
        model: str | None = None,
        enable_thinking: bool = False,
    ) -> str:
        """带全局并发控制和限流退避的 LLM 调用。

        信号量在 LLM 请求期间持有（含重试），请求完成后释放。
        429 限流时优先读 Retry-After 头，无则指数退避+随机抖动。
        网络错误（连接超时等）也做退避重试。
        """
        payload: dict = {
            "model": model or self.settings.llm_model,
            "temperature": 0.2,
            "stream": stream,
            "enable_thinking": enable_thinking,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if use_json:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        timeout = httpx2.Timeout(self.settings.llm_timeout_seconds, connect=30.0)

        max_retries = self.settings.llm_rate_limit_max_retries
        base_delay = self.settings.llm_rate_limit_base_delay
        max_delay = self.settings.llm_rate_limit_max_delay

        semaphore = get_global_semaphore()
        semaphore.acquire()
        try:
            for attempt in range(1, max_retries + 1):
                try:
                    if stream:
                        return self._call_stream(payload, headers, timeout)
                    return self._call_non_stream(payload, headers, timeout)
                except httpx2.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if status_code == 429:
                        delay = self._calculate_backoff(exc.response, attempt, base_delay, max_delay)
                        logger.warning(
                            "LLM 请求被限流 (429, attempt=%s/%s)，等待 %.1fs 后重试",
                            attempt, max_retries, delay,
                        )
                        time_module.sleep(delay)
                        continue
                    raise
                except (httpx2.ConnectError, httpx2.ReadTimeout, httpx2.WriteTimeout) as exc:
                    delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1), max_delay)
                    logger.warning(
                        "LLM 请求网络错误 (attempt=%s/%s): %s，等待 %.1fs 后重试",
                        attempt, max_retries, exc, delay,
                    )
                    if attempt < max_retries:
                        time_module.sleep(delay)
                        continue
                    raise
            raise RuntimeError(f"LLM 请求在 {max_retries} 次重试后仍被限流")
        finally:
            semaphore.release()

    @staticmethod
    def _calculate_backoff(
        response: httpx2.Response,
        attempt: int,
        base_delay: float,
        max_delay: float,
    ) -> float:
        """计算退避时间：优先读 Retry-After，无则指数退避+随机抖动。"""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = base_delay * (2 ** (attempt - 1))
        else:
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
        return min(delay, max_delay)

    def _call_stream(self, payload: dict, headers: dict, timeout: httpx2.Timeout) -> str:
        content_parts: list[str] = []
        with httpx2.Client(timeout=timeout) as client:
            with client.stream(
                "POST",
                self._api_url,
                json=payload,
                headers=headers,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            text = delta.get("content")
                            if text:
                                content_parts.append(text)
                        except json.JSONDecodeError:
                            logger.debug("跳过无法解析的 SSE 行: %s", data_str[:80])
        return "".join(content_parts)

    def _call_non_stream(self, payload: dict, headers: dict, timeout: httpx2.Timeout) -> str:
        payload["stream"] = False
        with httpx2.Client(timeout=timeout) as client:
            response = client.post(self._api_url, json=payload, headers=headers)
            response.raise_for_status()
            model_payload = response.json()
            return model_payload["choices"][0]["message"]["content"]

    def plan_single_page(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        svg_content: str,
        total_pages: int = 0,
        model: str | None = None,
        enable_thinking: bool = False,
    ) -> PagePlanResult:
        if not self.enabled or not api_key.strip():
            return self._plan_fallback_single(page_no, page_name, total_pages)
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                content = self._call_llm(
                    api_key=api_key,
                    system_prompt=self.prompt_builder.build_plan_system_prompt(),
                    user_prompt=self.prompt_builder.build_plan_user_prompt(
                        requirement_text=requirement_text,
                        page_no=page_no,
                        page_name=page_name,
                        svg_content=svg_content,
                    ),
                    use_json=True,
                    stream=True,
                    model=model,
                    enable_thinking=enable_thinking,
                )
                logger.info("LLM 页面规划返回 (page=%s): %s", page_no, content[:200])
                plan = self._parse_single_plan_response(content, page_no, page_name)
                if not plan.should_generate:
                    logger.info("第 %s 页跳过，原因: %s", page_no, plan.skip_reason)
                return plan
            except Exception as exc:
                logger.warning("LLM 页面规划失败 (page=%s, attempt=%s/%s): %s", page_no, attempt, max_retries, exc)
                if attempt < max_retries:
                    time_module.sleep(2 * attempt)
        logger.warning("LLM 页面规划重试 %s 次仍失败 (page=%s)，回退启发式逻辑", max_retries, page_no)
        return self._plan_fallback_single(page_no, page_name, total_pages)

    def generate_page_svg(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        page_type: str,
        page_title: str,
        svg_content: str,
        model: str | None = None,
        enable_thinking: bool = False,
    ) -> PageGenerationResult:
        if not self.enabled or not api_key.strip():
            return self._generate_fallback(page_no, page_name)
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                content = self._call_llm(
                    api_key=api_key,
                    system_prompt=self.prompt_builder.build_generate_system_prompt(page_type),
                    user_prompt=self.prompt_builder.build_generate_user_prompt(
                        requirement_text=requirement_text,
                        page_no=page_no,
                        page_name=page_name,
                        page_type=page_type,
                        page_title=page_title,
                        svg_content=svg_content,
                    ),
                    model=model,
                    enable_thinking=enable_thinking,
                )
                svg_text = self._extract_svg(content)
                if not svg_text:
                    logger.warning("LLM 返回内容中未找到有效 SVG (page=%s, attempt=%s/%s)", page_no, attempt, max_retries)
                    if attempt < max_retries:
                        time_module.sleep(2 * attempt)
                        continue
                    return self._generate_failed(page_no, page_name, raw_response=content)
                return PageGenerationResult(
                    page_no=page_no,
                    page_name=page_name,
                    generated_svg=svg_text,
                    decision_source="llm",
                    raw_response_text=content,
                )
            except Exception as exc:
                logger.warning("LLM 页面生成失败 (page=%s, attempt=%s/%s): %s", page_no, attempt, max_retries, exc)
                if attempt < max_retries:
                    time_module.sleep(2 * attempt)
        logger.warning("LLM 页面生成重试 %s 次仍失败 (page=%s)，该页将不输出", max_retries, page_no)
        return self._generate_failed(page_no, page_name, raw_response="重试3次仍失败")

    @staticmethod
    def _parse_single_plan_response(content: str, page_no: int, page_name: str) -> PagePlanResult:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        data = json.loads(cleaned)
        if isinstance(data, list):
            data = data[0] if data else {}
        return PagePlanResult(
            page_no=page_no,
            page_name=page_name,
            should_generate=bool(data.get("should_generate", True)),
            skip_reason=str(data.get("skip_reason", "")),
            page_type=str(data.get("page_type", "content")),
            page_title=str(data.get("page_title", "")),
            decision_source="llm",
            raw_response_text=content,
        )

    @staticmethod
    def _plan_fallback_single(page_no: int, page_name: str, total_pages: int = 0) -> PagePlanResult:
        if page_no == 1:
            page_type = "cover"
        elif total_pages > 0 and page_no == total_pages:
            page_type = "end"
        elif "目录" in page_name or "toc" in page_name.lower():
            page_type = "toc"
        elif any(kw in page_name for kw in ["架构", "流程", "时序", "图"]):
            page_type = "diagram"
        else:
            page_type = "content"
        return PagePlanResult(
            page_no=page_no,
            page_name=page_name,
            should_generate=True,
            skip_reason="",
            page_type=page_type,
            page_title=page_name,
            decision_source="heuristic",
        )

    @staticmethod
    def _extract_svg(content: str) -> str | None:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        match = re.search(r"<svg[\s>].*</svg>", cleaned, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(0).strip()
        if cleaned.startswith("<svg") or cleaned.startswith("<?xml"):
            return cleaned
        return None

    @staticmethod
    def _generate_fallback(page_no: int, page_name: str, raw_response: str | None = None) -> PageGenerationResult:
        return PageGenerationResult(
            page_no=page_no,
            page_name=page_name,
            generated_svg=None,
            decision_source="heuristic",
            raw_response_text=raw_response,
        )

    @staticmethod
    def _generate_failed(page_no: int, page_name: str, raw_response: str | None = None) -> PageGenerationResult:
        return PageGenerationResult(
            page_no=page_no,
            page_name=page_name,
            generated_svg=None,
            decision_source="failed",
            raw_response_text=raw_response,
        )
