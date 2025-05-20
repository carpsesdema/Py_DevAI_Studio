import logging
import os
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QSizePolicy, QFileDialog, QTextEdit, QLabel, QMessageBox
)
from PyQt6.QtGui import QFont, QIcon, QTextOption, QFontMetrics, QKeyEvent
from PyQt6.QtCore import Qt, pyqtSignal, QSize, pyqtSlot, QTimer

from utils import constants

logger = logging.getLogger(constants.APP_NAME)

try:
    from services.image_handler_service import ImageHandlerService  # Assuming this will be created

    IMAGE_SERVICE_AVAILABLE = True
except ImportError:
    ImageHandlerService = None
    IMAGE_SERVICE_AVAILABLE = False
    logger.warning("ChatInputBar: ImageHandlerService not found. Image attachment will be disabled.")

try:
    from .loading_indicator_widget import LoadingIndicatorWidget  # Assuming this will be created
except ImportError:
    LoadingIndicatorWidget = type("LoadingIndicatorWidget", (QLabel,),
                                  {"start": lambda self: None, "stop": lambda self: None,
                                   "setVisible": lambda self, v: None})
    logger.warning("ChatInputBar: LoadingIndicatorWidget not found, using placeholder.")


class MultilineTextEdit(QTextEdit):
    sendMessageOnEnter = pyqtSignal()
    MIN_LINES = 1
    MAX_LINES = 7
    LINE_PADDING = 8

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ChatInputMultilineTextEdit")
        self.setAcceptRichText(False)
        self.setWordWrapMode(QTextOption.WrapMode.WordWrap)

        font = QFont(constants.DEFAULT_FONT_FAMILY, constants.DEFAULT_FONT_SIZE)
        self.setFont(font)

        self._min_height = 30
        self._max_height = 200
        self._calculate_height_limits()
        self.textChanged.connect(self._update_height)
        self.setFixedHeight(self._min_height)

    def _calculate_height_limits(self) -> None:
        fm = QFontMetrics(self.font())
        line_height = fm.height()
        doc_margin = int(self.document().documentMargin())
        vertical_padding = self.LINE_PADDING + (doc_margin * 2)
        self._min_height = (line_height * self.MIN_LINES) + vertical_padding
        self._max_height = (line_height * self.MAX_LINES) + vertical_padding

    @pyqtSlot()
    def _update_height(self) -> None:
        vp_width = self.viewport().width()
        effective_width = vp_width if vp_width > 0 else self.width()
        if effective_width > 0:
            self.document().setTextWidth(effective_width)

        doc_height = self.document().size().height()
        doc_margin = int(self.document().documentMargin())
        vertical_padding = self.LINE_PADDING + (doc_margin * 2)
        target_height = int(doc_height + vertical_padding)
        clamped_height = max(self._min_height, min(target_height, self._max_height))

        if self.height() != clamped_height:
            self.setFixedHeight(clamped_height)
            self.updateGeometry()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()
        is_enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        is_shift_pressed = modifiers & Qt.KeyboardModifier.ShiftModifier

        if is_enter and not is_shift_pressed:
            self.sendMessageOnEnter.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class ChatInputBar(QWidget):
    sendMessageRequested = pyqtSignal(str, list)  # text, List[Dict[str, Any]] for image_data

    _INDICATOR_SIZE = QSize(22, 22)
    _BUTTON_ICON_SIZE = QSize(16, 16)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ChatInputBar")

        self._text_input: Optional[MultilineTextEdit] = None
        self._send_button: Optional[QPushButton] = None
        self._attach_button: Optional[QPushButton] = None
        self._loading_indicator: Optional[LoadingIndicatorWidget] = None

        self._attached_image_data_list: List[Dict[str, Any]] = []
        self._image_service: Optional[ImageHandlerService] = None
        if IMAGE_SERVICE_AVAILABLE and ImageHandlerService:
            self._image_service = ImageHandlerService()

        self._is_busy: bool = False
        self._is_enabled: bool = True

        self._init_ui()
        self._connect_signals()
        self._update_send_button_state()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        self._attach_button = QPushButton()
        self._attach_button.setObjectName("AttachImageButton")
        self._attach_button.setToolTip("Attach Image(s) (Max 5MB each, common formats)")
        attach_icon_path = os.path.join(constants.ASSETS_DIR, "attach_icon.svg")
        if os.path.exists(attach_icon_path):
            self._attach_button.setIcon(QIcon(attach_icon_path))
        else:
            self._attach_button.setText("+")
        self._attach_button.setIconSize(self._BUTTON_ICON_SIZE)
        self._attach_button.setFixedSize(QSize(28, 28))
        self._attach_button.setEnabled(self._image_service is not None)
        layout.addWidget(self._attach_button)

        self._text_input = MultilineTextEdit(self)
        layout.addWidget(self._text_input, 1)

        self._loading_indicator = LoadingIndicatorWidget(self)
        self._loading_indicator.setFixedSize(self._INDICATOR_SIZE)
        self._loading_indicator.setVisible(False)
        layout.addWidget(self._loading_indicator)

        self._send_button = QPushButton("Send")
        self._send_button.setObjectName("SendMessageButton")
        font = QFont(constants.DEFAULT_FONT_FAMILY, constants.DEFAULT_FONT_SIZE)
        self._send_button.setFont(font)
        self._send_button.setDefault(True)
        layout.addWidget(self._send_button)

        self.setLayout(layout)

    def _connect_signals(self) -> None:
        if self._text_input:
            self._text_input.sendMessageOnEnter.connect(self._trigger_send_message)
            self._text_input.textChanged.connect(self._update_send_button_state)
        if self._send_button:
            self._send_button.clicked.connect(self._trigger_send_message)
        if self._attach_button:
            self._attach_button.clicked.connect(self._handle_attach_action)

    @pyqtSlot()
    def _trigger_send_message(self) -> None:
        if not self._is_enabled or self._is_busy: return

        text_content = self._text_input.toPlainText().strip() if self._text_input else ""

        if not text_content and not self._attached_image_data_list:
            return

        self.sendMessageRequested.emit(text_content, list(self._attached_image_data_list))
        self.clear_input()

    @pyqtSlot()
    def _handle_attach_action(self) -> None:
        if not self._image_service:
            QMessageBox.warning(self, "Image Feature Unavailable", "The image processing service is not available.")
            return

        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach Images", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*)"
        )

        if file_paths:
            newly_attached_count = 0
            for fp in file_paths:
                if self._image_service:
                    processed_data = self._image_service.process_image_to_base64(fp)  # Assuming this method exists
                    if processed_data:
                        base64_str, mime_type = processed_data
                        self._attached_image_data_list.append({
                            "type": "image", "mime_type": mime_type, "data": base64_str, "original_path": fp
                        })
                        newly_attached_count += 1
                    else:
                        logger.warning(f"Failed to process image for attachment: {fp}")

            if newly_attached_count > 0:
                self._update_attachment_tooltip()
                self._update_send_button_state()

    def _update_attachment_tooltip(self) -> None:
        if self._attach_button:
            if self._attached_image_data_list:
                filenames = [os.path.basename(img_data.get("original_path", "image")) for img_data in
                             self._attached_image_data_list]
                tooltip = f"Attached ({len(filenames)}):\n" + "\n".join(f"- {name}" for name in filenames)
                self._attach_button.setToolTip(tooltip[:500] + "..." if len(tooltip) > 500 else tooltip)
            else:
                self._attach_button.setToolTip("Attach Image(s) (Max 5MB each, common formats)")

    @pyqtSlot()
    def _update_send_button_state(self) -> None:
        if self._send_button and self._text_input:
            has_text = bool(self._text_input.toPlainText().strip())
            has_attachments = bool(self._attached_image_data_list)
            can_send = self._is_enabled and not self._is_busy and (has_text or has_attachments)
            self._send_button.setEnabled(can_send)

    def handle_busy_state(self, is_busy: bool) -> None:
        self._is_busy = is_busy
        effective_enabled = self._is_enabled and not self._is_busy

        if self._text_input: self._text_input.setEnabled(effective_enabled)
        if self._attach_button: self._attach_button.setEnabled(effective_enabled and self._image_service is not None)
        if self._loading_indicator:
            self._loading_indicator.setVisible(is_busy)
            if is_busy:
                self._loading_indicator.start()
            else:
                self._loading_indicator.stop()
        self._update_send_button_state()

    def clear_input(self) -> None:
        if self._text_input: self._text_input.clear()
        self._attached_image_data_list.clear()
        self._update_attachment_tooltip()
        self._update_send_button_state()  # Will disable send button

    def set_focus_to_input(self) -> None:
        if self._text_input: self._text_input.setFocus()

    def set_enabled(self, enabled: bool) -> None:
        self._is_enabled = enabled
        self.handle_busy_state(self._is_busy)  # Re-evaluate based on new enabled state and current busy state