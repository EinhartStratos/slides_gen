from __future__ import annotations

from datetime import datetime
import json
import logging
import shutil

from app.core.constants import (
    ARTIFACT_TYPE_ANALYSIS_JSON,
    ARTIFACT_TYPE_REQUEST_JSON,
    ARTIFACT_TYPE_REQUIREMENT_MD,
    ARTIFACT_TYPE_RESULT_PPTX,
    ARTIFACT_TYPE_SVG_FINAL,
    ARTIFACT_TYPE_SVG_OUTPUT,
    ARTIFACT_TYPE_VALIDATION_REPORT,
    PAGE_STATUS_COMPLETED,
    PAGE_STATUS_FAILED,
    PAGE_STATUS_PENDING,
    PAGE_STATUS_RUNNING,
    PAGE_STATUS_SKIPPED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RESUMING,
    TASK_STATUS_RUNNING,
    TASK_STATUS_STOPPED,
)
from app.core.utils import json_dumps
from app.infrastructure.ppt_master.project_workspace import ProjectWorkspace
from app.infrastructure.storage.ftp import FtpStorage
from app.services.pptx_export_service import PptxExportService
from app.services.slide_generation_service import SlideGenerationService
from app.services.svg_validation_service import SvgValidationService
from app.services.task_service import TaskService
from app.services.template_service import TemplateService


logger = logging.getLogger(__name__)


