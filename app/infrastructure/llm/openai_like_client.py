from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from app.core.config import Settings
from app.infrastructure.llm.base import BasePageAnalysisClient, PageAnalysisResult
from app.infrastructure.llm.prompt_builder import PageAnalysisPromptBuilder


logger = logging.getLogger(__name__)


class OpenAILikePageAnalysisClient(BasePageAnalysisClient):
    def __init__(self, settings: Settings, prompt_builder: PageAnalysisPromptBuilder) -> None:
        self.settings = settings
        self.prompt_builder = prompt_builder

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_base_url and self.settings.llm_model)

    def analyze_page(
        self,
        api_key: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        svg_excerpt: str,
    ) -> PageAnalysisResult:
        if not self.enabled or not api_key.strip():
            return self._fallback(requirement_text, page_no, page_name)
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
                            svg_excerpt=svg_excerpt,
                        ),
                    },
                ],
                "response_format": {"type": "json_object"},
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
            parsed = self._parse_content(content, page_no, page_name)
            parsed.raw_response_text = content
            parsed.decision_source = "llm"
            return parsed
        except Exception as exc:
            logger.warning("LLM 分页分析失败，回退启发式逻辑: %s", exc)
            fallback = self._fallback(requirement_text, page_no, page_name)
            fallback.raw_response_text = str(exc)
            return fallback

    def _parse_content(self, content: str, page_no: int, page_name: str) -> PageAnalysisResult:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        payload = json.loads(cleaned)
        payload.setdefault("page_no", page_no)
        payload.setdefault("page_name", page_name)
        payload.setdefault("skip_reason", "")
        payload.setdefault("page_title", page_name)
        payload.setdefault("page_summary", "")
        payload.setdefault("bullet_points", [])
        payload.setdefault("diagram_kind", None)
        payload.setdefault("decision_source", "llm")
        bullet_points = payload.get("bullet_points") or []
        payload["bullet_points"] = [str(item).strip() for item in bullet_points if str(item).strip()][:5]
        return PageAnalysisResult.model_validate(payload)

    def _fallback(self, requirement_text: str, page_no: int, page_name: str) -> PageAnalysisResult:
        cleaned = re.sub(r"\s+", " ", requirement_text).strip()
        if not cleaned:
            return PageAnalysisResult(
                page_no=page_no,
                page_name=page_name,
                should_generate=False,
                skip_reason="需求文本为空，无法生成该页内容",
                page_title=page_name,
                page_summary="",
                bullet_points=[],
                diagram_kind=None,
                decision_source="heuristic",
            )
        sentences = [segment.strip() for segment in re.split(r"[。！？\n]", requirement_text) if segment.strip()]
        summary = sentences[0] if sentences else cleaned[:120]
        bullet_points = [segment[:60] for segment in sentences[:3]]
        lowered = cleaned.lower()
        diagram_kind = None
        if any(keyword in lowered for keyword in ["架构", "architecture"]):
            diagram_kind = "architecture"
        elif any(keyword in lowered for keyword in ["时序", "sequence"]):
            diagram_kind = "sequence"
        elif any(keyword in lowered for keyword in ["流程", "flow"]):
            diagram_kind = "flowchart"
        return PageAnalysisResult(
            page_no=page_no,
            page_name=page_name,
            should_generate=True,
            skip_reason="",
            page_title=page_name,
            page_summary=summary[:140],
            bullet_points=bullet_points,
            diagram_kind=diagram_kind,
            decision_source="heuristic",
        )
