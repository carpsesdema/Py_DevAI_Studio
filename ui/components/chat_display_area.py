import logging
from typing import List, Optional, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QListView, QAbstractItemView, QMenu, QApplication
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QModelIndex, QPoint, pyqtSignal
from PyQt6.QtGui import QAction

from utils import constants
from .chat_list_model import ChatListModel, ChatMessageRole, LoadingStatusRole
from core.models import ChatMessage
from .chat_item_delegate import ChatItemDelegate
from core.message_enums import MessageLoadingState

logger = logging.getLogger(constants.APP_NAME)


class ChatDisplayArea(QWidget):
    text_copied_to_clipboard = pyqtSignal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ChatDisplayAreaWidget")

        self.list_view = None
        self.model = None
        self.delegate = None

        self._init_ui()
        self._connect_internal_signals()
        logger.info("ChatDisplayArea initialized.")

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.list_view = QListView(self)
        self.list_view.setObjectName("ChatMessagesListView")
        self.list_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setUniformItemSizes(False)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.model = ChatListModel(self)
        self.list_view.setModel(self.model)

        self.delegate = ChatItemDelegate(self)
        self.delegate.setView(self.list_view)
        self.list_view.setItemDelegate(self.delegate)

        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        layout.addWidget(self.list_view)
        self.setLayout(layout)

    def _connect_internal_signals(self) -> None:
        if self.list_view:
            self.list_view.customContextMenuRequested.connect(self._show_context_menu)
        if self.model:
            self.model.modelReset.connect(self._handle_model_reset_for_delegate)
            self.model.rowsInserted.connect(lambda parent, first, last: QTimer.singleShot(0, self._scroll_to_bottom))

    @pyqtSlot()
    def _handle_model_reset_for_delegate(self) -> None:
        if self.delegate:
            self.delegate.clearCache()
        self._scroll_to_bottom()

    def get_model(self) -> Optional[ChatListModel]:
        return self.model

    def add_message_to_model(self, message: ChatMessage) -> None:
        if self.model:
            self.model.addMessage(message)

    def update_message_in_model(self, index: int, message: ChatMessage) -> None:
        if self.model:
            self.model.updateMessage(index, message)

    def start_streaming_in_model(self, initial_message_placeholder: ChatMessage) -> None:
        if self.model:
            self.model.addMessage(initial_message_placeholder)

    def append_stream_chunk_to_model(self, chunk: str) -> None:
        if self.model:
            self.model.appendChunkToLastMessage(chunk)
            if self.list_view:
                v_scrollbar = self.list_view.verticalScrollBar()
                if v_scrollbar and v_scrollbar.value() >= v_scrollbar.maximum() - (v_scrollbar.pageStep() // 2):
                    self._scroll_to_bottom()


    def finalize_stream_in_model(self) -> None:
        if self.model:
            self.model.finalizeLastMessage()

    def load_history_into_model(self, history: List[ChatMessage]) -> None:
        if self.model:
            self.model.loadHistory(history)

    def clear_model_display(self) -> None:
        if self.model:
            self.model.clearMessages()

    def get_last_message_full_text(self) -> Optional[str]:
        if self.model and self.model.rowCount() > 0:
            last_msg = self.model.getMessage(self.model.rowCount() - 1)
            if last_msg:
                return last_msg.content
        return None

    @pyqtSlot(QPoint)
    def _show_context_menu(self, position: QPoint) -> None:
        if not self.list_view or not self.model: return

        index = self.list_view.indexAt(position)
        if not index.isValid(): return

        message_obj = self.model.data(index, ChatMessageRole)
        if not isinstance(message_obj, ChatMessage): return

        if message_obj.content and message_obj.content.strip() and message_obj.role not in ["system", "error"]:
            menu = QMenu(self.list_view)
            copy_action = menu.addAction("Copy Text")
            copy_action.triggered.connect(
                lambda checked=False, text=message_obj.content: self._copy_text_to_clipboard(text))
            menu.exec(self.list_view.viewport().mapToGlobal(position))

    def _copy_text_to_clipboard(self, text: str) -> None:
        try:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
                self.text_copied_to_clipboard.emit("Message text copied!", "#98c379")
            else:
                self.text_copied_to_clipboard.emit("Error: Clipboard not accessible.", "#e06c75")
        except Exception as e:
            logger.exception(f"Error copying text to clipboard: {e}")
            self.text_copied_to_clipboard.emit(f"Copy Error: {e}", "#e06c75")

    def _scroll_to_bottom(self) -> None:
        if self.list_view and self.model and self.model.rowCount() > 0:
            QTimer.singleShot(0, self.list_view.scrollToBottom)