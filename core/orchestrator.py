import logging
from typing import Optional, Dict, Any

from .app_settings import AppSettings
from .ai_comms_logger import AICommsLogger
from .llm_manager import LLMManager
from .rag_service import RAGService
from .file_manager import FileManager
from .project_manager import ProjectManager
from utils import constants

logger = logging.getLogger(constants.APP_NAME)


class AppOrchestrator:
    def __init__(self, app_settings: AppSettings, comms_logger: AICommsLogger):
        if not isinstance(app_settings, AppSettings):
            raise TypeError("AppOrchestrator requires a valid AppSettings instance.")
        if not isinstance(comms_logger, AICommsLogger):
            raise TypeError("AppOrchestrator requires a valid AICommsLogger instance.")

        self.settings: AppSettings = app_settings
        self.comms_logger: AICommsLogger = comms_logger

        self.project_manager: Optional[ProjectManager] = None
        self.file_manager: Optional[FileManager] = None
        self.rag_service: Optional[RAGService] = None
        self.llm_manager: Optional[LLMManager] = None

        self._initialize_components()

    def _initialize_components(self) -> None:
        logger.info("AppOrchestrator initializing sub-components...")

        self.project_manager = ProjectManager(settings=self.settings)
        logger.info("ProjectManager initialized.")

        self.file_manager = FileManager(settings=self.settings, project_manager=self.project_manager)
        logger.info("FileManager initialized.")

        self.rag_service = RAGService(settings=self.settings, project_manager=self.project_manager)
        logger.info("RAGService initialized.")

        self.llm_manager = LLMManager(settings=self.settings, comms_logger=self.comms_logger,
                                      rag_service=self.rag_service)
        logger.info("LLMManager initialized.")

        logger.info("AppOrchestrator all sub-components initialized.")

    def get_settings(self) -> AppSettings:
        return self.settings

    def get_comms_logger(self) -> AICommsLogger:
        return self.comms_logger

    def get_project_manager(self) -> Optional[ProjectManager]:
        return self.project_manager

    def get_file_manager(self) -> Optional[FileManager]:
        return self.file_manager

    def get_rag_service(self) -> Optional[RAGService]:
        return self.rag_service

    def get_llm_manager(self) -> Optional[LLMManager]:
        return self.llm_manager

    async def initialize_async_services(self) -> None:
        logger.info("AppOrchestrator initializing asynchronous services...")
        if self.llm_manager:
            await self.llm_manager.load_configured_models()
        if self.rag_service:
            await self.rag_service.initialize_rag_for_active_project()
        logger.info("AppOrchestrator asynchronous services initialization complete.")

    def shutdown_services(self) -> None:
        logger.info("AppOrchestrator shutting down services...")
        if self.rag_service:
            self.rag_service.shutdown()
        if self.llm_manager:
            pass
        logger.info("AppOrchestrator services shutdown complete.")