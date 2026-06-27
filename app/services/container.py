from __future__ import annotations

from app.core.config import Settings
from app.infrastructure.db.mysql import MySQLDatabase
from app.infrastructure.db.task_repository import TaskRepository
from app.infrastructure.db.template_repository import TemplateRepository
from app.infrastructure.ppt_master.pptx_to_svg_adapter import PptxToSvgAdapter
from app.infrastructure.ppt_master.project_workspace import ProjectWorkspace
from app.infrastructure.ppt_master.svg_to_pptx_adapter import SvgToPptxAdapter
from app.infrastructure.storage.ftp import FtpStorage
from app.infrastructure.tasking.runner import TaskRunner


class ServiceContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = MySQLDatabase(settings)
        self.ftp = FtpStorage(settings)
        self.workspace = ProjectWorkspace(settings)
        self.pptx_to_svg = PptxToSvgAdapter(settings)
        self.svg_to_pptx = SvgToPptxAdapter(settings)
        self.task_runner = TaskRunner()
        self.templates = TemplateRepository(self.db)
        self.tasks = TaskRepository(self.db)
