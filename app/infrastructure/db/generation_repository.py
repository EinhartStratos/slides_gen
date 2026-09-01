from __future__ import annotations

from typing import Any

from app.core.utils import json_dumps
from app.infrastructure.db.mysql import MySQLDatabase


class GenerationRepository:
    def __init__(self, db: MySQLDatabase) -> None:
        self.db = db

    def create(self, payload: dict[str, Any]) -> None:
        sql = """
        INSERT INTO sg_generation_request (
            generation_id, api_key, template_id, generation_mode,
            requirement_text, custom_requirements, request_payload_json,
            auto_compose, status, warning_message, requirement_text_chars,
            planning_manifest_ftp_path,
            body_task_id, diagram_task_id, compose_task_id,
            body_status, diagram_status, compose_status
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s,
            %s, %s, %s,
            %s, %s, %s
        )
        """
        params = (
            payload["generation_id"],
            payload["api_key"],
            payload.get("template_id"),
            payload["generation_mode"],
            payload["requirement_text"],
            payload.get("custom_requirements"),
            payload.get("request_payload_json"),
            1 if payload.get("auto_compose", True) else 0,
            payload.get("status", "pending"),
            payload.get("warning_message"),
            payload.get("requirement_text_chars", 0),
            payload.get("planning_manifest_ftp_path"),
            payload.get("body_task_id"),
            payload.get("diagram_task_id"),
            payload.get("compose_task_id"),
            payload.get("body_status", "not_requested"),
            payload.get("diagram_status", "not_requested"),
            payload.get("compose_status", "not_requested"),
        )
        self.db.execute(sql, params)

    def get(self, generation_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM sg_generation_request WHERE generation_id = %s LIMIT 1",
            (generation_id,),
        )

    def get_owned(self, generation_id: str, api_key: str) -> dict[str, Any] | None:
        sql = "SELECT * FROM sg_generation_request WHERE generation_id = %s AND api_key = %s LIMIT 1"
        return self.db.fetch_one(sql, (generation_id, api_key))

    def list(self, api_key: str, offset: int, limit: int) -> list[dict[str, Any]]:
        sql = """
        SELECT * FROM sg_generation_request
        WHERE api_key = %s
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """
        return self.db.fetch_all(sql, (api_key, limit, offset))

    def update(self, generation_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = %s" for key in fields)
        params = tuple(fields.values()) + (generation_id,)
        sql = f"UPDATE sg_generation_request SET {assignments} WHERE generation_id = %s"
        self.db.execute(sql, params)

    def update_child_task_id(
        self,
        generation_id: str,
        child_field: str,
        task_id: str,
        status_field: str,
        status: str,
    ) -> None:
        self.update(
            generation_id,
            {
                child_field: task_id,
                status_field: status,
            },
        )

    def set_payload(self, generation_id: str, payload: dict[str, Any]) -> None:
        self.update(generation_id, {"request_payload_json": json_dumps(payload)})
