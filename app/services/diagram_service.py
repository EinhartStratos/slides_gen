from __future__ import annotations

import re
from pathlib import Path

from app.core.exceptions import NotFoundError
from app.core.utils import json_loads, to_iso
from app.infrastructure.db.diagram_repository import DiagramRepository
from app.infrastructure.db.task_repository import TaskRepository
from app.infrastructure.ppt_master.project_workspace import ProjectWorkspace
from app.infrastructure.storage.ftp import FtpStorage


class DiagramService:
    """独立图形查询、预览与下载服务。"""

    def __init__(
        self,
        task_repository: TaskRepository,
        diagram_repository: DiagramRepository,
        workspace: ProjectWorkspace,
        ftp: FtpStorage,
    ) -> None:
        self.task_repository = task_repository
        self.diagram_repository = diagram_repository
        self.workspace = workspace
        self.ftp = ftp

    def _get_diagram(self, api_key: str, task_id: str, diagram_id: str) -> dict:
        task = self.task_repository.get_owned_task(task_id, api_key)
        if task is None:
            raise NotFoundError(f"任务不存在或无权限: {task_id}")
        diagram = self.diagram_repository.get_by_task(task_id, diagram_id)
        if diagram is None:
            raise NotFoundError(f"图形不存在: {diagram_id}")
        return diagram

    def get_metadata(self, api_key: str, task_id: str, diagram_id: str) -> dict:
        diagram = self._get_diagram(api_key, task_id, diagram_id)
        return self._to_schema(diagram)

    def _to_schema(self, row: dict) -> dict:
        evidence_quotes = []
        applied_rule_ids = []
        layout_decision = None
        try:
            if row.get("evidence_quotes_json"):
                evidence_quotes = json_loads(row["evidence_quotes_json"]) or []
        except Exception:
            pass
        try:
            if row.get("applied_rule_ids_json"):
                applied_rule_ids = json_loads(row["applied_rule_ids_json"]) or []
        except Exception:
            pass
        try:
            if row.get("layout_decision_json"):
                layout_decision = json_loads(row["layout_decision_json"])
        except Exception:
            pass
        return {
            "diagram_id": row["diagram_id"],
            "generation_id": row["generation_id"],
            "task_id": row["task_id"],
            "page_key": row.get("page_key"),
            "template_page_no": row.get("template_page_no"),
            "final_page_no": row.get("final_page_no"),
            "diagram_title": row.get("diagram_title"),
            "section_title": row.get("section_title"),
            "diagram_kind": row.get("diagram_kind"),
            "diagram_description": row.get("diagram_description"),
            "version": int(row.get("version", 1)),
            "status": row["status"],
            "validation_status": row.get("validation_status"),
            "ftp_original_svg_path": row.get("ftp_original_svg_path"),
            "ftp_final_svg_path": row.get("ftp_final_svg_path"),
            "evidence_quotes": evidence_quotes,
            "applied_rule_ids": applied_rule_ids,
            "layout_decision": layout_decision,
            "error_message": row.get("error_message"),
            "created_at": to_iso(row.get("created_at")),
            "updated_at": to_iso(row.get("updated_at")),
            "completed_at": to_iso(row.get("completed_at")),
        }

    def preview_svg(self, api_key: str, task_id: str, diagram_id: str) -> str:
        diagram = self._get_diagram(api_key, task_id, diagram_id)
        ftp_path = diagram.get("ftp_final_svg_path") or diagram.get("ftp_original_svg_path")
        if not ftp_path:
            raise NotFoundError(f"图形尚未生成 SVG: {diagram_id}")
        local_path = self.workspace.temp_path(f"diagram_preview_{diagram_id}.svg")
        self.ftp.download_file(str(ftp_path), local_path)
        return self._sanitize_svg(local_path)

    def download_svg(self, api_key: str, task_id: str, diagram_id: str) -> Path:
        diagram = self._get_diagram(api_key, task_id, diagram_id)
        ftp_path = diagram.get("ftp_final_svg_path") or diagram.get("ftp_original_svg_path")
        if not ftp_path:
            raise NotFoundError(f"图形尚未生成 SVG: {diagram_id}")
        local_path = self.workspace.temp_path(f"diagram_{diagram_id}.svg")
        self.ftp.download_file(str(ftp_path), local_path)
        return local_path

    @staticmethod
    def _sanitize_svg(svg_path: Path) -> str:
        """白名单净化 SVG：移除脚本、事件属性、外部引用、foreignObject 等。"""
        text = svg_path.read_text(encoding="utf-8")
        # 移除 CDATA 和注释
        text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<foreignObject[\s\S]*?</foreignObject>", "", text, flags=re.IGNORECASE)
        # 移除事件属性
        text = re.sub(r"\s+on\w+\s*=\s*['\"][^'\"]*['\"]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+on\w+\s*=\s*[^\s>]*", "", text, flags=re.IGNORECASE)
        # 移除外部引用
        text = re.sub(r"\s+xlink:href\s*=\s*['\"][^'\"]*['\"]", "", text, flags=re.IGNORECASE)
        # 移除 html 命名空间及 iframe/object/embed
        text = re.sub(r"<(iframe|object|embed|audio|video)\b[\s\S]*?\/?>", "", text, flags=re.IGNORECASE)
        # 移除 xml 处理指令外的 DOCTYPE
        text = re.sub(r"<!DOCTYPE\b[^>]*>", "", text, flags=re.IGNORECASE)
        return text.strip()
