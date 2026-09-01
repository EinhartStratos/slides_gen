from __future__ import annotations

from typing import Any

from app.core.utils import json_dumps
from app.infrastructure.db.mysql import MySQLDatabase


class DiagramRepository:
    def __init__(self, db: MySQLDatabase) -> None:
        self.db = db

    def create(self, payload: dict[str, Any]) -> None:
        sql = """
        INSERT INTO sg_generation_diagram (
            diagram_id, generation_id, task_id, page_key, template_page_no, final_page_no,
            diagram_title, section_title, diagram_kind, diagram_description, version, status,
            ftp_original_svg_path, ftp_final_svg_path,
            evidence_quotes_json, applied_rule_ids_json, layout_decision_json,
            validation_status, error_message
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s
        )
        """
        params = (
            payload["diagram_id"],
            payload["generation_id"],
            payload["task_id"],
            payload.get("page_key"),
            payload.get("template_page_no"),
            payload.get("final_page_no"),
            payload.get("diagram_title"),
            payload.get("section_title"),
            payload.get("diagram_kind"),
            payload.get("diagram_description"),
            payload.get("version", 1),
            payload.get("status", "pending"),
            payload.get("ftp_original_svg_path"),
            payload.get("ftp_final_svg_path"),
            json_dumps(payload.get("evidence_quotes_json")) if payload.get("evidence_quotes_json") is not None else None,
            json_dumps(payload.get("applied_rule_ids_json")) if payload.get("applied_rule_ids_json") is not None else None,
            json_dumps(payload.get("layout_decision_json")) if payload.get("layout_decision_json") is not None else None,
            payload.get("validation_status"),
            payload.get("error_message"),
        )
        self.db.execute(sql, params)

    def get(self, diagram_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM sg_generation_diagram WHERE diagram_id = %s LIMIT 1",
            (diagram_id,),
        )

    def get_owned(self, diagram_id: str, api_key: str) -> dict[str, Any] | None:
        sql = """
        SELECT d.*
        FROM sg_generation_diagram d
        JOIN sg_generation_request g ON d.generation_id = g.generation_id
        WHERE d.diagram_id = %s AND g.api_key = %s
        LIMIT 1
        """
        return self.db.fetch_one(sql, (diagram_id, api_key))

    def get_by_task(self, task_id: str, diagram_id: str) -> dict[str, Any] | None:
        sql = "SELECT * FROM sg_generation_diagram WHERE task_id = %s AND diagram_id = %s LIMIT 1"
        return self.db.fetch_one(sql, (task_id, diagram_id))

    def list_by_generation(self, generation_id: str) -> list[dict[str, Any]]:
        sql = """
        SELECT * FROM sg_generation_diagram
        WHERE generation_id = %s
        ORDER BY created_at ASC
        """
        return self.db.fetch_all(sql, (generation_id,))

    def list_by_task(self, task_id: str) -> list[dict[str, Any]]:
        sql = """
        SELECT * FROM sg_generation_diagram
        WHERE task_id = %s
        ORDER BY created_at ASC
        """
        return self.db.fetch_all(sql, (task_id,))

    def update(self, diagram_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = %s" for key in fields)
        params = tuple(fields.values()) + (diagram_id,)
        sql = f"UPDATE sg_generation_diagram SET {assignments} WHERE diagram_id = %s"
        self.db.execute(sql, params)

    def update_final_page_no(self, diagram_id: str, final_page_no: int) -> None:
        self.update(diagram_id, {"final_page_no": final_page_no})
