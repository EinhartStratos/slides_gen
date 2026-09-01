from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from app.core.config import Settings
from app.core.constants import (
    CHILD_STATUS_NOT_REQUESTED,
    GENERATION_MODE_LEGACY_HYBRID,
    GENERATION_STATUS_COMPLETED,
    GENERATION_STATUS_COMPLETED_WITH_WARNINGS,
    GENERATION_STATUS_FAILED,
    GENERATION_STATUS_PENDING,
    GENERATION_STATUS_RUNNING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    TASK_STATUS_RESUMING,
    TASK_STATUS_RUNNING,
    TASK_TYPE_BODY,
    TASK_TYPE_COMPOSE,
    TASK_TYPE_DIAGRAMS,
    TASK_TYPE_LEGACY,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.utils import generate_id, json_dumps, to_iso
from app.infrastructure.db.diagram_repository import DiagramRepository
from app.infrastructure.db.generation_repository import GenerationRepository
from app.infrastructure.db.task_repository import TaskRepository
from app.infrastructure.ppt_master.project_workspace import ProjectWorkspace
from app.infrastructure.storage.ftp import FtpStorage
from app.infrastructure.tasking.runner import TaskRunner
from app.services.orchestration_service import OrchestrationService
from app.schemas.generation import CreateGenerationRequest
from app.services.builtin_template_service import BuiltinTemplateService
from app.services.task_service import TaskService
from app.services.template_service import TemplateService


class GenerationService:
    """Generation 父记录与子任务编排服务。"""

    def __init__(
        self,
        settings: Settings,
        generation_repository: GenerationRepository,
        task_repository: TaskRepository,
        diagram_repository: DiagramRepository,
        task_service: TaskService,
        template_service: TemplateService,
        builtin_template_service: BuiltinTemplateService,
        workspace: ProjectWorkspace,
        ftp: FtpStorage,
        task_runner: TaskRunner,
        orchestration_service: OrchestrationService,
    ) -> None:
        self.settings = settings
        self.generation_repository = generation_repository
        self.task_repository = task_repository
        self.diagram_repository = diagram_repository
        self.task_service = task_service
        self.template_service = template_service
        self.builtin_template_service = builtin_template_service
        self.workspace = workspace
        self.ftp = ftp
        self.task_runner = task_runner
        self.orchestration_service = orchestration_service

    def _ensure_template(self, api_key: str, template_id: str | None) -> dict:
        if template_id:
            return self.template_service.get_accessible_template(api_key, template_id)
        if self.settings.default_template_id:
            try:
                return self.template_service.get_template(self.settings.default_template_id)
            except NotFoundError:
                return self.builtin_template_service.ensure_default_template()
        return self.builtin_template_service.ensure_default_template()

    def _validate_length(self, requirement_text: str) -> tuple[bool, str | None]:
        chars = len(requirement_text)
        if chars > self.settings.requirement_text_max_chars:
            raise ValidationError(
                f"requirement_text 超过 {self.settings.requirement_text_max_chars} 字符上限（当前 {chars} 字符）",
            )
        warning = None
        if chars >= self.settings.requirement_text_warn_chars:
            warning = f"requirement_text 已达到 {self.settings.requirement_text_warn_chars} 字符告警线（当前 {chars} 字符）"
        return chars, warning

    def create(
        self,
        api_key: str,
        request: CreateGenerationRequest,
    ) -> dict:
        template = self._ensure_template(api_key, request.template_id)
        chars, warning = self._validate_length(request.requirement_text)

        generation_id = generate_id("gen")
        generation_workspace = self.workspace.generation(generation_id)
        self.workspace.ensure_generation_dirs(generation_workspace)

        request_payload = request.model_dump(mode="json", exclude_none=True)
        generation_workspace.request_json_path.write_text(json_dumps(request_payload), encoding="utf-8")
        generation_workspace.requirement_path.write_text(request.requirement_text, encoding="utf-8")

        remote_root = self.ftp.join(self.ftp.settings.ftp_root_dir, "generations", generation_id)
        ftp_generation_dir = self.ftp.ensure_dir(remote_root)
        ftp_request_path = self.ftp.upload_file(
            generation_workspace.request_json_path,
            self.ftp.join(remote_root, "request", "request.json"),
        )
        ftp_requirement_path = self.ftp.upload_file(
            generation_workspace.requirement_path,
            self.ftp.join(remote_root, "input", "requirement.md"),
        )

        body_task_id = None
        diagram_task_id = None
        body_status = CHILD_STATUS_NOT_REQUESTED
        diagram_status = CHILD_STATUS_NOT_REQUESTED

        if "body" in request.targets:
            body_task_id = self._create_child_task(
                api_key=api_key,
                generation_id=generation_id,
                task_type=TASK_TYPE_BODY,
                template=template,
                requirement_text=request.requirement_text,
                custom_requirements=request.custom_requirements,
                options=request.options,
                ftp_root=remote_root,
                generation_workspace=generation_workspace,
            )
            body_status = TASK_STATUS_PENDING

        if "diagrams" in request.targets:
            diagram_task_id = self._create_child_task(
                api_key=api_key,
                generation_id=generation_id,
                task_type=TASK_TYPE_DIAGRAMS,
                template=template,
                requirement_text=request.requirement_text,
                custom_requirements=request.custom_requirements,
                options=request.options,
                ftp_root=remote_root,
                generation_workspace=generation_workspace,
            )
            diagram_status = TASK_STATUS_PENDING

        compose_status = CHILD_STATUS_NOT_REQUESTED
        if request.auto_compose and body_task_id and diagram_task_id:
            compose_status = CHILD_STATUS_NOT_REQUESTED  # 实际等执行时判断

        if body_task_id:
            self.task_runner.submit(body_task_id, lambda: self.orchestration_service.run_task(api_key, body_task_id))
        if diagram_task_id:
            self.task_runner.submit(diagram_task_id, lambda: self.orchestration_service.run_task(api_key, diagram_task_id))

        self.generation_repository.create(
            {
                "generation_id": generation_id,
                "api_key": api_key,
                "template_id": template["template_id"],
                "generation_mode": request.generation_mode,
                "requirement_text": request.requirement_text,
                "custom_requirements": request.custom_requirements,
                "request_payload_json": json_dumps(request_payload),
                "auto_compose": request.auto_compose,
                "status": GENERATION_STATUS_PENDING,
                "warning_message": warning,
                "requirement_text_chars": chars,
                "planning_manifest_ftp_path": None,
                "body_task_id": body_task_id,
                "diagram_task_id": diagram_task_id,
                "compose_task_id": None,
                "body_status": body_status,
                "diagram_status": diagram_status,
                "compose_status": compose_status,
            }
        )

        summary = self.get_summary(api_key, generation_id)
        summary["warning_message"] = warning
        return summary

    def _create_child_task(
        self,
        api_key: str,
        generation_id: str,
        task_type: str,
        template: dict,
        requirement_text: str,
        custom_requirements: str | None,
        options: object | None,
        ftp_root: str,
        generation_workspace,
    ) -> str:
        task_id = generate_id("task")
        task_workspace = self.workspace.task(task_id)
        self.workspace.ensure_task_dirs(task_workspace)

        request_payload = {
            "custom_requirements": custom_requirements,
            "options": options.model_dump(mode="json", exclude_none=True) if options else {},
            "generation_id": generation_id,
        }
        task_workspace.request_json_path.write_text(json_dumps(request_payload), encoding="utf-8")
        task_workspace.requirement_path.write_text(requirement_text, encoding="utf-8")

        child_payload = {
            "task_id": task_id,
            "api_key": api_key,
            "generation_id": generation_id,
            "task_type": task_type,
            "template_id": template["template_id"],
            "requirement_text": requirement_text,
            "request_payload_json": json_dumps(request_payload),
            "status": TASK_STATUS_PENDING,
            "current_stage": "queued",
            "progress": 0,
        }

        remote_task_dir = self.ftp.join(ftp_root, "tasks", task_type, task_id)
        ftp_task_dir = self.ftp.ensure_dir(remote_task_dir)
        ftp_request_path = self.ftp.upload_file(
            task_workspace.request_json_path,
            self.ftp.join(remote_task_dir, "request", "request.json"),
        )
        ftp_requirement_path = self.ftp.upload_file(
            task_workspace.requirement_path,
            self.ftp.join(remote_task_dir, "input", "requirement.md"),
        )

        self.task_repository.create_task(
            {
                **child_payload,
                "ftp_task_dir": ftp_task_dir,
                "ftp_request_path": ftp_request_path,
                "ftp_requirement_path": ftp_requirement_path,
                "ftp_template_snapshot_dir": self.ftp.join(remote_task_dir, "template_snapshot"),
                "ftp_svg_output_dir": self.ftp.join(remote_task_dir, "svg_output"),
                "ftp_svg_final_dir": self.ftp.join(remote_task_dir, "svg_final"),
                "ftp_validation_report_path": self.ftp.join(remote_task_dir, "validation", "validation_report.json"),
                "ftp_result_pptx_path": self.ftp.join(remote_task_dir, "exports", "generated.pptx"),
            }
        )
        self.task_service.create_event(task_id, api_key, "created", "queued", f"{task_type} 子任务已创建")
        return task_id

    def get_summary(self, api_key: str, generation_id: str) -> dict:
        generation = self.generation_repository.get_owned(generation_id, api_key)
        if generation is None:
            raise NotFoundError(f"Generation 不存在: {generation_id}")

        body_task = None
        diagram_task = None
        compose_task = None
        if generation.get("body_task_id"):
            body_task = self.task_repository.get_task(generation["body_task_id"])
        if generation.get("diagram_task_id"):
            diagram_task = self.task_repository.get_task(generation["diagram_task_id"])
        if generation.get("compose_task_id"):
            compose_task = self.task_repository.get_task(generation["compose_task_id"])

        diagrams = self.diagram_repository.list_by_generation(generation_id)
        artifacts = self._collect_artifacts(generation_id)

        body_pptx_artifact_id = None
        composed_pptx_artifact_id = None
        for art in artifacts:
            if art.get("artifact_type") == "body_pptx" and art.get("is_final"):
                body_pptx_artifact_id = art["artifact_id"]
            if art.get("artifact_type") == "composed_pptx" and art.get("is_final"):
                composed_pptx_artifact_id = art["artifact_id"]

        kept, skipped, diagram_count = self._count_pages_and_diagrams(
            body_task, diagram_task, diagrams
        )

        return {
            "generation_id": generation["generation_id"],
            "generation_mode": generation["generation_mode"],
            "status": generation["status"],
            "auto_compose": bool(generation.get("auto_compose")),
            "requirement_text_chars": int(generation.get("requirement_text_chars", 0)),
            "requirement_text_warning": bool(generation.get("warning_message")),
            "template_id": generation.get("template_id"),
            "body_task_id": generation.get("body_task_id"),
            "diagram_task_id": generation.get("diagram_task_id"),
            "compose_task_id": generation.get("compose_task_id"),
            "body_status": generation.get("body_status"),
            "diagram_status": generation.get("diagram_status"),
            "compose_status": generation.get("compose_status"),
            "kept_page_count": kept,
            "skipped_page_count": skipped,
            "diagram_count": diagram_count,
            "body_pptx_artifact_id": body_pptx_artifact_id,
            "composed_pptx_artifact_id": composed_pptx_artifact_id,
            "has_body_download": body_pptx_artifact_id is not None,
            "has_diagram_downloads": bool(diagrams),
            "has_composed_download": composed_pptx_artifact_id is not None,
            "warning_message": generation.get("warning_message"),
            "error_message": generation.get("error_message"),
            "created_at": to_iso(generation.get("created_at")),
            "completed_at": to_iso(generation.get("completed_at")),
        }

    def _collect_artifacts(self, generation_id: str) -> list[dict]:
        generation = self.generation_repository.get(generation_id)
        if generation is None:
            return []
        artifacts: list[dict] = []
        for task_id in [
            generation.get("body_task_id"),
            generation.get("diagram_task_id"),
            generation.get("compose_task_id"),
        ]:
            if task_id:
                artifacts.extend(self.task_repository.list_artifacts(task_id))
        return artifacts

    def list_diagrams(self, api_key: str, generation_id: str) -> dict:
        generation = self.generation_repository.get_owned(generation_id, api_key)
        if generation is None:
            raise NotFoundError(f"Generation 不存在: {generation_id}")

        rows = self.diagram_repository.list_by_generation(generation_id)
        return {
            "generation_id": generation_id,
            "task_id": generation.get("diagram_task_id"),
            "diagrams": [
                {
                    "diagram_id": row["diagram_id"],
                    "status": row["status"],
                    "diagram_title": row.get("diagram_title"),
                    "section_title": row.get("section_title"),
                    "diagram_kind": row.get("diagram_kind"),
                    "diagram_description": row.get("diagram_description"),
                    "final_page_no": row.get("final_page_no"),
                }
                for row in rows
            ],
        }

    def _count_pages_and_diagrams(
        self,
        body_task: dict | None,
        diagram_task: dict | None,
        diagrams: list[dict],
    ) -> tuple[int, int, int]:
        kept = 0
        skipped = 0
        if body_task:
            for page in self.task_repository.list_pages(body_task["task_id"]):
                if page.get("should_generate"):
                    kept += 1
                elif page.get("status") == "skipped":
                    skipped += 1
        return kept, skipped, len(diagrams)

    def list(self, api_key: str, offset: int, limit: int) -> list[dict]:
        rows = self.generation_repository.list(api_key, offset, limit)
        return [
            {
                "generation_id": row["generation_id"],
                "generation_mode": row["generation_mode"],
                "status": row["status"],
                "requirement_text_chars": int(row.get("requirement_text_chars", 0)),
                "body_status": row["body_status"],
                "diagram_status": row["diagram_status"],
                "compose_status": row["compose_status"],
                "template_id": row.get("template_id"),
                "created_at": to_iso(row.get("created_at")),
                "completed_at": to_iso(row.get("completed_at")),
            }
            for row in rows
        ]

    def append_child_task(self, api_key: str, generation_id: str, task_type: str) -> dict:
        generation = self.generation_repository.get_owned(generation_id, api_key)
        if generation is None:
            raise NotFoundError(f"Generation 不存在: {generation_id}")

        existing_field = {"body": "body_task_id", "diagrams": "diagram_task_id"}[task_type]
        if generation.get(existing_field):
            raise ConflictError(f"该 Generation 已存在 {task_type} 任务")

        template = self.template_service.get_template(str(generation["template_id"]))
        generation_workspace = self.workspace.generation(generation_id)

        remote_root = self.ftp.join(self.ftp.settings.ftp_root_dir, "generations", generation_id)
        task_id = self._create_child_task(
            api_key=api_key,
            generation_id=generation_id,
            task_type=task_type,
            template=template,
            requirement_text=generation["requirement_text"],
            custom_requirements=generation.get("custom_requirements"),
            options=None,
            ftp_root=remote_root,
            generation_workspace=generation_workspace,
        )

        status = TASK_STATUS_PENDING
        if task_type == "body":
            self.generation_repository.update(
                generation_id,
                {"body_task_id": task_id, "body_status": status},
            )
        else:
            self.generation_repository.update(
                generation_id,
                {"diagram_task_id": task_id, "diagram_status": status},
            )

        self.task_runner.submit(task_id, lambda: self.orchestration_service.run_task(api_key, task_id))

        return self.get_summary(api_key, generation_id)

    def update_aggregation(self, generation_id: str) -> None:
        """由子任务执行结束后调用，刷新聚合状态并触发自动组装。"""
        generation = self.generation_repository.get(generation_id)
        if generation is None:
            return

        statuses = []
        for field, task_id in [
            ("body_status", generation.get("body_task_id")),
            ("diagram_status", generation.get("diagram_task_id")),
            ("compose_status", generation.get("compose_task_id")),
        ]:
            if task_id:
                task = self.task_repository.get_task(task_id)
                if task:
                    self.generation_repository.update(generation_id, {field: task["status"]})
                    if task["status"] not in {TASK_STATUS_PENDING, CHILD_STATUS_NOT_REQUESTED}:
                        statuses.append(task["status"])

        # 聚合状态判定
        if any(s == TASK_STATUS_RUNNING for s in statuses):
            overall = GENERATION_STATUS_RUNNING
        elif any(s == TASK_STATUS_FAILED for s in statuses) and not any(
            s in {TASK_STATUS_COMPLETED, GENERATION_STATUS_COMPLETED_WITH_WARNINGS} for s in statuses
        ):
            overall = GENERATION_STATUS_FAILED
        elif all(s == TASK_STATUS_COMPLETED for s in statuses):
            overall = GENERATION_STATUS_COMPLETED
        elif any(s in {GENERATION_STATUS_COMPLETED_WITH_WARNINGS, "completed_with_warnings"} for s in statuses):
            overall = GENERATION_STATUS_COMPLETED_WITH_WARNINGS
        else:
            overall = GENERATION_STATUS_PENDING

        fields: dict = {"status": overall}
        if overall in {GENERATION_STATUS_COMPLETED, GENERATION_STATUS_COMPLETED_WITH_WARNINGS, GENERATION_STATUS_FAILED}:
            fields["completed_at"] = datetime.now()
        self.generation_repository.update(generation_id, fields)

        # 自动组装逻辑：body 和 diagrams 都完成后触发
        if generation.get("auto_compose"):
            fresh = self.generation_repository.get(generation_id)
            body_status = fresh.get("body_status")
            diagram_status = fresh.get("diagram_status")
            if (
                body_status in {TASK_STATUS_COMPLETED, "completed_with_warnings"}
                and diagram_status in {TASK_STATUS_COMPLETED, "completed_with_warnings"}
                and not fresh.get("compose_task_id")
            ):
                template = self.template_service.get_template(str(fresh["template_id"]))
                generation_workspace = self.workspace.generation(generation_id)
                remote_root = self.ftp.join(self.ftp.settings.ftp_root_dir, "generations", generation_id)
                compose_task_id = self._create_child_task(
                    api_key=fresh["api_key"],
                    generation_id=generation_id,
                    task_type=TASK_TYPE_COMPOSE,
                    template=template,
                    requirement_text=fresh["requirement_text"],
                    custom_requirements=fresh.get("custom_requirements"),
                    options=None,
                    ftp_root=remote_root,
                    generation_workspace=generation_workspace,
                )
                self.generation_repository.update(
                    generation_id,
                    {"compose_task_id": compose_task_id, "compose_status": TASK_STATUS_PENDING},
                )
                self.task_runner.submit(
                    compose_task_id,
                    lambda: self.orchestration_service.run_task(fresh["api_key"], compose_task_id),
                )
