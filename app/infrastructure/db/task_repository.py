from __future__ import annotations

from typing import Any

from app.core.utils import json_dumps
from app.infrastructure.db.mysql import MySQLDatabase


class TaskRepository:
    def __init__(self, db: MySQLDatabase) -> None:
        self.db = db

    def create_task(self, payload: dict[str, Any]) -> None:
        sql = """
        INSERT INTO sg_generation_task (
            task_id, api_key, template_id, requirement_text, request_payload_json,
            status, current_stage, progress, stop_requested, resume_count,
            total_pages, processed_pages, completed_pages, skipped_pages, failed_pages,
            ftp_task_dir, ftp_request_path, ftp_requirement_path, ftp_template_snapshot_dir,
            ftp_svg_output_dir, ftp_svg_final_dir, ftp_validation_report_path,
            ftp_result_pptx_path, error_code, error_message
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s
        )
        """
        params = (
            payload["task_id"],
            payload["api_key"],
            payload.get("template_id"),
            payload["requirement_text"],
            payload.get("request_payload_json"),
            payload.get("status", "pending"),
            payload.get("current_stage", "queued"),
            payload.get("progress", 0),
            1 if payload.get("stop_requested") else 0,
            payload.get("resume_count", 0),
            payload.get("total_pages"),
            payload.get("processed_pages", 0),
            payload.get("completed_pages", 0),
            payload.get("skipped_pages", 0),
            payload.get("failed_pages", 0),
            payload.get("ftp_task_dir"),
            payload.get("ftp_request_path"),
            payload.get("ftp_requirement_path"),
            payload.get("ftp_template_snapshot_dir"),
            payload.get("ftp_svg_output_dir"),
            payload.get("ftp_svg_final_dir"),
            payload.get("ftp_validation_report_path"),
            payload.get("ftp_result_pptx_path"),
            payload.get("error_code"),
            payload.get("error_message"),
        )
        self.db.execute(sql, params)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one("SELECT * FROM sg_generation_task WHERE task_id = %s LIMIT 1", (task_id,))

    def get_owned_task(self, task_id: str, api_key: str) -> dict[str, Any] | None:
        sql = "SELECT * FROM sg_generation_task WHERE task_id = %s AND api_key = %s LIMIT 1"
        return self.db.fetch_one(sql, (task_id, api_key))

    def list_tasks(self, api_key: str, status: str | None, offset: int, limit: int) -> list[dict[str, Any]]:
        sql = "SELECT * FROM sg_generation_task WHERE api_key = %s"
        params: list[Any] = [api_key]
        if status:
            sql += " AND status = %s"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        return self.db.fetch_all(sql, tuple(params))

    def list_task_ids(self, api_key: str, status: str | None) -> list[dict[str, Any]]:
        sql = "SELECT task_id FROM sg_generation_task WHERE api_key = %s"
        params: list[Any] = [api_key]
        if status:
            sql += " AND status = %s"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        return self.db.fetch_all(sql, tuple(params))

    def update_task(self, task_id: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{key} = %s" for key in fields)
        params = tuple(fields.values()) + (task_id,)
        sql = f"UPDATE sg_generation_task SET {assignments} WHERE task_id = %s"
        self.db.execute(sql, params)

    def upsert_page(self, payload: dict[str, Any]) -> None:
        sql = """
        INSERT INTO sg_generation_task_page (
            task_id, page_no, page_name, template_svg_ftp_path, analysis_json_ftp_path,
            status, should_generate, skip_reason, diagram_kind,
            ftp_generated_svg_path, ftp_final_svg_path,
            validation_status, validation_message, error_message,
            started_at, completed_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s
        ) ON DUPLICATE KEY UPDATE
            page_name = VALUES(page_name),
            template_svg_ftp_path = VALUES(template_svg_ftp_path),
            analysis_json_ftp_path = VALUES(analysis_json_ftp_path),
            status = VALUES(status),
            should_generate = VALUES(should_generate),
            skip_reason = VALUES(skip_reason),
            diagram_kind = VALUES(diagram_kind),
            ftp_generated_svg_path = VALUES(ftp_generated_svg_path),
            ftp_final_svg_path = VALUES(ftp_final_svg_path),
            validation_status = VALUES(validation_status),
            validation_message = VALUES(validation_message),
            error_message = VALUES(error_message),
            started_at = VALUES(started_at),
            completed_at = VALUES(completed_at)
        """
        params = (
            payload["task_id"],
            payload["page_no"],
            payload.get("page_name"),
            payload.get("template_svg_ftp_path"),
            payload.get("analysis_json_ftp_path"),
            payload.get("status", "pending"),
            payload.get("should_generate"),
            payload.get("skip_reason"),
            payload.get("diagram_kind"),
            payload.get("ftp_generated_svg_path"),
            payload.get("ftp_final_svg_path"),
            payload.get("validation_status"),
            payload.get("validation_message"),
            payload.get("error_message"),
            payload.get("started_at"),
            payload.get("completed_at"),
        )
        self.db.execute(sql, params)

    def list_pages(self, task_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM sg_generation_task_page WHERE task_id = %s ORDER BY page_no ASC",
            (task_id,),
        )

    def create_artifact(self, payload: dict[str, Any]) -> None:
        sql = """
        INSERT INTO sg_generation_task_artifact (
            artifact_id, task_id, page_no, artifact_type, ftp_path,
            file_name, file_ext, content_type, file_size_bytes, checksum_md5,
            is_final, status
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s
        )
        """
        params = (
            payload["artifact_id"],
            payload["task_id"],
            payload.get("page_no"),
            payload["artifact_type"],
            payload["ftp_path"],
            payload.get("file_name"),
            payload.get("file_ext"),
            payload.get("content_type"),
            payload.get("file_size_bytes"),
            payload.get("checksum_md5"),
            1 if payload.get("is_final") else 0,
            payload.get("status", "ready"),
        )
        self.db.execute(sql, params)

    def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM sg_generation_task_artifact WHERE task_id = %s ORDER BY created_at DESC",
            (task_id,),
        )

    def list_events(self, task_id: str, limit: int = 100) -> list[dict[str, Any]]:
        sql = """
        SELECT *
        FROM sg_generation_task_event
        WHERE task_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """
        return self.db.fetch_all(sql, (task_id, limit))

    def create_event(self, payload: dict[str, Any]) -> None:
        sql = """
        INSERT INTO sg_generation_task_event (
            event_id, task_id, api_key, page_no, event_type,
            event_stage, event_message, event_detail_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            payload["event_id"],
            payload["task_id"],
            payload.get("api_key"),
            payload.get("page_no"),
            payload["event_type"],
            payload.get("event_stage"),
            payload.get("event_message"),
            json_dumps(payload.get("event_detail_json")) if payload.get("event_detail_json") is not None else None,
        )
        self.db.execute(sql, params)
