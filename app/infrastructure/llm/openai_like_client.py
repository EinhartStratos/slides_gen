from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from app.core.config import Settings
from app.infrastructure.llm.base import BasePageGenerationClient, PageGenerationResult
from app.infrastructure.llm.prompt_builder import PageAnalysisPromptBuilder


logger = logging.getLogger(__name__)


class OpenAILikePageGenerationClient(BasePageGenerationClient):
    def __init__(self, settings: Settings, prompt_builder: PageAnalysisPromptBuilder) -> None:
        self.settings = settings
        self.prompt_builder = prompt_builder

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_base_url and self.settings.llm_model)

    def generate_page_svg(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        svg_content: str,
    ) -> PageGenerationResult:
        if not self.enabled or not api_key.strip():
            return self._fallback(page_no, page_name)
        try:
            payload = {
                "model": self.settings.llm_model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": self.prompt_builder.build_system_prompt()},
                    {
                        "role": "user",
                        "content": self.prompt_builder.build_user_prompt(
                            requirement_text=requirement_text,
                            page_no=page_no,
                            page_name=page_name,
                            svg_excerpt=svg_content,
                        ),
                    },
                ],
            }
            request = urllib.request.Request(
                url=f"{self.settings.llm_base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.settings.llm_timeout_seconds) as response:
                raw = response.read().decode("utf-8")
            model_payload = json.loads(raw)
            content = model_payload["choices"][0]["message"]["content"]
            svg_text = self._extract_svg(content)
            if not svg_text:
                logger.warning("LLM 返回内容中未找到有效 SVG，回退到原始模板")
                return self._fallback(page_no, page_name, raw_response=content)
            return PageGenerationResult(
                page_no=page_no,
                page_name=page_name,
                should_generate=True,
                skip_reason="",
                decision_source="llm",
                generated_svg=svg_text,
                raw_response_text=content,
            )
        except Exception as exc:
            logger.warning("LLM 页面生成失败，回退到原始模板: %s", exc)
            return self._fallback(page_no, page_name, raw_response=str(exc))

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
    def _fallback(page_no: int, page_name: str, raw_response: str | None = None) -> PageGenerationResult:
        return PageGenerationResult(
            page_no=page_no,
            page_name=page_name,
            should_generate=True,
            skip_reason="",
            decision_source="heuristic",
            generated_svg=None,
            raw_response_text=raw_response,
        )
