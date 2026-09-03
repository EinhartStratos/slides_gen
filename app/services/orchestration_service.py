from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import logging
import shutil
import threading
from typing import Any

from app.core.constants import (
    ARTIFACT_TYPE_ANALYSIS_JSON,
    ARTIFACT_TYPE_BODY_PPTX,
    ARTIFACT_TYPE_COMPOSED_PPTX,
    ARTIFACT_TYPE_DIAGRAM_SVG,
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
    TASK_TYPE_BODY,
    TASK_TYPE_COMPOSE,
    TASK_TYPE_DIAGRAMS,
)
from app.core.utils import generate_id, json_dumps
from app.core.config import Settings
from app.infrastructure.llm.rule_matcher import PageGenerationRuleMatcher, RuleMatcher
from app.infrastructure.db.diagram_repository import DiagramRepository
from app.infrastructure.ppt_master.project_workspace import ProjectWorkspace
from app.infrastructure.storage.ftp import FtpStorage
from app.services.hybrid_pptx_exporter import HybridPptxExporter
from app.services.pptx_builder_service import PptxBuilderService
from app.services.pptx_export_service import PptxExportService
from app.services.slide_generation_service import SlideGenerationService
from app.schemas.structured_generation import StructuredPageResult
from app.services.svg_validation_service import SvgValidationService
from app.services.task_service import TaskService
from app.services.template_service import TemplateService
from app.services.requirement_preprocessor import RequirementPreprocessor
from app.schemas.structured_generation import StructuredPageResult


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
        diagram_repository: DiagramRepository | None = None,
        pptx_builder_service: PptxBuilderService | None = None,
        hybrid_exporter: HybridPptxExporter | None = None,
        rule_matcher: RuleMatcher | None = None,
        page_rule_matcher: PageGenerationRuleMatcher | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.workspace = workspace
        self.ftp = ftp
        self.task_service = task_service
        self.template_service = template_service
        self.slide_service = slide_service
        self.svg_validation_service = svg_validation_service
        self.pptx_export_service = pptx_export_service
        self.diagram_repository = diagram_repository
        self.pptx_builder_service = pptx_builder_service
        self.hybrid_exporter = hybrid_exporter
        self.rule_matcher = rule_matcher
        self.page_rule_matcher = page_rule_matcher
        self.settings = settings
        self._generation_service: Any | None = None

    def set_generation_service(self, generation_service: Any) -> None:
        self._generation_service = generation_service

    def _notify_generation(self, generation_id: str | None, task_id: str) -> None:
        if not generation_id or not self._generation_service:
            return
        try:
            self._generation_service.update_aggregation(generation_id)
        except Exception as exc:
            logger.warning("通知 Generation 聚合状态失败: %s", exc)

    async def _preprocess_requirement(self, api_key: str, raw_text: str) -> str:
        """对 requirement_text 做结构化预处理，失败则返回原文。"""
        try:
            client = getattr(self.slide_service, "generation_client", None)
            if not client or not client.enabled or not api_key:
                return raw_text
            preprocessor = RequirementPreprocessor(
                llm_client=client,
                api_key=api_key,
                max_input_chars=40000,
                max_concurrency=2,
            )
            processed = await preprocessor.preprocess(raw_text)
            return processed.formatted_text
        except Exception as exc:
            logger.warning("requirement 预处理失败，使用原文: %s", exc)
            return raw_text

    async def run_task(self, api_key: str, task_id: str) -> None:
        task = self.task_service.get_task(api_key, task_id)
        raw_text = str(task.get("requirement_text") or "")
        if raw_text.strip():
            task["requirement_text"] = await self._preprocess_requirement(api_key, raw_text)
        task_type = task.get("task_type") or "legacy"

        if task_type == TASK_TYPE_BODY:
            await self._run_body_task(api_key, task_id, task)
            return
        if task_type == TASK_TYPE_DIAGRAMS:
            await self._run_diagrams_task(api_key, task_id, task)
            return
        if task_type == TASK_TYPE_COMPOSE:
            await self._run_compose_task(api_key, task_id, task)
            return

        await self._run_legacy_task(api_key, task_id, task)

    def _should_force_page_as_diagram(self, custom_requirements: str, page_plan: dict) -> bool:
        """当用户自定义要求明确包含画图意图，且当前为可生成内容页时，允许强制作为图形页处理。"""
        if not custom_requirements or not custom_requirements.strip():
            return False
        keywords = ["图", "连接", "架构", "流程", "时序", "关系", "连线", "箭头", "拓扑"]
        has_diagram_intent = any(kw in custom_requirements for kw in keywords)
        page_type = page_plan.get("page_type", "content")
        return has_diagram_intent and page_type in ("content", "diagram") and page_plan.get("page_no", 0) > 1

    async def _run_legacy_task(self, api_key: str, task_id: str, task: dict) -> None:
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
            custom_requirements = request_payload.get("custom_requirements") or ""

            task_type = task.get("task_type") or "legacy"
            force_structured = task_type == TASK_TYPE_BODY
            result_artifact_type = ARTIFACT_TYPE_BODY_PPTX if task_type == TASK_TYPE_BODY else ARTIFACT_TYPE_RESULT_PPTX
            result_pptx_name = "body.pptx" if task_type == TASK_TYPE_BODY else "generated.pptx"
            svg_page_types = set()
            if not force_structured and self.settings is not None:
                svg_page_types = {t.strip() for t in self.settings.svg_page_types.split(",") if t.strip()}

            existing_pages = {row["page_no"]: row for row in self.task_service.repository.list_pages(task_id)}
            total_pages = len(source_svgs)
            self.task_service.repository.update_task(task_id, {"total_pages": total_pages, "current_stage": "page_planning", "progress": 5})

            lock = threading.Lock()
            counters = {"processed": 0, "completed": 0, "skipped": 0, "failed": 0}
            all_plans: dict[int, dict] = {}

            # 解析模板规则（用于结构化填充）
            template_rules: dict | None = None
            if self.pptx_builder_service is not None:
                try:
                    template_pptx_path = self.template_service.get_template_pptx_path(template)
                    template_rules = self.pptx_builder_service.parse_template_rules(
                        template_pptx_path,
                        task_workspace.analysis_dir / "template_rules.json",
                    )
                    logger.info("模板规则解析完成，共 %d 页", len(template_rules.get("pages", [])))
                except Exception as exc:
                    logger.warning("模板规则解析失败，所有页面将走 SVG 路径: %s", exc)

            # 收集各页的结果（用于混合导出）
            svg_pages: dict[int, Path] = {}
            structured_pages: dict[int, StructuredPageResult] = {}
            skipped_pages: set[int] = set()

            self.task_service.repository.update_task(task_id, {"current_stage": "page_generation", "progress": 10})

            with ThreadPoolExecutor(max_workers=max(total_pages, 1), thread_name_prefix=f"task-{task_id}") as executor:
                futures = {}
                for index, source_svg in enumerate(source_svgs, start=1):
                    page_rule = None
                    if template_rules is not None:
                        pages_list = template_rules.get("pages", [])
                        if index <= len(pages_list):
                            page_rule = pages_list[index - 1]
                    future = executor.submit(
                        self._process_one_page,
                        api_key=api_key,
                        task_id=task_id,
                        requirement_text=str(task["requirement_text"]),
                        page_no=index,
                        source_svg=source_svg,
                        existing_pages=existing_pages,
                        total_pages=total_pages,
                        llm_model=llm_model,
                        llm_enable_thinking=llm_enable_thinking,
                        task_workspace=task_workspace,
                        task=task,
                        counters=counters,
                        lock=lock,
                        all_plans=all_plans,
                        template_rules=template_rules,
                        page_rule=page_rule,
                        svg_pages=svg_pages,
                        structured_pages=structured_pages,
                        skipped_pages=skipped_pages,
                        custom_requirements=custom_requirements,
                        force_structured=force_structured,
                        svg_page_types=svg_page_types,
                    )
                    futures[index] = future

                for future in as_completed(futures.values()):
                    try:
                        future.result()
                    except Exception as exc:
                        logger.error("页面处理异常: %s", exc)

            plan_list = [all_plans[i] for i in sorted(all_plans.keys())]
            if plan_list:
                plan_path = self.slide_service.write_plan(task_workspace, plan_list)
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

            with lock:
                completed_pages = counters["completed"]
                skipped_count = counters["skipped"]
                failed_pages = counters["failed"]
                processed_pages = counters["processed"]

            validation_report = {
                "task_id": task_id,
                "total_pages": total_pages,
                "completed_pages": completed_pages,
                "skipped_pages": skipped_count,
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
            logger.info("开始导出阶段: structured_pages=%s, skipped_pages=%s, svg_pages=%s",
                        len(structured_pages), len(skipped_pages), len(svg_pages))

            # 混合导出：如果有结构化页面，使用 HybridPptxExporter；否则回退到纯 SVG 导出
            output_pptx_path = task_workspace.exports_dir / result_pptx_name
            if self.hybrid_exporter is not None and template_rules is not None and (structured_pages or skipped_pages):
                logger.info("使用混合导出器, template_pptx=%s", template)
                template_pptx_path = self.template_service.get_template_pptx_path(template)
                result_pptx_path = self.hybrid_exporter.export(
                    template_pptx_path=template_pptx_path,
                    template_rules=template_rules,
                    svg_pages=svg_pages,
                    structured_pages=structured_pages,
                    skipped_pages=skipped_pages,
                    output_path=output_pptx_path,
                )
            else:
                logger.info("使用纯 SVG 导出器")
                result_pptx_path = self.pptx_export_service.export(task_workspace.svg_final_dir, output_pptx_path)
            logger.info("PPTX 导出完成: %s", result_pptx_path)
            ftp_result_pptx_path_remote = self.ftp.join(str(task["ftp_task_dir"]), "exports", result_pptx_name)
            ftp_result_pptx_path = self.ftp.upload_file(result_pptx_path, ftp_result_pptx_path_remote)
            self.task_service.create_artifact(
                task_id,
                result_artifact_type,
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
                    "skipped_pages": skipped_count,
                    "failed_pages": failed_pages,
                    "completed_at": datetime.now(),
                    "error_message": None,
                    "error_code": None,
                },
            )
            self.task_service.create_event(task_id, api_key, "exported", "completed", "最终 PPTX 已导出")
        except Exception as exc:
            logger.error("任务执行失败: %s", exc, exc_info=True)
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
            self._notify_generation(task.get("generation_id"), task_id)

    def _process_one_page(
        self,
        api_key: str,
        task_id: str,
        requirement_text: str,
        page_no: int,
        source_svg,
        existing_pages: dict,
        total_pages: int,
        llm_model: str | None,
        llm_enable_thinking: bool,
        task_workspace,
        task: dict,
        counters: dict,
        lock: threading.Lock,
        all_plans: dict,
        template_rules: dict | None = None,
        page_rule: dict | None = None,
        svg_pages: dict | None = None,
        structured_pages: dict | None = None,
        skipped_pages: set | None = None,
        custom_requirements: str = "",
        force_structured: bool = False,
        svg_page_types: set | None = None,
    ) -> None:
        """单页完整处理：规划 → 生成（SVG 或结构化）→ 渲染 → 校验 → 上传。线程安全。"""

        latest_task = self.task_service.get_task(api_key, task_id)
        if latest_task["stop_requested"]:
            return

        page_row = existing_pages.get(page_no)
        if page_row and page_row["status"] == PAGE_STATUS_COMPLETED and page_row.get("ftp_final_svg_path"):
            local_final_path = task_workspace.svg_final_dir / source_svg.name
            if not local_final_path.exists():
                self.ftp.download_file(str(page_row["ftp_final_svg_path"]), local_final_path)
            with lock:
                counters["processed"] += 1
                counters["completed"] += 1
                self._update_progress(task_id, counters, total_pages)
            return

        page_name = source_svg.stem
        template_svg_ftp_path = self.ftp.join(
            str(task["ftp_template_snapshot_dir"]),
            "svg-flat",
            source_svg.name,
        )
        self.task_service.repository.upsert_page(
            {
                "task_id": task_id,
                "page_no": page_no,
                "page_name": page_name,
                "template_svg_ftp_path": template_svg_ftp_path,
                "status": PAGE_STATUS_RUNNING,
                "started_at": datetime.now(),
            }
        )
        self.task_service.create_event(task_id, api_key, "page_started", "page_generation", f"开始处理第 {page_no} 页", page_no=page_no)

        svg_content = source_svg.read_text(encoding="utf-8", errors="ignore")

        # 匹配该页面的检查规则
        check_rules_text = ""
        if self.rule_matcher is not None and page_rule is not None:
            page_purpose = page_rule.get("page_purpose", "text")
            element_text = " ".join(
                (e.get("content_requirement") or "") + " " + (e.get("default_text") or "")
                for e in page_rule.get("elements", [])
            )
            matched_rules = self.rule_matcher.match(
                page_name=page_rule.get("page_name", page_name),
                page_purpose=page_purpose,
                element_text=element_text,
            )
            check_rules_text = self.rule_matcher.format_rules_for_prompt(matched_rules)
            if matched_rules:
                logger.info("第 %s 页匹配到 %d 条检查规则", page_no, len(matched_rules))

        # 匹配该页面的全局页面生成规范
        planning_rules_text = ""
        body_rules_text = ""
        if self.page_rule_matcher is not None:
            rule_page_name = page_rule.get("page_name", page_name) if page_rule else page_name
            planning_rules = self.page_rule_matcher.match(
                page_name=rule_page_name,
                apply_to="planning",
                svg_content=svg_content,
            )
            body_rules = self.page_rule_matcher.match(
                page_name=rule_page_name,
                apply_to="body",
                svg_content=svg_content,
            )
            planning_rules_text = self.page_rule_matcher.format_rules_for_prompt(planning_rules)
            body_rules_text = self.page_rule_matcher.format_rules_for_prompt(body_rules)
            if planning_rules or body_rules:
                logger.info("第 %s 页匹配到 %d 条页面生成规范（planning=%d, body=%d）", page_no, len(planning_rules) + len(body_rules), len(planning_rules), len(body_rules))

        page_plan = self.slide_service.plan_single_page(
            api_key=api_key,
            requirement_text=requirement_text,
            page_no=page_no,
            page_name=page_name,
            svg_content=svg_content,
            total_pages=total_pages,
            model=llm_model,
            enable_thinking=llm_enable_thinking,
            check_rules_text=check_rules_text,
            page_generation_rules_text=planning_rules_text,
            custom_requirements=custom_requirements,
        )
        with lock:
            all_plans[page_no] = page_plan

        if not page_plan.get("should_generate", True):
            with lock:
                counters["processed"] += 1
                counters["skipped"] += 1
            plan_result_path = self.slide_service.write_page_result(task_workspace, page_no, page_plan)
            ftp_plan_result_path = self.ftp.upload_file(
                plan_result_path,
                self.ftp.join(str(task["ftp_task_dir"]), "analysis", plan_result_path.name),
            )
            self.task_service.create_artifact(
                task_id,
                ARTIFACT_TYPE_ANALYSIS_JSON,
                ftp_plan_result_path,
                plan_result_path.name,
                page_no=page_no,
                file_size_bytes=plan_result_path.stat().st_size,
                content_type="application/json",
            )
            self.task_service.repository.upsert_page(
                {
                    "task_id": task_id,
                    "page_no": page_no,
                    "page_name": page_name,
                    "template_svg_ftp_path": template_svg_ftp_path,
                    "analysis_json_ftp_path": ftp_plan_result_path,
                    "status": PAGE_STATUS_SKIPPED,
                    "should_generate": 0,
                    "skip_reason": page_plan.get("skip_reason", ""),
                    "completed_at": datetime.now(),
                }
            )
            self.task_service.create_event(task_id, api_key, "page_skipped", "page_generation", f"第 {page_no} 页跳过: {page_plan.get('skip_reason', '')}", page_no=page_no)
            with lock:
                if skipped_pages is not None:
                    skipped_pages.add(page_no)
                self._update_progress(task_id, counters, total_pages)
            return

        # 判断生成方式：根据 page_type 决定走 SVG 还是结构化填充
        page_type = page_plan.get("page_type", "content")
        if svg_page_types is None:
            svg_page_types = set()
            if self.settings is not None:
                svg_page_types = {t.strip() for t in self.settings.svg_page_types.split(",") if t.strip()}
        use_svg = not force_structured and (page_type in svg_page_types or template_rules is None or page_rule is None or self.pptx_builder_service is None)

        if not use_svg:
            # 结构化填充路径
            self._process_structured_page(
                api_key=api_key,
                task_id=task_id,
                requirement_text=requirement_text,
                page_no=page_no,
                page_name=page_name,
                page_rule=page_rule,
                llm_model=llm_model,
                llm_enable_thinking=llm_enable_thinking,
                task_workspace=task_workspace,
                task=task,
                template_svg_ftp_path=template_svg_ftp_path,
                counters=counters,
                lock=lock,
                total_pages=total_pages,
                structured_pages=structured_pages,
                skipped_pages=skipped_pages,
                check_rules_text=check_rules_text,
                page_generation_rules_text=body_rules_text,
                custom_requirements=custom_requirements,
            )
            return

        try:
            page_result = self.slide_service.generate_page_svg(
                api_key, requirement_text, page_no, source_svg, page_plan,
                model=llm_model, enable_thinking=llm_enable_thinking,
                check_rules_text=check_rules_text,
                page_generation_rules_text=body_rules_text,
                custom_requirements=custom_requirements,
            )

            if page_result.get("decision_source") == "failed":
                with lock:
                    counters["processed"] += 1
                    counters["failed"] += 1
                result_path = self.slide_service.write_page_result(task_workspace, page_no, page_result)
                ftp_analysis_path = self.ftp.upload_file(
                    result_path,
                    self.ftp.join(str(task["ftp_task_dir"]), "analysis", result_path.name),
                )
                self.task_service.create_artifact(
                    task_id,
                    ARTIFACT_TYPE_ANALYSIS_JSON,
                    ftp_analysis_path,
                    result_path.name,
                    page_no=page_no,
                    file_size_bytes=result_path.stat().st_size,
                    content_type="application/json",
                )
                self.task_service.repository.upsert_page(
                    {
                        "task_id": task_id,
                        "page_no": page_no,
                        "page_name": page_name,
                        "template_svg_ftp_path": template_svg_ftp_path,
                        "analysis_json_ftp_path": ftp_analysis_path,
                        "status": PAGE_STATUS_FAILED,
                        "should_generate": 1,
                        "error_message": "LLM 生成失败，重试3次仍不成功",
                        "completed_at": datetime.now(),
                    }
                )
                self.task_service.create_event(task_id, api_key, "page_failed", "page_generation", f"第 {page_no} 页 LLM 生成失败，跳过不输出", page_no=page_no)
                with lock:
                    self._update_progress(task_id, counters, total_pages)
                return

            result_path = self.slide_service.write_page_result(task_workspace, page_no, page_result)
            ftp_analysis_path = self.ftp.upload_file(
                result_path,
                self.ftp.join(str(task["ftp_task_dir"]), "analysis", result_path.name),
            )
            self.task_service.create_artifact(
                task_id,
                ARTIFACT_TYPE_ANALYSIS_JSON,
                ftp_analysis_path,
                result_path.name,
                page_no=page_no,
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
                page_no=page_no,
                file_size_bytes=generated_svg_path.stat().st_size,
                content_type="image/svg+xml",
            )
            self.task_service.create_artifact(
                task_id,
                ARTIFACT_TYPE_SVG_FINAL,
                ftp_final_svg_path,
                final_svg_path.name,
                page_no=page_no,
                is_final=True,
                file_size_bytes=final_svg_path.stat().st_size,
                content_type="image/svg+xml",
            )
            self.task_service.repository.upsert_page(
                {
                    "task_id": task_id,
                    "page_no": page_no,
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
            with lock:
                counters["processed"] += 1
                if validation_status == "passed":
                    counters["completed"] += 1
                    if svg_pages is not None:
                        svg_pages[page_no] = final_svg_path
                    self.task_service.create_event(task_id, api_key, "page_completed", "page_generation", f"第 {page_no} 页已完成", page_no=page_no)
                else:
                    counters["failed"] += 1
                    self.task_service.create_event(task_id, api_key, "page_failed", "page_generation", f"第 {page_no} 页校验失败", page_no=page_no)
                self._update_progress(task_id, counters, total_pages)
        except Exception as exc:
            with lock:
                counters["processed"] += 1
                counters["failed"] += 1
            self.task_service.repository.upsert_page(
                {
                    "task_id": task_id,
                    "page_no": page_no,
                    "page_name": page_name,
                    "template_svg_ftp_path": template_svg_ftp_path,
                    "status": PAGE_STATUS_FAILED,
                    "error_message": str(exc),
                    "completed_at": datetime.now(),
                }
            )
            self.task_service.create_event(task_id, api_key, "page_failed", "page_generation", f"第 {page_no} 页失败: {exc}", page_no=page_no)
            with lock:
                self._update_progress(task_id, counters, total_pages)

    def _process_structured_page(
        self,
        api_key: str,
        task_id: str,
        requirement_text: str,
        page_no: int,
        page_name: str,
        page_rule: dict,
        llm_model: str | None,
        llm_enable_thinking: bool,
        task_workspace,
        task: dict,
        template_svg_ftp_path: str,
        counters: dict,
        lock: threading.Lock,
        total_pages: int = 1,
        structured_pages: dict | None = None,
        skipped_pages: set | None = None,
        check_rules_text: str = "",
        page_generation_rules_text: str = "",
        custom_requirements: str = "",
    ) -> None:
        """结构化填充路径：LLM 输出 JSON → 保存结果 → 记录到 structured_pages。"""
        try:
            result = self.pptx_builder_service.generate_page_content(
                api_key=api_key,
                requirement_text=requirement_text,
                page_no=page_no,
                page_name=page_name,
                page_rule=page_rule,
                model=llm_model,
                enable_thinking=llm_enable_thinking,
                check_rules_text=check_rules_text,
                page_generation_rules_text=page_generation_rules_text,
                custom_requirements=custom_requirements,
            )

            if not result.should_generate:
                with lock:
                    counters["processed"] += 1
                    counters["skipped"] += 1
                    if skipped_pages is not None:
                        skipped_pages.add(page_no)
                result_path = self.pptx_builder_service.save_page_result(task_workspace, page_no, result)
                ftp_result_path = self.ftp.upload_file(
                    result_path,
                    self.ftp.join(str(task["ftp_task_dir"]), "structured_results", result_path.name),
                )
                self.task_service.repository.upsert_page(
                    {
                        "task_id": task_id,
                        "page_no": page_no,
                        "page_name": page_name,
                        "template_svg_ftp_path": template_svg_ftp_path,
                        "status": PAGE_STATUS_SKIPPED,
                        "should_generate": 0,
                        "skip_reason": result.skip_reason,
                        "completed_at": datetime.now(),
                    }
                )
                self.task_service.create_event(task_id, api_key, "page_skipped", "page_generation", f"第 {page_no} 页跳过: {result.skip_reason}", page_no=page_no)
                with lock:
                    self._update_progress(task_id, counters, total_pages)
                return

            result_path = self.pptx_builder_service.save_page_result(task_workspace, page_no, result)
            ftp_result_path = self.ftp.upload_file(
                result_path,
                self.ftp.join(str(task["ftp_task_dir"]), "structured_results", result_path.name),
            )
            self.task_service.create_artifact(
                task_id,
                "structured_result",
                ftp_result_path,
                result_path.name,
                page_no=page_no,
                file_size_bytes=result_path.stat().st_size,
                content_type="application/json",
            )
            self.task_service.repository.upsert_page(
                {
                    "task_id": task_id,
                    "page_no": page_no,
                    "page_name": page_name,
                    "template_svg_ftp_path": template_svg_ftp_path,
                    "status": PAGE_STATUS_COMPLETED,
                    "should_generate": 1,
                    "completed_at": datetime.now(),
                }
            )
            with lock:
                counters["processed"] += 1
                counters["completed"] += 1
                if structured_pages is not None:
                    structured_pages[page_no] = result
            self.task_service.create_event(task_id, api_key, "page_completed", "page_generation", f"第 {page_no} 页结构化生成完成", page_no=page_no)
            with lock:
                self._update_progress(task_id, counters, total_pages)
        except Exception as exc:
            with lock:
                counters["processed"] += 1
                counters["failed"] += 1
            self.task_service.repository.upsert_page(
                {
                    "task_id": task_id,
                    "page_no": page_no,
                    "page_name": page_name,
                    "template_svg_ftp_path": template_svg_ftp_path,
                    "status": PAGE_STATUS_FAILED,
                    "error_message": str(exc),
                    "completed_at": datetime.now(),
                }
            )
            self.task_service.create_event(task_id, api_key, "page_failed", "page_generation", f"第 {page_no} 页结构化生成失败: {exc}", page_no=page_no)
            with lock:
                self._update_progress(task_id, counters, total_pages)

    def _update_progress(self, task_id: str, counters: dict, total_pages: int) -> None:
        """更新任务进度（调用方需持有 lock）。"""
        processed = counters["processed"]
        progress = min(10 + (processed / max(total_pages, 1)) * 80, 90)
        self.task_service.repository.update_task(
            task_id,
            {
                "processed_pages": counters["processed"],
                "completed_pages": counters["completed"],
                "skipped_pages": counters["skipped"],
                "failed_pages": counters["failed"],
                "progress": round(progress, 2),
                "last_heartbeat_at": datetime.now(),
            },
        )

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

    async def _run_body_task(self, api_key: str, task_id: str, task: dict) -> None:
        """正文任务：强制所有保留页走结构化填充，输出 body.pptx。"""
        await self._run_legacy_task(api_key, task_id, task)

    async def _run_diagrams_task(self, api_key: str, task_id: str, task: dict) -> None:
        """图形任务：为标记为 diagram 的页面生成独立 SVG。

        v4 完整版应使用单图 Prompt 和正文无关；当前先用 full-page SVG 占位，
        并保存到 sg_generation_diagram。
        """
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
            custom_requirements = request_payload.get("custom_requirements") or ""

            total_pages = len(source_svgs)
            self.task_service.repository.update_task(task_id, {"total_pages": total_pages, "current_stage": "diagram_generation", "progress": 10})

            template_rules: dict | None = None
            if self.pptx_builder_service is not None:
                try:
                    template_pptx_path = self.template_service.get_template_pptx_path(template)
                    template_rules = self.pptx_builder_service.parse_template_rules(
                        template_pptx_path,
                        task_workspace.analysis_dir / "template_rules.json",
                    )
                except Exception as exc:
                    logger.warning("模板规则解析失败: %s", exc)

            lock = threading.Lock()
            counters = {"processed": 0, "completed": 0, "skipped": 0, "failed": 0}
            # 当模板没有明确 diagram 页，但用户自定义要求中明确要画图时，允许复用一个 content 页
            force_diagram_state = {"done": False}

            with ThreadPoolExecutor(max_workers=max(total_pages, 1), thread_name_prefix=f"diagram-{task_id}") as executor:
                futures = {}
                for index, source_svg in enumerate(source_svgs, start=1):
                    page_rule = None
                    if template_rules is not None:
                        pages_list = template_rules.get("pages", [])
                        if index <= len(pages_list):
                            page_rule = pages_list[index - 1]
                    future = executor.submit(
                        self._process_diagram_page,
                        api_key=api_key,
                        task_id=task_id,
                        generation_id=task.get("generation_id"),
                        requirement_text=str(task["requirement_text"]),
                        page_no=index,
                        source_svg=source_svg,
                        total_pages=total_pages,
                        llm_model=llm_model,
                        llm_enable_thinking=llm_enable_thinking,
                        task_workspace=task_workspace,
                        task=task,
                        counters=counters,
                        lock=lock,
                        page_rule=page_rule,
                        custom_requirements=custom_requirements,
                        force_diagram_state=force_diagram_state,
                    )
                    futures[index] = future

                for future in as_completed(futures.values()):
                    try:
                        future.result()
                    except Exception as exc:
                        logger.error("图形页处理异常: %s", exc)

            with lock:
                completed = counters["completed"]
                failed = counters["failed"]
                processed = counters["processed"]
                skipped = counters["skipped"]

            status = TASK_STATUS_COMPLETED if failed == 0 else "completed_with_warnings" if completed > 0 else TASK_STATUS_FAILED
            self.task_service.repository.update_task(
                task_id,
                {
                    "status": status,
                    "current_stage": "completed",
                    "progress": 100,
                    "processed_pages": processed,
                    "completed_pages": completed,
                    "skipped_pages": skipped,
                    "failed_pages": failed,
                    "completed_at": datetime.now(),
                },
            )
            self.task_service.create_event(task_id, api_key, "completed", "completed", f"图形任务完成：成功 {completed}，失败 {failed}")
        except Exception as exc:
            logger.error("图形任务失败: %s", exc, exc_info=True)
            self.task_service.repository.update_task(
                task_id,
                {
                    "status": TASK_STATUS_FAILED,
                    "current_stage": "failed",
                    "error_message": str(exc),
                    "completed_at": datetime.now(),
                },
            )
            self.task_service.create_event(task_id, api_key, "failed", "failed", f"图形任务失败: {exc}")
        finally:
            try:
                if task_workspace.root.exists():
                    shutil.rmtree(task_workspace.root, ignore_errors=True)
            except Exception:
                pass
            self._notify_generation(task.get("generation_id"), task_id)

    def _process_diagram_page(
        self,
        api_key: str,
        task_id: str,
        generation_id: str | None,
        requirement_text: str,
        page_no: int,
        source_svg,
        total_pages: int,
        llm_model: str | None,
        llm_enable_thinking: bool,
        task_workspace,
        task: dict,
        counters: dict,
        lock: threading.Lock,
        page_rule: dict | None = None,
        custom_requirements: str = "",
        force_diagram_state: dict | None = None,
    ) -> None:
        """处理单个图形页：规划 → 生成 SVG → 校验 → 保存。"""
        page_name = source_svg.stem

        self.task_service.repository.upsert_page(
            {
                "task_id": task_id,
                "page_no": page_no,
                "page_name": page_name,
                "status": PAGE_STATUS_RUNNING,
                "started_at": datetime.now(),
            }
        )

        check_rules_text = ""
        if self.rule_matcher is not None and page_rule is not None:
            matched_rules = self.rule_matcher.match(
                page_name=page_rule.get("page_name", page_name),
                page_purpose=page_rule.get("page_purpose", "text"),
                element_text=" ".join(
                    (e.get("content_requirement") or "") + " " + (e.get("default_text") or "")
                    for e in page_rule.get("elements", [])
                ),
            )
            check_rules_text = self.rule_matcher.format_rules_for_prompt(matched_rules)

        svg_content = source_svg.read_text(encoding="utf-8", errors="ignore")

        # 匹配该图形的全局页面生成规范
        planning_rules_text = ""
        diagram_rules_text = ""
        if self.page_rule_matcher is not None:
            rule_page_name = page_rule.get("page_name", page_name) if page_rule else page_name
            planning_rules = self.page_rule_matcher.match(
                page_name=rule_page_name,
                apply_to="planning",
                svg_content=svg_content,
            )
            diagram_rules = self.page_rule_matcher.match(
                page_name=rule_page_name,
                apply_to="diagram",
                svg_content=svg_content,
            )
            planning_rules_text = self.page_rule_matcher.format_rules_for_prompt(planning_rules)
            diagram_rules_text = self.page_rule_matcher.format_rules_for_prompt(diagram_rules)

        page_plan = self.slide_service.plan_single_page(
            api_key=api_key,
            requirement_text=requirement_text,
            page_no=page_no,
            page_name=page_name,
            svg_content=svg_content,
            total_pages=total_pages,
            model=llm_model,
            enable_thinking=llm_enable_thinking,
            check_rules_text=check_rules_text,
            page_generation_rules_text=planning_rules_text,
            custom_requirements=custom_requirements,
        )

        # 兜底：如果用户明确要求画图但模板没有 diagram 页，复用第一个合适的 content 页
        if (
            page_plan.get("should_generate")
            and page_plan.get("page_type") != "diagram"
            and self._should_force_page_as_diagram(custom_requirements, page_plan)
            and force_diagram_state is not None
        ):
            with force_diagram_state.get("lock", lock):
                if not force_diagram_state.get("done"):
                    page_plan["page_type"] = "diagram"
                    page_plan["page_title"] = page_plan.get("page_title") or "产品连接关系图"
                    force_diagram_state["done"] = True

        if not page_plan.get("should_generate", True):
            with lock:
                counters["processed"] += 1
                counters["skipped"] += 1
            self.task_service.repository.upsert_page(
                {
                    "task_id": task_id,
                    "page_no": page_no,
                    "page_name": page_name,
                    "status": PAGE_STATUS_SKIPPED,
                    "should_generate": 0,
                    "skip_reason": page_plan.get("skip_reason", ""),
                    "completed_at": datetime.now(),
                }
            )
            with lock:
                self._update_progress(task_id, counters, total_pages)
            return

        page_type = page_plan.get("page_type", "content")
        if page_type != "diagram":
            with lock:
                counters["processed"] += 1
                counters["skipped"] += 1
            self.task_service.repository.upsert_page(
                {
                    "task_id": task_id,
                    "page_no": page_no,
                    "page_name": page_name,
                    "status": PAGE_STATUS_SKIPPED,
                    "should_generate": 0,
                    "skip_reason": "非 diagram 页面，图形任务跳过",
                    "completed_at": datetime.now(),
                }
            )
            with lock:
                self._update_progress(task_id, counters, total_pages)
            return

        page_title = page_plan.get("page_title") or page_name
        try:
            page_result = self.slide_service.generate_diagram_svg(
                api_key=api_key,
                requirement_text=requirement_text,
                page_no=page_no,
                page_name=page_name,
                page_title=page_title,
                model=llm_model,
                enable_thinking=llm_enable_thinking,
                check_rules_text=check_rules_text,
                page_generation_rules_text=diagram_rules_text,
                custom_requirements=custom_requirements,
            )

            if page_result.get("decision_source") == "failed" or not page_result.get("generated_svg"):
                with lock:
                    counters["processed"] += 1
                    counters["failed"] += 1
                self.task_service.repository.upsert_page(
                    {
                        "task_id": task_id,
                        "page_no": page_no,
                        "page_name": page_name,
                        "status": PAGE_STATUS_FAILED,
                        "error_message": page_result.get("raw_response_text") or "LLM 生成 SVG 失败",
                        "completed_at": datetime.now(),
                    }
                )
                with lock:
                    self._update_progress(task_id, counters, total_pages)
                return

            output_svg_path = task_workspace.svg_output_dir / f"page_{page_no:02d}.svg"
            final_svg_path = task_workspace.svg_final_dir / f"page_{page_no:02d}.svg"
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
                page_no=page_no,
                file_size_bytes=generated_svg_path.stat().st_size,
                content_type="image/svg+xml",
            )
            self.task_service.create_artifact(
                task_id,
                ARTIFACT_TYPE_DIAGRAM_SVG,
                ftp_final_svg_path,
                final_svg_path.name,
                page_no=page_no,
                is_final=True,
                file_size_bytes=final_svg_path.stat().st_size,
                content_type="image/svg+xml",
            )

            # 写入 sg_generation_diagram
            if self.diagram_repository is not None and generation_id:
                diagram_id = generate_id("dia")
                self.diagram_repository.create(
                    {
                        "diagram_id": diagram_id,
                        "generation_id": generation_id,
                        "task_id": task_id,
                        "page_key": f"page_{page_no}",
                        "template_page_no": page_no,
                        "diagram_title": page_title,
                        "section_title": page_title,
                        "diagram_kind": page_plan.get("page_type"),
                        "status": "completed" if validation_status == "passed" else "failed",
                        "ftp_original_svg_path": ftp_generated_svg_path,
                        "ftp_final_svg_path": ftp_final_svg_path,
                        "validation_status": validation_status,
                        "error_message": None if validation_status == "passed" else validation_message,
                    }
                )

            self.task_service.repository.upsert_page(
                {
                    "task_id": task_id,
                    "page_no": page_no,
                    "page_name": page_name,
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

            with lock:
                counters["processed"] += 1
                if validation_status == "passed":
                    counters["completed"] += 1
                else:
                    counters["failed"] += 1
                self._update_progress(task_id, counters, total_pages)
        except Exception as exc:
            with lock:
                counters["processed"] += 1
                counters["failed"] += 1
            self.task_service.repository.upsert_page(
                {
                    "task_id": task_id,
                    "page_no": page_no,
                    "page_name": page_name,
                    "status": PAGE_STATUS_FAILED,
                    "error_message": str(exc),
                    "completed_at": datetime.now(),
                }
            )
            with lock:
                self._update_progress(task_id, counters, total_pages)

    async def _run_compose_task(self, api_key: str, task_id: str, task: dict) -> None:
        """组装任务：将正文任务的 structured_results 与图形任务的 diagram_svg 合并成最终 PPTX。"""
        task_workspace = self.workspace.task(task_id)
        self.workspace.ensure_task_dirs(task_workspace)

        start_status = TASK_STATUS_RESUMING if task["status"] == TASK_STATUS_RESUMING else TASK_STATUS_RUNNING
        self.task_service.touch_running(task_id, start_status, "preparing")

        try:
            generation_id = task.get("generation_id")
            if not generation_id:
                raise ValueError("compose 任务缺少 generation_id")

            body_task = self.task_service.repository.get_task_by_generation_and_type(generation_id, TASK_TYPE_BODY)
            diagram_task = self.task_service.repository.get_task_by_generation_and_type(generation_id, TASK_TYPE_DIAGRAMS)

            if not body_task:
                raise ValueError("正文任务尚未创建，无法组装")
            if not diagram_task:
                raise ValueError("图形任务尚未创建，无法组装")
            if body_task["status"] not in {TASK_STATUS_COMPLETED, "completed_with_warnings"}:
                raise ValueError("正文任务尚未完成")
            if diagram_task["status"] not in {TASK_STATUS_COMPLETED, "completed_with_warnings"}:
                raise ValueError("图形任务尚未完成")

            self.task_service.repository.update_task(task_id, {"current_stage": "composing", "progress": 10})

            # 拉取正文结果
            structured_pages: dict[int, StructuredPageResult] = {}
            skipped_pages: set[int] = set()
            for artifact in self.task_service.repository.list_artifacts(body_task["task_id"]):
                if artifact["artifact_type"] == "structured_result" and artifact.get("page_no"):
                    local_path = task_workspace.structured_results_dir / artifact["file_name"]
                    self.ftp.download_file(str(artifact["ftp_path"]), local_path)
                    data = json.loads(local_path.read_text(encoding="utf-8"))
                    result = StructuredPageResult.model_validate(data)
                    if result.should_generate:
                        structured_pages[artifact["page_no"]] = result
                    else:
                        skipped_pages.add(artifact["page_no"])

            # 标记 body 中未保留页为 skipped
            for page in self.task_service.repository.list_pages(body_task["task_id"]):
                if page.get("status") == PAGE_STATUS_SKIPPED or not page.get("should_generate"):
                    skipped_pages.add(page["page_no"])

            # 拉取图形结果
            svg_pages: dict[int, Path] = {}
            if self.diagram_repository is not None:
                for diagram in self.diagram_repository.list_by_task(diagram_task["task_id"]):
                    if diagram["status"] != "completed" or not diagram.get("ftp_final_svg_path"):
                        continue
                    page_no = diagram["template_page_no"]
                    local_path = task_workspace.svg_final_dir / f"page_{page_no:02d}.svg"
                    self.ftp.download_file(str(diagram["ftp_final_svg_path"]), local_path)
                    svg_pages[page_no] = local_path

            # 拉取模板及规则
            template = self.template_service.get_template(str(task["template_id"]))
            template_pptx_path = self.template_service.get_template_pptx_path(template)
            template_rules = self.pptx_builder_service.parse_template_rules(
                template_pptx_path,
                task_workspace.analysis_dir / "template_rules.json",
            )

            self._sync_template_snapshot_to_ftp(task, task_workspace)

            # 组装最终 PPTX：保留正文结构化回填，图形 SVG 以插入模式叠在页面上
            output_pptx_path = task_workspace.exports_dir / "composed.pptx"
            result_pptx_path = self.hybrid_exporter.export(
                template_pptx_path=template_pptx_path,
                template_rules=template_rules,
                svg_pages=svg_pages,
                structured_pages=structured_pages,
                skipped_pages=skipped_pages,
                output_path=output_pptx_path,
                insert_svg_pages=set(svg_pages.keys()),
            )

            ftp_composed_path = self.ftp.upload_file(
                result_pptx_path,
                self.ftp.join(str(task["ftp_task_dir"]), "exports", "composed.pptx"),
            )
            self.task_service.create_artifact(
                task_id,
                ARTIFACT_TYPE_COMPOSED_PPTX,
                ftp_composed_path,
                "composed.pptx",
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
                    "ftp_result_pptx_path": ftp_composed_path,
                    "completed_at": datetime.now(),
                },
            )
            self.task_service.create_event(task_id, api_key, "exported", "completed", "最终 PPTX 组装完成")
        except Exception as exc:
            logger.error("组装任务失败: %s", exc, exc_info=True)
            self.task_service.repository.update_task(
                task_id,
                {
                    "status": TASK_STATUS_FAILED,
                    "current_stage": "failed",
                    "error_message": str(exc),
                    "completed_at": datetime.now(),
                },
            )
            self.task_service.create_event(task_id, api_key, "failed", "failed", f"组装任务失败: {exc}")
        finally:
            try:
                if task_workspace.root.exists():
                    shutil.rmtree(task_workspace.root, ignore_errors=True)
            except Exception:
                pass
            self._notify_generation(task.get("generation_id"), task_id)