class OrchestrationService:
    def __init__(
        self,
        workspace: ProjectWorkspace,
        ftp: FtpStorage,
        task_service: TaskService,
        template_service: TemplateService,
        slide_service: SlideGenerationService,
        svg_validation_service: SvgValidationService,
        pptx_export_service: PptxExportService,
    ) -> None:
        self.workspace = workspace
        self.ftp = ftp
        self.task_service = task_service
        self.template_service = template_service
        self.slide_service = slide_service
        self.svg_validation_service = svg_validation_service
        self.pptx_export_service = pptx_export_service

    async def run_task(self, api_key: str, task_id: str) -> None:
        task = self.task_service.get_task(api_key, task_id)
        task_workspace = self.workspace.task(task_id)
        self.workspace.ensure_task_dirs(task_workspace)

        start_status = TASK_STATUS_RESUMING if task["status"] == TASK_STATUS_RESUMING else TASK_STATUS_RUNNING
        self.task_service.touch_running(task_id, start_status, "preparing")

        try:
            template = self.template_service.get_template(str(task["template_id"]))
            source_svgs = self.template_service.copy_flat_svgs_to_task_snapshot(
                template,
                task_workspace.template_snapshot_svg_flat_dir,
                task_workspace.template_snapshot_assets_dir,
            )
            self.slide_service.mirror_assets(task_workspace.template_snapshot_assets_dir, task_workspace.assets_dir)
            self._sync_task_static_files(task, task_workspace)
            self._sync_template_snapshot_to_ftp(task, task_workspace)

            request_payload = {}
            raw_payload = task.get("request_payload_json")
            if raw_payload:
                try:
                    request_payload = json.loads(raw_payload)
                except Exception:
                    request_payload = {}
            options = request_payload.get("options") or {}
            llm_model = options.get("model")
            llm_enable_thinking = options.get("enable_thinking", False)

            existing_pages = {row["page_no"]: row for row in self.task_service.repository.list_pages(task_id)}
            total_pages = len(source_svgs)
            self.task_service.repository.update_task(task_id, {"total_pages": total_pages, "current_stage": "page_planning", "progress": 5})

            page_plans = self.slide_service.plan_pages(
                api_key, str(task["requirement_text"]), source_svgs,
                model=llm_model, enable_thinking=llm_enable_thinking,
            )
            plan_path = self.slide_service.write_plan(task_workspace, page_plans)
            ftp_plan_path = self.ftp.upload_file(
                plan_path,
                self.ftp.join(str(task["ftp_task_dir"]), "analysis", plan_path.name),
            )
            self.task_service.create_artifact(
                task_id,
                ARTIFACT_TYPE_ANALYSIS_JSON,
                ftp_plan_path,
                plan_path.name,
                file_size_bytes=plan_path.stat().st_size,
                content_type="application/json",
            )
            self.task_service.create_event(task_id, api_key, "planning_done", "page_planning", f"页面规划完成，共{total_pages}页")

            plan_map = {p["page_no"]: p for p in page_plans}

            self.task_service.repository.update_task(task_id, {"current_stage": "page_generation", "progress": 10})

            completed_pages = 0
            skipped_pages = 0
            failed_pages = 0
            processed_pages = 0

            for index, source_svg in enumerate(source_svgs, start=1):
                latest_task = self.task_service.get_task(api_key, task_id)
                if latest_task["stop_requested"]:
                    self.task_service.repository.update_task(
                        task_id,
                        {
                            "status": TASK_STATUS_STOPPED,
                            "current_stage": "stopped",
                            "stopped_at": datetime.now(),
                            "progress": float(latest_task["progress"]),
                        },
                    )
                    self.task_service.create_event(task_id, api_key, "stopped", "stopped", "任务已停止")
                    return

                page_row = existing_pages.get(index)
                if page_row and page_row["status"] == PAGE_STATUS_COMPLETED and page_row.get("ftp_final_svg_path"):
                    local_final_path = task_workspace.svg_final_dir / source_svg.name
                    if not local_final_path.exists():
                        self.ftp.download_file(str(page_row["ftp_final_svg_path"]), local_final_path)
                    completed_pages += 1
                    processed_pages += 1
                    progress = 10 + (processed_pages / max(total_pages, 1)) * 80
                    self.task_service.repository.update_task(
                        task_id,
                        {
                            "processed_pages": processed_pages,
                            "completed_pages": completed_pages,
                            "skipped_pages": skipped_pages,
                            "failed_pages": failed_pages,
                            "progress": round(progress, 2),
                            "last_heartbeat_at": datetime.now(),
                        },
                    )
                    continue

                page_name = source_svg.stem
                template_svg_ftp_path = self.ftp.join(
                    str(task["ftp_template_snapshot_dir"]),
                    "svg-flat",
                    source_svg.name,
                )
                self.task_service.repository.upsert_page(
                    {
                        "task_id": task_id,
                        "page_no": index,
                        "page_name": page_name,
                        "template_svg_ftp_path": template_svg_ftp_path,
                        "status": PAGE_STATUS_RUNNING,
                        "started_at": datetime.now(),
                    }
                )
                self.task_service.create_event(task_id, api_key, "page_started", "page_generation", f"开始处理第 {index} 页", page_no=index)

                page_plan = plan_map.get(index, {})
                if not page_plan.get("should_generate", True):
                    skipped_pages += 1
                    processed_pages += 1
                    plan_result_path = self.slide_service.write_page_result(task_workspace, index, page_plan)
                    ftp_plan_result_path = self.ftp.upload_file(
                        plan_result_path,
                        self.ftp.join(str(task["ftp_task_dir"]), "analysis", plan_result_path.name),
                    )
                    self.task_service.create_artifact(
                        task_id,
                        ARTIFACT_TYPE_ANALYSIS_JSON,
                        ftp_plan_result_path,
                        plan_result_path.name,
                        page_no=index,
                        file_size_bytes=plan_result_path.stat().st_size,
                        content_type="application/json",
                    )
                    self.task_service.repository.upsert_page(
                        {
                            "task_id": task_id,
                            "page_no": index,
                            "page_name": page_name,
                            "template_svg_ftp_path": template_svg_ftp_path,
                            "analysis_json_ftp_path": ftp_plan_result_path,
                            "status": PAGE_STATUS_SKIPPED,
                            "should_generate": 0,
                            "skip_reason": page_plan.get("skip_reason", ""),
                            "completed_at": datetime.now(),
                        }
                    )
                    self.task_service.create_event(task_id, api_key, "page_skipped", "page_generation", f"第 {index} 页跳过: {page_plan.get('skip_reason', '')}", page_no=index)
                    progress = 10 + (processed_pages / max(total_pages, 1)) * 80
                    self.task_service.repository.update_task(
                        task_id,
                        {
                            "processed_pages": processed_pages,
                            "completed_pages": completed_pages,
                            "skipped_pages": skipped_pages,
                            "failed_pages": failed_pages,
                            "progress": round(progress, 2),
                            "last_heartbeat_at": datetime.now(),
                        },
                    )
                    continue

                try:
                    page_result = self.slide_service.generate_page_svg(
                        api_key, str(task["requirement_text"]), index, source_svg, page_plan,
                        model=llm_model, enable_thinking=llm_enable_thinking,
                    )

                    if page_result.get("decision_source") == "failed":
                        failed_pages += 1
                        processed_pages += 1
                        result_path = self.slide_service.write_page_result(task_workspace, index, page_result)
                        ftp_analysis_path = self.ftp.upload_file(
                            result_path,
                            self.ftp.join(str(task["ftp_task_dir"]), "analysis", result_path.name),
                        )
                        self.task_service.create_artifact(
                            task_id,
                            ARTIFACT_TYPE_ANALYSIS_JSON,
                            ftp_analysis_path,
                            result_path.name,
                            page_no=index,
                            file_size_bytes=result_path.stat().st_size,
                            content_type="application/json",
                        )
                        self.task_service.repository.upsert_page(
                            {
                                "task_id": task_id,
                                "page_no": index,
                                "page_name": page_name,
                                "template_svg_ftp_path": template_svg_ftp_path,
                                "analysis_json_ftp_path": ftp_analysis_path,
                                "status": PAGE_STATUS_FAILED,
                                "should_generate": 1,
                                "error_message": "LLM 生成失败，重试3次仍不成功",
                                "completed_at": datetime.now(),
                            }
                        )
                        self.task_service.create_event(task_id, api_key, "page_failed", "page_generation", f"第 {index} 页 LLM 生成失败，跳过不输出", page_no=index)
                        progress = 10 + (processed_pages / max(total_pages, 1)) * 80
                        self.task_service.repository.update_task(
                            task_id,
                            {
                                "processed_pages": processed_pages,
                                "completed_pages": completed_pages,
                                "skipped_pages": skipped_pages,
                                "failed_pages": failed_pages,
                                "progress": round(progress, 2),
                                "last_heartbeat_at": datetime.now(),
                            },
                        )
                        continue

                    result_path = self.slide_service.write_page_result(task_workspace, index, page_result)
                    ftp_analysis_path = self.ftp.upload_file(
                        result_path,
                        self.ftp.join(str(task["ftp_task_dir"]), "analysis", result_path.name),
                    )
                    self.task_service.create_artifact(
                        task_id,
                        ARTIFACT_TYPE_ANALYSIS_JSON,
                        ftp_analysis_path,
                        result_path.name,
                        page_no=index,
                        file_size_bytes=result_path.stat().st_size,
                        content_type="application/json",
                    )

                    output_svg_path = task_workspace.svg_output_dir / source_svg.name
                    final_svg_path = task_workspace.svg_final_dir / source_svg.name
                    generated_svg_path, final_svg_path = self.slide_service.render_page(source_svg, output_svg_path, final_svg_path, page_result)
                    validation_status, validation_message = self.svg_validation_service.validate(final_svg_path)

                    ftp_generated_svg_path = self.ftp.upload_file(
                        generated_svg_path,
                        self.ftp.join(str(task["ftp_task_dir"]), "svg_output", generated_svg_path.name),
                    )
                    ftp_final_svg_path = self.ftp.upload_file(
                        final_svg_path,
                        self.ftp.join(str(task["ftp_task_dir"]), "svg_final", final_svg_path.name),
                    )
                    self.task_service.create_artifact(
                        task_id,
                        ARTIFACT_TYPE_SVG_OUTPUT,
                        ftp_generated_svg_path,
                        generated_svg_path.name,
                        page_no=index,
                        file_size_bytes=generated_svg_path.stat().st_size,
                        content_type="image/svg+xml",
                    )
                    self.task_service.create_artifact(
                        task_id,
                        ARTIFACT_TYPE_SVG_FINAL,
                        ftp_final_svg_path,
                        final_svg_path.name,
                        page_no=index,
                        is_final=True,
                        file_size_bytes=final_svg_path.stat().st_size,
                        content_type="image/svg+xml",
                    )
                    self.task_service.repository.upsert_page(
                        {
                            "task_id": task_id,
                            "page_no": index,
                            "page_name": page_name,
                            "template_svg_ftp_path": template_svg_ftp_path,
                            "analysis_json_ftp_path": ftp_analysis_path,
                            "status": PAGE_STATUS_COMPLETED if validation_status == "passed" else PAGE_STATUS_FAILED,
                            "should_generate": 1,
                            "ftp_generated_svg_path": ftp_generated_svg_path,
                            "ftp_final_svg_path": ftp_final_svg_path,
                            "validation_status": validation_status,
                            "validation_message": validation_message,
                            "error_message": None if validation_status == "passed" else validation_message,
                            "completed_at": datetime.now(),
                        }
                    )
                    if validation_status == "passed":
                        completed_pages += 1
                        self.task_service.create_event(task_id, api_key, "page_completed", "page_generation", f"第 {index} 页已完成", page_no=index)
                    else:
                        failed_pages += 1
                        self.task_service.create_event(task_id, api_key, "page_failed", "page_generation", f"第 {index} 页校验失败", page_no=index)
                    processed_pages += 1
                except Exception as exc:
                    failed_pages += 1
                    processed_pages += 1
                    self.task_service.repository.upsert_page(
                        {
                            "task_id": task_id,
                            "page_no": index,
                            "page_name": page_name,
                            "template_svg_ftp_path": template_svg_ftp_path,
                            "status": PAGE_STATUS_FAILED,
                            "error_message": str(exc),
                            "completed_at": datetime.now(),
                        }
                    )
                    self.task_service.create_event(task_id, api_key, "page_failed", "page_generation", f"第 {index} 页失败: {exc}", page_no=index)

                progress = 10 + (processed_pages / max(total_pages, 1)) * 80
                self.task_service.repository.update_task(
                    task_id,
                    {
                        "processed_pages": processed_pages,
                        "completed_pages": completed_pages,
                        "skipped_pages": skipped_pages,
                        "failed_pages": failed_pages,
                        "progress": round(progress, 2),
                        "last_heartbeat_at": datetime.now(),
                    },
                )

            validation_report = {
                "task_id": task_id,
                "total_pages": total_pages,
                "completed_pages": completed_pages,
                "skipped_pages": skipped_pages,
                "failed_pages": failed_pages,
            }
            validation_report_path = task_workspace.validation_dir / "validation_report.json"
            validation_report_path.write_text(json.dumps(validation_report, ensure_ascii=False, indent=2), encoding="utf-8")
            ftp_validation_report_path = self.ftp.upload_file(
                validation_report_path,
                str(task["ftp_validation_report_path"]),
            )
            self.task_service.create_artifact(
                task_id,
                ARTIFACT_TYPE_VALIDATION_REPORT,
                ftp_validation_report_path,
                validation_report_path.name,
                is_final=True,
                file_size_bytes=validation_report_path.stat().st_size,
                content_type="application/json",
            )

            if failed_pages > 0 and completed_pages == 0:
                self.task_service.repository.update_task(
                    task_id,
                    {
                        "status": TASK_STATUS_FAILED,
                        "current_stage": "failed",
                        "progress": 100,
                        "error_message": "所有页面处理失败，未生成最终 PPTX",
                        "completed_at": datetime.now(),
                    },
                )
                self.task_service.create_event(task_id, api_key, "failed", "failed", "任务失败，未生成任何可导出页面")
                return

            self.task_service.repository.update_task(task_id, {"current_stage": "exporting", "progress": 90})
            result_pptx_path = self.pptx_export_service.export(task_workspace.svg_final_dir, task_workspace.result_pptx_path)
            ftp_result_pptx_path = self.ftp.upload_file(result_pptx_path, str(task["ftp_result_pptx_path"]))
            self.task_service.create_artifact(
                task_id,
                ARTIFACT_TYPE_RESULT_PPTX,
                ftp_result_pptx_path,
                result_pptx_path.name,
                is_final=True,
                file_size_bytes=result_pptx_path.stat().st_size,
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
            self.task_service.repository.update_task(
                task_id,
                {
                    "status": TASK_STATUS_COMPLETED,
                    "current_stage": "completed",
                    "progress": 100,
                    "ftp_validation_report_path": ftp_validation_report_path,
                    "ftp_result_pptx_path": ftp_result_pptx_path,
                    "processed_pages": processed_pages,
                    "completed_pages": completed_pages,
                    "skipped_pages": skipped_pages,
                    "failed_pages": failed_pages,
                    "completed_at": datetime.now(),
                    "error_message": None,
                    "error_code": None,
                },
            )
            self.task_service.create_event(task_id, api_key, "exported", "completed", "最终 PPTX 已导出")
        except Exception as exc:
            self.task_service.repository.update_task(
                task_id,
                {
                    "status": TASK_STATUS_FAILED,
                    "current_stage": "failed",
                    "error_message": str(exc),
                    "completed_at": datetime.now(),
                },
            )
            self.task_service.create_event(task_id, api_key, "failed", "failed", f"任务执行失败: {exc}")
        finally:
            try:
                if task_workspace.root.exists():
                    shutil.rmtree(task_workspace.root, ignore_errors=True)
                    logger.info("已清理 runtime 任务目录: %s", task_workspace.root)
            except Exception:
                pass

    def _sync_task_static_files(self, task: dict, workspace) -> None:
        request_ftp = self.ftp.upload_file(workspace.request_json_path, str(task["ftp_request_path"]))
        requirement_ftp = self.ftp.upload_file(workspace.requirement_path, str(task["ftp_requirement_path"]))
        self.task_service.create_artifact(
            task["task_id"],
            ARTIFACT_TYPE_REQUEST_JSON,
            request_ftp,
            workspace.request_json_path.name,
            file_size_bytes=workspace.request_json_path.stat().st_size,
            content_type="application/json",
        )
        self.task_service.create_artifact(
            task["task_id"],
            ARTIFACT_TYPE_REQUIREMENT_MD,
            requirement_ftp,
            workspace.requirement_path.name,
            file_size_bytes=workspace.requirement_path.stat().st_size,
            content_type="text/markdown",
        )

    def _sync_template_snapshot_to_ftp(self, task: dict, workspace) -> None:
        base_remote = self.ftp.join(str(task["ftp_task_dir"]), "template_snapshot")
        for path in sorted(workspace.template_snapshot_svg_flat_dir.rglob("*.svg")):
            relative = path.relative_to(workspace.template_snapshot_svg_flat_dir).as_posix()
            self.ftp.upload_file(path, self.ftp.join(base_remote, "svg-flat", relative))
        for path in sorted(workspace.template_snapshot_assets_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(workspace.template_snapshot_assets_dir).as_posix()
            self.ftp.upload_file(path, self.ftp.join(base_remote, "assets", relative))
