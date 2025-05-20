import logging
from typing import List, Optional, Any, Union

from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt, pyqtSignal, QObject

from utils import constants

logger = logging.getLogger(constants.APP_NAME)

try:
    from core.models import ChatMessage
    from core.message_enums import MessageLoadingState
except ImportError:
    logger.critical("ChatListModel: Failed to import core.models or core.message_enums. Using placeholders.")


    class ChatMessage:
        def __init__(self, role: str, content: str, image_data: Optional[List[dict]] = None,
                     metadata: Optional[dict] = None, id: Optional[str] = None, loading_state=None):
            self.role = role
            self.content = content  # Simplified: assuming text content is primary
            self.image_data = image_data or []
            self.metadata = metadata or {}
            self.id = id or "dummy_id"
            self.loading_state = loading_state if loading_state is not None else MessageLoadingState.IDLE
            self.timestamp = "dummy_timestamp"


    class MessageLoadingState:
        IDLE = 0
        LOADING = 1
        COMPLETED = 2
        ERROR = 3

        # Add name property for compatibility if used in logging
        @property
        def name(self):
            return {0: "IDLE", 1: "LOADING", 2: "COMPLETED", 3: "ERROR"}.get(self, "UNKNOWN")

ChatMessageRole = Qt.ItemDataRole.UserRole + 1
LoadingStatusRole = Qt.ItemDataRole.UserRole + 2
MessageIdRole = Qt.ItemDataRole.UserRole + 3


class ChatListModel(QAbstractListModel):
    message_content_updated_for_streaming = pyqtSignal(QModelIndex)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._messages: List[ChatMessage] = []
        logger.info("ChatListModel initialized.")

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._messages)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._messages)):
            return None

        message = self._messages[index.row()]

        if role == ChatMessageRole:
            return message
        elif role == Qt.ItemDataRole.DisplayRole:
            return f"[{message.role}] {message.content[:50]}..." if hasattr(message,
                                                                            'content') and message.content else f"[{message.role}] (No text content)"
        elif role == LoadingStatusRole:
            return message.loading_state if hasattr(message, 'loading_state') else MessageLoadingState.IDLE
        elif role == MessageIdRole:
            return message.id if hasattr(message, 'id') else None
        return None

    def addMessage(self, message: ChatMessage) -> None:
        if not isinstance(message, ChatMessage) and not isinstance(message,
                                                                   dict):  # Allow dict for flexibility if core.models not fully loaded
            logger.error(f"Attempted to add invalid type to ChatListModel: {type(message)}")
            return

        if isinstance(message, dict):  # Convert dict to ChatMessage if necessary
            try:
                message = ChatMessage(
                    role=message.get("role", "user"),
                    content=message.get("content", ""),
                    image_data=message.get("image_data"),
                    metadata=message.get("metadata"),
                    id=message.get("id"),
                    loading_state=message.get("loading_state", MessageLoadingState.IDLE)
                )
            except Exception as e_conv:
                logger.error(f"Failed to convert dict to ChatMessage: {e_conv}")
                return

        row_to_insert = len(self._messages)
        self.beginInsertRows(QModelIndex(), row_to_insert, row_to_insert)
        self._messages.append(message)
        self.endInsertRows()

    def appendChunkToLastMessage(self, chunk: str) -> None:
        if not self._messages:
            return
        if not isinstance(chunk, str):
            return

        last_message = self._messages[-1]

        current_text = last_message.content if hasattr(last_message, 'content') else ""
        last_message.content = current_text + chunk

        if not hasattr(last_message, 'metadata') or last_message.metadata is None:
            last_message.metadata = {}
        last_message.metadata["is_streaming"] = True

        last_model_idx = self.index(len(self._messages) - 1, 0)
        self.dataChanged.emit(last_model_idx, last_model_idx, [ChatMessageRole])
        self.message_content_updated_for_streaming.emit(last_model_idx)

    def finalizeLastMessage(self) -> None:
        if not self._messages:
            return

        last_message = self._messages[-1]
        if hasattr(last_message, 'metadata') and last_message.metadata and last_message.metadata.get("is_streaming"):
            last_message.metadata["is_streaming"] = False
            if hasattr(last_message, 'loading_state'):  # Ensure loading state is completed
                last_message.loading_state = MessageLoadingState.COMPLETED
            model_index = self.index(len(self._messages) - 1, 0)
            self.dataChanged.emit(model_index, model_index, [ChatMessageRole, LoadingStatusRole])

    def updateMessage(self, index_row: int, new_message_data: ChatMessage) -> None:
        if not (0 <= index_row < len(self._messages)):
            return
        if not isinstance(new_message_data, ChatMessage) and not isinstance(new_message_data, dict):
            return

        if isinstance(new_message_data, dict):
            try:
                new_message_data = ChatMessage(
                    role=new_message_data.get("role", self._messages[index_row].role),
                    content=new_message_data.get("content", self._messages[index_row].content),
                    image_data=new_message_data.get("image_data", self._messages[index_row].image_data),
                    metadata=new_message_data.get("metadata", self._messages[index_row].metadata),
                    id=new_message_data.get("id", self._messages[index_row].id),
                    loading_state=new_message_data.get("loading_state", self._messages[index_row].loading_state)
                )
            except Exception as e_conv_update:
                logger.error(f"Failed to convert dict to ChatMessage for update: {e_conv_update}")
                return

        self._messages[index_row] = new_message_data
        model_idx = self.index(index_row, 0)
        self.dataChanged.emit(model_idx, model_idx, [ChatMessageRole, LoadingStatusRole, Qt.ItemDataRole.DisplayRole])

    def update_message_loading_state_by_id(self, message_id: str, new_state: MessageLoadingState) -> bool:
        if not isinstance(message_id, str) or not message_id:
            return False

        for row, message in enumerate(self._messages):
            if hasattr(message, 'id') and message.id == message_id:
                if not hasattr(message, 'loading_state') or message.loading_state != new_state:
                    message.loading_state = new_state
                    model_index = self.index(row, 0)
                    self.dataChanged.emit(model_index, model_index, [LoadingStatusRole])
                    return True
                return True
        return False

    def find_message_row_by_id(self, message_id: str) -> Optional[int]:
        if not isinstance(message_id, str) or not message_id:
            return None
        for row, msg in enumerate(self._messages):
            if hasattr(msg, 'id') and msg.id == message_id:
                return row
        return None

    def loadHistory(self, history: List[ChatMessage]) -> None:
        self.beginResetModel()

        processed_history = []
        for item in history:
            if isinstance(item, ChatMessage):
                processed_history.append(item)
            elif isinstance(item, dict):
                try:
                    processed_history.append(ChatMessage(
                        role=item.get("role", "user"),
                        content=item.get("content", ""),
                        image_data=item.get("image_data"),
                        metadata=item.get("metadata"),
                        id=item.get("id"),
                        loading_state=item.get("loading_state", MessageLoadingState.IDLE)
                    ))
                except Exception as e_hist_load:
                    logger.error(f"Error converting history item dict to ChatMessage: {e_hist_load}")
            else:
                logger.warning(f"Skipping invalid item type in history: {type(item)}")

        self._messages = processed_history
        self.endResetModel()

    def clearMessages(self) -> None:
        self.beginResetModel()
        self._messages = []
        self.endResetModel()

    def getMessage(self, row: int) -> Optional[ChatMessage]:
        if 0 <= row < len(self._messages):
            return self._messages[row]
        return None

    def getAllMessages(self) -> List[ChatMessage]:
        return list(self._messages)