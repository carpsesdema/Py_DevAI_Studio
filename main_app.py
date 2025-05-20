import sys
import os
import logging
import asyncio
from typing import Optional

import qasync

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFontDatabase, QIcon

from utils import constants
from core.app_settings import AppSettings
from core.ai_comms_logger import AICommsLogger
from ui.main_window import MainWindow


def global_exception_hook(exctype, value, traceback_obj):
    logger = logging.getLogger(constants.APP_NAME)
    logger.critical("Unhandled exception caught at global level:", exc_info=(exctype, value, traceback_obj))
    sys.__excepthook__(exctype, value, traceback_obj)


sys.excepthook = global_exception_hook


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(constants.LOG_LEVEL)

    file_handler = logging.FileHandler(constants.LOG_FILE_PATH, mode='a', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(constants.LOG_FORMAT))

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(constants.LOG_FORMAT))

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    logging.info(f"--- {constants.APP_NAME} v{constants.APP_VERSION} Logging Started ---")
    logging.info(f"Base Directory: {constants.APP_BASE_DIR}")
    logging.info(f"User Data Directory: {constants.USER_DATA_BASE_DIR}")
    logging.info(f"Log File Path: {constants.LOG_FILE_PATH}")


class PyDevAIApplication(QApplication):
    def __init__(self, argv: list[str]):
        super().__init__(argv)
        self.main_window: Optional[MainWindow] = None
        self.settings: Optional[AppSettings] = None
        self.ai_comms_logger: Optional[AICommsLogger] = None
        self.logger = logging.getLogger(constants.APP_NAME)

        self._load_custom_font()
        self._set_application_details()

    def _load_custom_font(self) -> None:
        font_path = os.path.join(constants.ASSETS_DIR, "JetBrainsMono-Regular.ttf")
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                font_families = QFontDatabase.applicationFontFamilies(font_id)
                if font_families:
                    self.logger.info(f"Successfully loaded custom font: '{font_families[0]}' from {font_path}")
                else:
                    self.logger.error(f"Loaded font from {font_path}, but no font families found.")
            else:
                self.logger.error(
                    f"Failed to load custom font from {font_path}. QFontDatabase.addApplicationFont returned -1.")
        else:
            self.logger.warning(
                f"Custom font 'JetBrainsMono-Regular.ttf' not found at {font_path}. Using system default.")

    def _set_application_details(self) -> None:
        self.setApplicationName(constants.APP_NAME)
        self.setApplicationVersion(constants.APP_VERSION)
        self.setOrganizationName(constants.APP_AUTHOR)

        icon_path = os.path.join(constants.ASSETS_DIR, "Synchat.ico")
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            if not app_icon.isNull():
                self.setWindowIcon(app_icon)
                self.logger.info(f"Application icon set from {icon_path}")
            else:
                self.logger.warning(f"Failed to create QIcon from {icon_path}, icon is null.")
        else:
            self.logger.warning(f"Application icon 'Synchat.ico' not found at {icon_path}.")

    async def initialize_core_components(self):
        self.logger.info("Initializing core application components...")
        self.settings = AppSettings()
        self.ai_comms_logger = AICommsLogger.get_instance(parent_for_first_init=self)

        self.main_window = MainWindow(app_settings=self.settings, comms_logger=self.ai_comms_logger)

        await self.main_window.async_initialize_components()
        self.main_window.show()
        self.logger.info("Application components initialized and main window shown.")

    def perform_cleanup(self):
        self.logger.info("Application is performing cleanup...")
        if self.main_window:
            self.main_window.cleanup_before_exit()
        if self.settings:
            self.settings.save()
        self.logger.info("Cleanup finished. Exiting.")
        logging.shutdown()


async def run_application():
    setup_logging()

    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = PyDevAIApplication(sys.argv)
    app.aboutToQuit.connect(app.perform_cleanup)

    if sys.platform == "win32" and sys.version_info >= (3, 8):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    try:
        await app.initialize_core_components()
        with loop:
            loop.run_forever()
    except KeyboardInterrupt:
        app.logger.info("KeyboardInterrupt caught. Application shutting down.")
    except Exception as e:
        app.logger.critical(f"Critical error during application execution: {e}", exc_info=True)
    finally:
        if loop and not loop.is_closed():
            loop.close()
        app.exit()


if __name__ == '__main__':
    try:
        asyncio.run(run_application())
    except RuntimeError as e_runtime:
        if "Event loop is already running" in str(e_runtime):
            logging.warning("Async event loop already running. This might occur in some IDEs.")
        else:
            logging.critical(f"RuntimeError starting application: {e_runtime}", exc_info=True)
            sys.exit(1)
    except Exception as e_global:
        logging.critical(f"Global exception during application startup: {e_global}", exc_info=True)
        sys.exit(1)