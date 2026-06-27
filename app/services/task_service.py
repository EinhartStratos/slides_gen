from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json

from app.core.constants import TASK_STATUS_FAILED, TASK_STATUS_PENDING, TASK_STATUS_RESUMING, TASK_STATUS_STOPPED, TASK_STATUS_STOPPING
from app.core.exceptions import ConflictError, NotFoundError
from app.core.utils import generate_id, json_dumps, to_iso
from app.infrastructure.db.task_repository import TaskRepository
from app.infrastructure.ppt_master.project_workspace import ProjectWorkspace
from app.infrastructure.storage.ftp import FtpStorage
from app.schemas.task import CreateGenerationTaskRequest
from app.services.builtin_template_service import BuiltinTemplateService
from app.services.template_service import TemplateService


class TaskService:
    def __init__(
        self,
        repository: TaskRepository,
        workspace: ProjectWorkspace,
        ftp: FtpStorage,
        template_service: TemplateService,
        builtin_template_service: BuiltinTemplateService,
        default_template_id: str | None,
    ) -> None:
        self.repository = repository
        self.workspace = workspace
        self.ftp = ftp
        self.template_service = template_service
        self.builtin_template_service = builtin_template_service
        self.default_template_id = default_template_id

    def create_task(self, api_key: str, request: CreateGenerationTaskRequest) -> dict:
        if request.template_id:
            template = self.template_service.get_accessible_template(api_key, request.template_id)
        elif self.default_template_id:
            try:
                template = self.template_service.get_template(self.default_template_id)
            except NotFoundError:
                template = self.builtin_template_service.ensure_default_template()
        else:
            template = self.builtin_template_service.ensure_default_template()
        task_id = request.task_id or generate_id("task")
        existing = self.repository.get_task(task_id)
        # if existing is not None:
        #     raise ConflictError(f"任务ID已存在: {task_id}")

        task_workspace = self.workspace.task(task_id)
        self.workspace.ensure_task_dirs(task_workspace)

        request_payload = request.model_dump(mode="json", exclude_none=True)
        task_workspace.request_json_path.write_text(json_dumps(request_payload), encoding="utf-8")
        task_workspace.requirement_path.write_text(request.requirement_text, encoding="utf-8")

        remote_root = self.ftp.join(self.ftp.settings.ftp_root_dir, "tasks", task_id)
        ftp_task_dir = self.ftp.ensure_dir(remote_root)
        ftp_request_path = self.ftp.upload_file(task_workspace.request_json_path, self.ftp.join(remote_root, "request", "request.json"))
        ftp_requirement_path = self.ftp.upload_file(task_workspace.requirement_path, self.ftp.join(remote_root, "input", "requirement.md"))
        ftp_template_snapshot_dir = self.ftp.join(remote_root, "template_snapshot")
        ftp_svg_output_dir = self.ftp.join(remote_root, "svg_output")
        ftp_svg_final_dir = self.ftp.join(remote_root, "svg_final")
        ftp_validation_report_path = self.ftp.join(remote_root, "validation", "validation_report.json")
        ftp_result_pptx_path = self.ftp.join(remote_root, "exports", (request.options.output_filename if request.options and request.options.output_filename else "generated.pptx"))

        self.repository.create_task(
            {
                "task_id": task_id,
                "api_key": api_key,
                "template_id": template["template_id"],
                "requirement_text": request.requirement_text,
                "request_payload_json": json_dumps(request_payload),
                "status": TASK_STATUS_PENDING,
                "current_stage": "queued",
                "progress": 0,
                "stop_requested": False,
                "resume_count": 0,
                "ftp_task_dir": ftp_task_dir,
                "ftp_request_path": ftp_request_path,
                "ftp_requirement_path": ftp_requirement_path,
                "ftp_template_snapshot_dir": ftp_template_snapshot_dir,
                "ftp_svg_output_dir": ftp_svg_output_dir,
                "ftp_svg_final_dir": ftp_svg_final_dir,
                "ftp_validation_report_path": ftp_validation_report_path,
                "ftp_result_pptx_path": ftp_result_pptx_path,
            }
        )
        self.create_event(task_id, api_key, "created", "queued", f"任务已创建，使用模板 {template['template_name']}")
        return self.get_task_summary(api_key, task_id)

    def get_task(self, api_key: str, task_id: str) -> dict:
        task = self.repository.get_owned_task(task_id, api_key)
        if task is None:
            raise NotFoundError(f"任务不存在: {task_id}")
        return task

    def get_task_summary(self, api_key: str, task_id: str) -> dict:
        task = self.get_task(api_key, task_id)
        return {
            "task_id": task["task_id"],
            "status": task["status"],
            "current_stage": task["current_stage"],
            "progress": float(task["progress"]),
            "template_id": task.get("template_id"),
            "ftp_result_pptx_path": task.get("ftp_result_pptx_path"),
            "error_message": task.get("error_message"),
            "created_at": to_iso(task.get("created_at")),
            "completed_at": to_iso(task.get("completed_at")),
        }

    def list_tasks(self, api_key: str, status: str | None, offset: int, limit: int, ids_only: bool) -> list[dict] | list[str]:
        if ids_only:
            return [row["task_id"] for row in self.repository.list_task_ids(api_key, status)]
        rows = self.repository.list_tasks(api_key, status, offset, limit)
        return [
            {
                "task_id": row["task_id"],
                "status": row["status"],
                "current_stage": row["current_stage"],
                "progress": float(row["progress"]),
                "template_id": row.get("template_id"),
                "ftp_result_pptx_path": row.get("ftp_result_pptx_path"),
                "error_message": row.get("error_message"),
                "created_at": to_iso(row.get("created_at")),
                "completed_at": to_iso(row.get("completed_at")),
            }
            for row in rows
        ]

    def list_events(self, api_key: str, task_id: str, limit: int = 100) -> list[dict]:
        self.get_task(api_key, task_id)
        rows = self.repository.list_events(task_id, limit)
        items: list[dict] = []
        for row in rows:
            detail = row.get("event_detail_json")
            if isinstance(detail, str) and detail:
                try:
                    detail = json.loads(detail)
                except json.JSONDecodeError:
                    pass
            items.append(
                {
                    "event_id": row["event_id"],
                    "task_id": row["task_id"],
                    "page_no": row.get("page_no"),
                    "event_type": row["event_type"],
                    "event_stage": row.get("event_stage"),
                    "event_message": row.get("event_message"),
                    "event_detail": detail,
                    "created_at": to_iso(row.get("created_at")),
                }
            )
        return items

    def list_pages(self, api_key: str, task_id: str) -> list[dict]:
        self.get_task(api_key, task_id)
        rows = self.repository.list_pages(task_id)
        return [
            {
                "task_id": row["task_id"],
                "page_no": row["page_no"],
                "page_name": row.get("page_name"),
                "should_generate": row.get("should_generate"),
                "skip_reason": row.get("skip_reason"),
                "status": row["status"],
                "diagram_kind": row.get("diagram_kind"),
                "ftp_generated_svg_path": row.get("ftp_generated_svg_path"),
                "ftp_final_svg_path": row.get("ftp_final_svg_path"),
                "error_message": row.get("error_message"),
            }
            for row in rows
        ]

    def list_artifacts(self, api_key: str, task_id: str) -> list[dict]:
        self.get_task(api_key, task_id)
        rows = self.repository.list_artifacts(task_id)
        return [
            {
                "artifact_id": row["artifact_id"],
                "task_id": row["task_id"],
                "page_no": row.get("page_no"),
                "artifact_type": row["artifact_type"],
                "ftp_path": row["ftp_path"],
                "file_name": row.get("file_name"),
                "is_final": bool(row.get("is_final")),
                "status": row["status"],
                "created_at": to_iso(row.get("created_at")),
            }
            for row in rows
        ]

    def request_stop(self, api_key: str, task_id: str) -> dict:
        task = self.get_task(api_key, task_id)
        if task["status"] in {"completed", "cancelled"}:
            raise ConflictError(f"当前状态不允许停止: {task['status']}")
        next_status = TASK_STATUS_STOPPING if task["status"] in {"running", "resuming"} else task["status"]
        self.repository.update_task(task_id, {"stop_requested": 1, "status": next_status, "current_stage": "stop_requested"})
        self.create_event(task_id, api_key, "stop_requested", "stop_requested", "已收到停止请求")
        updated = self.get_task(api_key, task_id)
        return {
            "task_id": task_id,
            "status": updated["status"],
            "stop_requested": bool(updated["stop_requested"]),
            "resume_count": int(updated["resume_count"]),
        }

    def mark_resume_requested(self, api_key: str, task_id: str) -> dict:
        task = self.get_task(api_key, task_id)
        if task["status"] not in {TASK_STATUS_STOPPED, TASK_STATUS_FAILED}:
            raise ConflictError(f"当前状态不允许恢复: {task['status']}")
        self.repository.update_task(
            task_id,
            {
                "status": TASK_STATUS_RESUMING,
                "current_stage": "queued",
                "stop_requested": 0,
                "error_code": None,
                "error_message": None,
                "stopped_at": None,
                "completed_at": None,
                "resume_count": int(task["resume_count"]) + 1,
            },
        )
        self.create_event(task_id, api_key, "resumed", "queued", "任务已进入恢复队列")
        updated = self.get_task(api_key, task_id)
        return {
            "task_id": task_id,
            "status": updated["status"],
            "stop_requested": bool(updated["stop_requested"]),
            "resume_count": int(updated["resume_count"]),
        }

    def create_event(self, task_id: str, api_key: str | None, event_type: str, event_stage: str | None, message: str, page_no: int | None = None, detail: dict | None = None) -> None:
        self.repository.create_event(
            {
                "event_id": generate_id("evt"),
                "task_id": task_id,
                "api_key": api_key,
                "page_no": page_no,
                "event_type": event_type,
                "event_stage": event_stage,
                "event_message": message,
                "event_detail_json": detail,
            }
        )

    def create_artifact(self, task_id: str, artifact_type: str, ftp_path: str, file_name: str, page_no: int | None = None, is_final: bool = False, file_size_bytes: int | None = None, content_type: str | None = None) -> None:
        suffix = Path(file_name).suffix if file_name else ""
        self.repository.create_artifact(
            {
                "artifact_id": generate_id("art"),
                "task_id": task_id,
                "page_no": page_no,
                "artifact_type": artifact_type,
                "ftp_path": ftp_path,
                "file_name": file_name,
                "file_ext": suffix,
                "content_type": content_type,
                "file_size_bytes": file_size_bytes,
                "is_final": is_final,
            }
        )

    def touch_running(self, task_id: str, status: str, stage: str) -> None:
        now = datetime.now()
        fields = {"status": status, "current_stage": stage, "last_heartbeat_at": now}
        if status in {"running", "resuming"}:
            fields.setdefault("started_at", now)
        self.repository.update_task(task_id, fields)
