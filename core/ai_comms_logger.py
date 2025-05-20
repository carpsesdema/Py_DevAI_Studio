import logging
from PyQt6.QtCore import QObject, pyqtSignal
from typing import Optional, List, Any

module_logger = logging.getLogger(__name__)

class AICommsLogger(QObject):
    newLogMessage = pyqtSignal(str)
    _instance: Optional['AICommsLogger'] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> 'AICommsLogger':
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._log_buffer: List[str] = []
            cls._instance._max_buffer_size: int = 500
            cls._instance._qobject_initialized_for_instance: bool = False
        return cls._instance

    def __init__(self, parent: Optional[QObject] = None):
        if hasattr(self, '_qobject_initialized_for_instance') and self._qobject_initialized_for_instance:
            return

        super().__init__(parent)
        self._qobject_initialized_for_instance = True
        module_logger.info("AICommsLogger instance QObject part initialized.")

    @classmethod
    def get_instance(cls, parent_for_first_init: Optional[QObject] = None) -> 'AICommsLogger':
        if not cls._instance:
            cls._instance = cls(parent=parent_for_first_init)
        elif parent_for_first_init and not cls._instance.parent() and cls._instance._qobject_initialized_for_instance:
            pass
        return cls._instance

    def log(self, message: str, source: str = "System") -> None:
        if not hasattr(self, '_qobject_initialized_for_instance') or not self._qobject_initialized_for_instance:
            print(f"AICommsLogger.log() called before QObject part of instance was fully initialized. Message from {source}: {message}")
            return

        if not isinstance(message, str):
            try:
                message = str(message)
            except Exception:
                message = "AICommsLogger: Received non-string loggable message."

        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        full_message = f"[{timestamp}][{source}] {message}"

        if len(full_message) > 1024 * 16:
            full_message = full_message[:1024*16] + "... (truncated)"

        try:
            if hasattr(self, 'newLogMessage') and isinstance(self.newLogMessage, pyqtSignal):
                 self.newLogMessage.emit(full_message)
            else:
                print(f"Error: newLogMessage signal not properly initialized. Log: {full_message}")
        except Exception as e:
            print(f"AICommsLogger.log(): Error emitting newLogMessage signal: {e}. Message: {full_message}")

        if hasattr(self, '_log_buffer'):
            self._log_buffer.append(full_message)
            if len(self._log_buffer) > self._max_buffer_size:
                self._log_buffer.pop(0)
        else:
            print(f"AICommsLogger.log: _log_buffer attribute missing! Message: {full_message}")

    def get_buffered_logs(self) -> List[str]:
        if hasattr(self, '_log_buffer'):
            return list(self._log_buffer)
        print("AICommsLogger.get_buffered_logs: _log_buffer attribute missing!")
        return []

    def clear_buffer(self) -> None:
        if hasattr(self, '_log_buffer'):
            self._log_buffer.clear()
            module_logger.debug("AICommsLogger buffer cleared.")