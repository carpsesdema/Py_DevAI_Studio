# main.py
import asyncio
import logging
import os
import sys
import traceback
from typing import Optional
from logging.handlers import RotatingFileHandler # <-- ADDED for better file logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox, QStyle

try:
    import qasync
except ImportError:
    print("[CRITICAL] qasync library not found. Please install it: pip install qasync", file=sys.stderr)
    try:
        _dummy_app = QApplication.instance() or QApplication(sys.argv);
        QMessageBox.critical(None, "Missing Dependency",
                             "Required library 'qasync' is not installed.\nPlease run: pip install qasync")
    except Exception as e:
        print(f"Failed to show missing dependency message: {e}", file=sys.stderr)
    sys.exit(1)

try:
    from ui.main_window import MainWindow
    from core.chat_manager import ChatManager
    from core.application_orchestrator import ApplicationOrchestrator
    from services.session_service import SessionService
    from services.upload_service import UploadService
    from core.chat_message_state_handler import ChatMessageStateHandler
    from utils import constants # <-- IMPORT constants
    from utils.constants import ( # <-- Specific imports from constants
        CHAT_FONT_FAMILY, LOG_LEVEL, LOG_FORMAT, APP_VERSION, APP_NAME,
        ASSETS_PATH, USER_DATA_DIR, LOG_FILE_NAME # <-- ADDED USER_DATA_DIR, LOG_FILE_NAME
    )
except ImportError as e:
    print(f"[CRITICAL] Failed to import core components in main.py: {e}", file=sys.stderr)
    print(f"PYTHONPATH: {sys.path}", file=sys.stderr)
    try:
        _dummy_app = QApplication.instance() or QApplication(sys.argv);
        QMessageBox.critical(None, "Import Error",
                             f"Failed to import core components:\n{e}\nCheck PYTHONPATH.")
    except Exception as e_qm:
        print(f"Failed to show import error message: {e_qm}", file=sys.stderr)
    sys.exit(1)


# --- Logging Setup ---
# Ensure the user data directory (where logs will be stored) exists
try:
    os.makedirs(USER_DATA_DIR, exist_ok=True)
except OSError as e_dir:
    # If we can't create the log directory, we might have to fall back to console-only
    # or exit, depending on how critical file logging is.
    print(f"[CRITICAL] Could not create user data directory {USER_DATA_DIR} for logging: {e_dir}", file=sys.stderr)
    # For now, we'll let basicConfig try to handle it, but it might fail if dir doesn't exist for FileHandler

log_file_path = os.path.join(USER_DATA_DIR, LOG_FILE_NAME)
log_level_actual = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

