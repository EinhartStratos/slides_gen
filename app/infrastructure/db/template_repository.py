from __future__ import annotations

from typing import Any

from app.infrastructure.db.mysql import MySQLDatabase


class TemplateRepository:
    def __init__(self, db: MySQLDatabase) -> None:
        self.db = db

    def create(self, payload: dict[str, Any]) -> None:
        sql = """
        INSERT INTO sg_template (
            template_id, api_key, template_name, source_type, source_filename,
            source_ftp_path, imported_svg_dir_ftp_path, imported_svg_flat_dir_ftp_path,
            assets_ftp_dir_path, manifest_ftp_path, slide_count,
            slide_width_emu, slide_height_emu, is_builtin, status
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s
        )
        """
        params = (
            payload["template_id"],
            payload.get("api_key"),
            payload["template_name"],
            payload.get("source_type", "custom"),
            payload.get("source_filename"),
            payload.get("source_ftp_path"),
            payload.get("imported_svg_dir_ftp_path"),
            payload.get("imported_svg_flat_dir_ftp_path"),
            payload.get("assets_ftp_dir_path"),
            payload.get("manifest_ftp_path"),
            payload.get("slide_count"),
            payload.get("slide_width_emu"),
            payload.get("slide_height_emu"),
            1 if payload.get("is_builtin") else 0,
            payload.get("status", "ready"),
        )
        self.db.execute(sql, params)

    def get_by_id(self, template_id: str) -> dict[str, Any] | None:
        sql = "SELECT * FROM sg_template WHERE template_id = %s LIMIT 1"
        return self.db.fetch_one(sql, (template_id,))

    def get_accessible_by_id(self, template_id: str, api_key: str) -> dict[str, Any] | None:
        sql = """
        SELECT *
        FROM sg_template
        WHERE template_id = %s AND (api_key = %s OR is_builtin = 1)
        LIMIT 1
        """
        return self.db.fetch_one(sql, (template_id, api_key))

    def get_latest_builtin(self) -> dict[str, Any] | None:
        sql = """
        SELECT *
        FROM sg_template
        WHERE is_builtin = 1 AND status = 'ready'
        ORDER BY created_at DESC
        LIMIT 1
        """
        return self.db.fetch_one(sql)

    def list_for_api_key(self, api_key: str | None) -> list[dict[str, Any]]:
        sql = """
        SELECT *
        FROM sg_template
        WHERE api_key = %s OR is_builtin = 1
        ORDER BY is_builtin DESC, created_at DESC
        """
        return self.db.fetch_all(sql, (api_key,))
