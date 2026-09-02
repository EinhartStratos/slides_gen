from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.infrastructure.llm.concurrency import init_global_semaphore
from app.infrastructure.llm.openai_like_client import OpenAILikePageGenerationClient
from app.infrastructure.llm.prompt_builder import PageAnalysisPromptBuilder
from app.infrastructure.llm.rule_matcher import PageGenerationRuleMatcher, RuleMatcher
from app.services.builtin_template_service import BuiltinTemplateService
from app.services.container import ServiceContainer
from app.services.diagram_service import DiagramService
from app.services.generation_service import GenerationService
from app.services.orchestration_service import OrchestrationService
from app.services.pptx_builder_service import PptxBuilderService
from app.services.pptx_export_service import PptxExportService
from app.services.hybrid_pptx_exporter import HybridPptxExporter
from app.services.slide_generation_service import SlideGenerationService
from app.services.svg_validation_service import SvgValidationService
from app.services.task_service import TaskService
from app.services.template_import_service import TemplateImportService
from app.services.template_service import TemplateService


@dataclass(slots=True)
class AppServices:
    container: ServiceContainer
    template_service: TemplateService
    template_import_service: TemplateImportService
    builtin_template_service: BuiltinTemplateService
    task_service: TaskService
    generation_service: GenerationService
    diagram_service: DiagramService
    slide_generation_service: SlideGenerationService
    svg_validation_service: SvgValidationService
    pptx_export_service: PptxExportService
    pptx_builder_service: PptxBuilderService
    hybrid_exporter: HybridPptxExporter
    orchestration_service: OrchestrationService


def build_services(settings: Settings) -> AppServices:
    init_global_semaphore(settings.max_llm_concurrency)
    container = ServiceContainer(settings)
    template_service = TemplateService(
        repository=container.templates,
        workspace=container.workspace,
        ftp=container.ftp,
        pptx_to_svg=container.pptx_to_svg,
    )
    template_import_service = TemplateImportService(
        repository=container.templates,
        workspace=container.workspace,
        ftp=container.ftp,
        pptx_to_svg=container.pptx_to_svg,
    )
    builtin_template_service = BuiltinTemplateService(
        settings=settings,
        repository=container.templates,
        template_import_service=template_import_service,
    )
    task_service = TaskService(
        repository=container.tasks,
        workspace=container.workspace,
        ftp=container.ftp,
        template_service=template_service,
        builtin_template_service=builtin_template_service,
        default_template_id=settings.default_template_id,
    )
    prompt_builder = PageAnalysisPromptBuilder()
    generation_client = OpenAILikePageGenerationClient(settings=settings, prompt_builder=prompt_builder)
    slide_generation_service = SlideGenerationService(generation_client=generation_client)
    svg_validation_service = SvgValidationService()
    pptx_export_service = PptxExportService(container.svg_to_pptx)
    pptx_builder_service = PptxBuilderService(generation_client=generation_client)
    hybrid_exporter = HybridPptxExporter(settings=settings)
    rule_matcher = RuleMatcher.from_file("app/config/check_rules.json")
    page_rule_matcher = PageGenerationRuleMatcher.from_file(settings.page_generation_rules_file)
    orchestration_service = OrchestrationService(
        workspace=container.workspace,
        ftp=container.ftp,
        task_service=task_service,
        template_service=template_service,
        slide_service=slide_generation_service,
        svg_validation_service=svg_validation_service,
        pptx_export_service=pptx_export_service,
        diagram_repository=container.diagrams,
        pptx_builder_service=pptx_builder_service,
        hybrid_exporter=hybrid_exporter,
        rule_matcher=rule_matcher,
        page_rule_matcher=page_rule_matcher,
        settings=settings,
    )
    generation_service = GenerationService(
        settings=settings,
        generation_repository=container.generations,
        task_repository=container.tasks,
        diagram_repository=container.diagrams,
        task_service=task_service,
        template_service=template_service,
        builtin_template_service=builtin_template_service,
        workspace=container.workspace,
        ftp=container.ftp,
        task_runner=container.task_runner,
        orchestration_service=orchestration_service,
    )
    orchestration_service.set_generation_service(generation_service)
    diagram_service = DiagramService(
        task_repository=container.tasks,
        diagram_repository=container.diagrams,
        workspace=container.workspace,
        ftp=container.ftp,
    )
    return AppServices(
        container=container,
        template_service=template_service,
        template_import_service=template_import_service,
        builtin_template_service=builtin_template_service,
        task_service=task_service,
        generation_service=generation_service,
        diagram_service=diagram_service,
        slide_generation_service=slide_generation_service,
        svg_validation_service=svg_validation_service,
        pptx_export_service=pptx_export_service,
        pptx_builder_service=pptx_builder_service,
        hybrid_exporter=hybrid_exporter,
        orchestration_service=orchestration_service,
    )