# Create handlers
# File Handler - Captures DEBUG and above
# Using RotatingFileHandler for better log management (max 5MB, 3 backup files)
file_handler = RotatingFileHandler(log_file_path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
file_handler.setLevel(log_level_actual) # Set to DEBUG for file
file_formatter = logging.Formatter(LOG_FORMAT)
file_handler.setFormatter(file_formatter)

# Console Handler - Captures WARNING and above (to reduce spam)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING) # Higher level for console
console_formatter = logging.Formatter('%(levelname)s: [%(name)s.%(funcName)s] %(message)s') # Simpler format for console
console_handler.setFormatter(console_formatter)

# Get the root logger and add handlers
root_logger = logging.getLogger()
root_logger.setLevel(log_level_actual) # Set root logger to the most verbose level needed by any handler
root_logger.handlers.clear() # Clear any existing handlers (important if basicConfig was called elsewhere)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Set levels for noisy libraries AFTER setting up our root logger and handlers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.INFO)
logging.getLogger("PIL.PngImagePlugin").setLevel(logging.INFO) # Pillow can be noisy with PNGs
# --- End Logging Setup ---

# Now, use the logger instance obtained *after* configuration
logger = logging.getLogger(__name__)
logger.info(f"Logging configured. File output to: {log_file_path}")


async def async_main():
    logger.info(f"--- Starting {APP_NAME} v{APP_VERSION} (Async with Orchestrator & StateHandler) ---")

    app = QApplication.instance()
    if app is None:
        if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'): QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'): QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
        app = QApplication(sys.argv)

    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))
    logger.info(f"Application base path: {application_path}")
    logger.info("--- Font Setup: Relying on system fonts ---")
    app.setStyle("Fusion");
    app.setApplicationName(APP_NAME);
    app.setApplicationVersion(APP_VERSION)

    try:
        app_icon_path = os.path.join(ASSETS_PATH, "Synchat.ico")
        std_fallback_icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        app_icon = QIcon(app_icon_path) if os.path.exists(app_icon_path) else std_fallback_icon
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
        elif not std_fallback_icon.isNull():
            app.setWindowIcon(std_fallback_icon)
        else:
            logger.warning("Could not load custom or standard fallback icon.")
    except Exception as e:
        logger.error(f"Error setting application icon: {e}", exc_info=True)

    logger.info("--- Instantiating Application Components ---")
    main_window: Optional[MainWindow] = None
    chat_message_state_handler: Optional[ChatMessageStateHandler] = None
    chat_manager: Optional[ChatManager] = None

    try:
        session_service = SessionService()
        upload_service = UploadService()
        app_orchestrator = ApplicationOrchestrator(session_service=session_service, upload_service=upload_service)
        logger.info("ApplicationOrchestrator instantiated.")
        chat_manager = ChatManager(orchestrator=app_orchestrator)
        logger.info("ChatManager instantiated with orchestrator.")

        main_window = MainWindow(chat_manager=chat_manager, app_base_path=application_path)
        logger.info("MainWindow instantiated.")

        if main_window and main_window.chat_tab_manager:
            active_chat_tab = main_window.chat_tab_manager.get_active_chat_tab_instance()
            chat_list_model_instance = None
            if active_chat_tab:
                chat_display_area = active_chat_tab.get_chat_display_area()
                if chat_display_area:
                    chat_list_model_instance = chat_display_area.get_model()
                    if chat_display_area.chat_item_delegate:
                        chat_display_area.chat_item_delegate.setView(chat_display_area.chat_list_view)
                        logger.info("Set view reference for initial active tab's delegate.")

            if chat_list_model_instance:
                backend_coordinator_instance = chat_manager.get_backend_coordinator()
                if backend_coordinator_instance:
                    chat_message_state_handler = ChatMessageStateHandler(
                        model=chat_list_model_instance,
                        backend_coordinator=backend_coordinator_instance,
                        parent=app
                    )
                    logger.info("ChatMessageStateHandler instantiated and wired to initial active model.")
                else:
                    logger.error("Critical: BackendCoordinator not available. ChatMessageStateHandler NOT created.")
            else:
                logger.warning(
                    "ChatMessageStateHandler NOT created: Could not get a ChatListModel instance from initial active tab (this is normal if no tabs are open on startup).")
        logger.info("--- Core Components Instantiated ---")
    except Exception as e:
        logger.exception(" ***** FATAL ERROR DURING COMPONENT INSTANTIATION ***** ")
        try:
            QMessageBox.critical(None, "Fatal Init Error", f"Failed during component setup:\n{e}\n\nCheck logs at {log_file_path}")
        except Exception:
            print(f"[CRITICAL] Component Init Failed: {e}\nTraceback:\n{traceback.format_exc()}", file=sys.stderr)
        if app:
            app.quit()
        return 1

    if chat_manager:
        QTimer.singleShot(100, chat_manager.initialize)
        logger.info("Scheduled ChatManager late initialization.")
    else:
        logger.critical("ChatManager failed to instantiate. Application cannot continue.")
        if app: app.quit()
        return 1

    if main_window:
        main_window.setGeometry(100, 100, 1100, 850)
        main_window.show()
        logger.info("--- Main Window Shown ---")
    else:
        logger.error("MainWindow instance not created, cannot show window.")
        if app: app.quit()
        return 1

    logger.info("--- async_main: Entering main blocking phase (await asyncio.Future()) ---")
    if app:
        await asyncio.Future()
        logger.info("--- async_main: asyncio.Future() completed. Application is shutting down. ---")
    else:
        logger.error("--- async_main: app instance is None. Cannot block. Application will likely exit. ---")

    logger.info(f"--- async_main returning, Application Event Loop should be finishing ---")
    return 0


if __name__ == "__main__":
    # This initial log might go to console before file handler is fully up if there's an early issue,
    # but subsequent logs from within async_main and components will use the configured handlers.
    logger.info(f"Application starting (__name__ == '__main__'). Log file: {log_file_path}")

    q_app_instance = QApplication.instance()
    if q_app_instance is None:
        if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'): QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'): QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
        q_app_instance = QApplication(sys.argv)

    event_loop: Optional[qasync.QEventLoop] = None
    exit_code = 1

    try:
        if sys.platform == "win32" and sys.version_info >= (3, 8):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        event_loop = qasync.QEventLoop(q_app_instance)
        asyncio.set_event_loop(event_loop)

        with event_loop:
            exit_code = event_loop.run_until_complete(async_main())

    except RuntimeError as e:
        if "cannot be nested" in str(e).lower() or "already running" in str(e).lower():
            logger.warning(f"qasync event loop issue: {e}. Loop may already be running (e.g. interactive environment).")
            if QApplication.instance() and QApplication.instance().activeWindow():
                pass
            else:
                exit_code = 1
        else:
            logger.critical(f"RuntimeError during qasync execution: {e}", exc_info=True)
            try:
                QMessageBox.critical(None, "Runtime Error", f"Application failed to run:\n{e}\n\nCheck logs at {log_file_path}")
            except Exception:
                pass
            exit_code = 1
    except Exception as e:
        logger.critical(f"Unhandled exception during application startup/run: {e}", exc_info=True)
        try:
            QMessageBox.critical(None, "Unhandled Exception", f"An unexpected error occurred:\n{e}\n\nCheck logs at {log_file_path}")
        except Exception:
            pass
        exit_code = 1
    finally:
        logger.info(f"Application attempting to exit with code: {exit_code}")
        if event_loop and event_loop.is_running():
            logger.info("Event loop still running in finally block, attempting to close.")
            event_loop.close()
        logging.shutdown() # <-- Ensure all log handlers are flushed and closed
        sys.exit(exit_code)