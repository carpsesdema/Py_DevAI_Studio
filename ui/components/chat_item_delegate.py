# ui/chat_item_delegate.py
import logging
import base64
import html
import hashlib
import os
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime

from PyQt6.QtWidgets import QStyledItemDelegate, QStyle, QApplication, QStyleOptionViewItem, QWidget
from PyQt6.QtGui import (
    QPainter, QColor, QFontMetrics, QTextDocument, QPixmap, QImage, QFont,
    QMovie, QPen, QTextOption  # Added QTextOption
)
from PyQt6.QtCore import (
    QModelIndex, QRect, QPoint, QSize, Qt, QObject, QByteArray,
    QPersistentModelIndex, pyqtSlot
)

from utils import constants  # For colors, fonts, asset paths
from core.models import ChatMessage  # From PyDevAI_Studio's core
from core.message_enums import MessageLoadingState  # From PyDevAI_Studio's core
from .chat_list_model import ChatMessageRole, LoadingStatusRole, MessageIdRole  # Roles from our model

try:
    import markdown

    MARKDOWN_AVAILABLE = True
except ImportError:
    markdown = None  # type: ignore
    MARKDOWN_AVAILABLE = False
    logging.warning("ChatItemDelegate: python-markdown library not found. Markdown rendering will be basic.")

logger = logging.getLogger(constants.APP_NAME)


class ChatItemDelegate(QStyledItemDelegate):
    # --- Configuration Constants (Derived from utils.constants or specific to delegate) ---
    BUBBLE_PADDING_V = 8
    BUBBLE_PADDING_H = 12
    BUBBLE_MARGIN_V = 5
    BUBBLE_MARGIN_H = 10  # Overall margin for the item
    BUBBLE_RADIUS = 10
    IMAGE_PADDING_INTERNAL = 5  # Padding between text and image, or image and image
    MAX_IMAGE_WIDTH_IN_BUBBLE = 280
    MAX_IMAGE_HEIGHT_IN_BUBBLE = 280
    MIN_BUBBLE_WIDTH_FOR_CONTENT = 60  # Min width for the content area inside bubble
    USER_BUBBLE_INDENT_FROM_RIGHT = 50  # How far user bubbles are from the right edge
    TIMESTAMP_PADDING_TOP = 4
    TIMESTAMP_HEIGHT = 16  # Approximate height for timestamp text
    BUBBLE_MAX_WIDTH_FACTOR = 0.78  # Bubble can take up to 78% of view width

    INDICATOR_SIZE = QSize(20, 20)  # Size of loading/completed icons
    INDICATOR_PADDING_X = 6  # Padding for indicator from bubble edge
    INDICATOR_PADDING_Y = 6

    # Role-based colors (fetched from constants)
    ROLE_COLORS = {
        "user": (QColor(constants.USER_BUBBLE_COLOR_HEX), QColor(constants.USER_TEXT_COLOR_HEX)),
        "assistant": (QColor(constants.ASSISTANT_BUBBLE_COLOR_HEX), QColor(constants.ASSISTANT_TEXT_COLOR_HEX)),
        "system": (QColor(constants.SYSTEM_BUBBLE_COLOR_HEX), QColor(constants.SYSTEM_TEXT_COLOR_HEX)),
        "error": (QColor(constants.ERROR_BUBBLE_COLOR_HEX), QColor(constants.ERROR_TEXT_COLOR_HEX)),
    }
    DEFAULT_AI_COLOR = ROLE_COLORS["assistant"]  # Fallback
    CODE_BG_COLOR = QColor(constants.CODE_BLOCK_BG_COLOR_HEX)
    BUBBLE_BORDER_COLOR = QColor(constants.BUBBLE_BORDER_COLOR_HEX)
    TIMESTAMP_TEXT_COLOR = QColor(constants.TIMESTAMP_COLOR_HEX)

    # --- End Configuration Constants ---

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        # Fonts (can be customized further via AppSettings if needed)
        self.ui_font = QFont(constants.DEFAULT_FONT_FAMILY, constants.DEFAULT_FONT_SIZE)
        self.code_font = QFont(constants.CODE_FONT_FAMILY, constants.CODE_FONT_SIZE)
        self.timestamp_font = QFont(constants.DEFAULT_FONT_FAMILY, constants.DEFAULT_FONT_SIZE - 2)  # Smaller

        self.ui_font_metrics = QFontMetrics(self.ui_font)
        self.timestamp_font_metrics = QFontMetrics(self.timestamp_font)

        # Caches
        self._text_doc_cache: Dict[Tuple[str, int, str, str], QTextDocument] = {}  # (msg_id, content_hash, width, role)
        self._image_pixmap_cache: Dict[str, QPixmap] = {}  # data_hash -> QPixmap

        # Loading/Completion Indicator Assets
        self._loading_movie_template: Optional[QMovie] = None
        self._completed_icon_pixmap: Optional[QPixmap] = None
        self._active_loading_movies: Dict[QPersistentModelIndex, QMovie] = {}  # Tracks active movies per index
        self._view_widget_ref: Optional[QWidget] = None  # Reference to the QListView for updates

        self._load_indicator_assets()
        self._bubble_stylesheet_content = self._load_bubble_stylesheet()
        logger.info("ChatItemDelegate initialized with enhanced features.")

    def _load_indicator_assets(self) -> None:
        loading_gif_path = os.path.join(constants.ASSETS_DIR, constants.LOADING_GIF_FILENAME)
        if os.path.exists(loading_gif_path):
            self._loading_movie_template = QMovie(loading_gif_path)
            if self._loading_movie_template.isValid():
                self._loading_movie_template.setScaledSize(self.INDICATOR_SIZE)
            else:
                self._loading_movie_template = None
                logger.error(f"Failed to load QMovie template from: {loading_gif_path}")
        else:
            logger.error(f"Loading GIF asset not found: {loading_gif_path}")

        completed_icon_path = os.path.join(constants.ASSETS_DIR, constants.COMPLETED_ICON_FILENAME)
        if os.path.exists(completed_icon_path):
            self._completed_icon_pixmap = QPixmap(completed_icon_path)
            if not self._completed_icon_pixmap.isNull():
                self._completed_icon_pixmap = self._completed_icon_pixmap.scaled(
                    self.INDICATOR_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
            else:
                self._completed_icon_pixmap = None
                logger.error(f"Failed to load QPixmap from: {completed_icon_path}")
        else:
            logger.error(f"Completion icon asset not found: {completed_icon_path}")

    def _load_bubble_stylesheet(self) -> str:
        try:
            # Assuming bubble_style.qss is in the same directory as this delegate file, or a known relative path
            # For PyDevAI_Studio, it's in ui/
            style_path = os.path.join(os.path.dirname(__file__), "bubble_style.qss")
            if os.path.exists(style_path):
                with open(style_path, "r", encoding="utf-8") as f_style:
                    logger.info(f"Loaded bubble_style.qss from: {style_path}")
                    return f_style.read()
            else:
                logger.warning(f"bubble_style.qss not found at {style_path}. Markdown rendering will be basic.")
        except Exception as e_style:
            logger.error(f"Error loading bubble_style.qss: {e_style}")

        # Fallback internal styles if bubble_style.qss fails or is minimal
        # This should be more comprehensive if bubble_style.qss is critical
        return f"""
            body {{ /* Base text color is set dynamically via HTML */ }}
            pre {{ background-color: {self.CODE_BG_COLOR.name()}; border: 1px solid #404040; border-radius: 4px; padding: 8px; margin: 6px 0; font-family: '{self.code_font.family()}'; font-size: {self.code_font.pointSize()}pt; color: {QColor(constants.CODE_BLOCK_TEXT_COLOR_HEX).name()}; white-space: pre-wrap; word-wrap: break-word; }}
            code {{ font-family: '{self.code_font.family()}'; background-color: {self.CODE_BG_COLOR.lighter(115).name()}; padding: 1px 4px; border-radius: 3px; font-size: {self.code_font.pointSize() - 1}pt; }}
            p {{ margin-bottom: 6px; }}
            ul, ol {{ margin-left: 20px; margin-bottom: 6px; }}
            li {{ margin-bottom: 3px; }}
        """

    def setView(self, view_widget: QWidget) -> None:
        """Stores a reference to the view for efficient updates during animation."""
        self._view_widget_ref = view_widget

    @pyqtSlot(int)  # frame_number, though not used, is part of QMovie's signal
    def _on_movie_frame_changed(self, frame_number: int) -> None:
        if not self._view_widget_ref or not self._active_loading_movies:
            return

        movie_sender = self.sender()
        if not isinstance(movie_sender, QMovie): return

        for p_idx, active_movie_instance in list(self._active_loading_movies.items()):  # Iterate copy
            if active_movie_instance == movie_sender:
                if p_idx.isValid() and self._view_widget_ref.model() and \
                        self._view_widget_ref.model().data(p_idx, LoadingStatusRole) == MessageLoadingState.LOADING:
                    self._view_widget_ref.update(p_idx)  # Request repaint of the specific item
                else:  # Stale entry or state changed, cleanup this movie instance
                    active_movie_instance.stop()
                    try:
                        active_movie_instance.frameChanged.disconnect(self._on_movie_frame_changed)
                    except TypeError:
                        pass  # Already disconnected
                    active_movie_instance.deleteLater()  # Schedule for deletion
                    del self._active_loading_movies[p_idx]
                break

    def clearCache(self) -> None:
        self._text_doc_cache.clear()
        self._image_pixmap_cache.clear()
        for p_idx, movie_instance in list(self._active_loading_movies.items()):  # Iterate copy
            movie_instance.stop()
            try:
                movie_instance.frameChanged.disconnect(self._on_movie_frame_changed)
            except TypeError:
                pass
            movie_instance.deleteLater()
        self._active_loading_movies.clear()
        logger.debug("ChatItemDelegate caches and active movies cleared.")

    # ui/chat_item_delegate.py (Part 2/2)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        message_data: Optional[ChatMessage] = index.data(ChatMessageRole)
        if not isinstance(message_data, ChatMessage):
            super().paint(painter, option, index)
            painter.restore();
            return

        loading_state: MessageLoadingState = index.data(LoadingStatusRole) or MessageLoadingState.IDLE
        is_user_role = message_data.role == "user"
        bubble_color, _ = self.ROLE_COLORS.get(message_data.role, self.DEFAULT_AI_COLOR)

        available_width = option.rect.width()
        # Calculate the size needed by the content INSIDE the bubble (text, images)
        content_dims_inside_bubble = self._calculate_content_size(message_data, available_width, is_user_role)

        # Calculate the actual bubble rectangle based on content size and margins
        bubble_rect = self._calculate_bubble_rect(option.rect, content_dims_inside_bubble, is_user_role)

        # Draw the bubble
        painter.setPen(QPen(self.BUBBLE_BORDER_COLOR, 0.5))
        painter.setBrush(bubble_color)
        painter.drawRoundedRect(bubble_rect, self.BUBBLE_RADIUS, self.BUBBLE_RADIUS)

        # Content drawing rectangle (inside bubble, respecting padding)
        content_draw_rect = bubble_rect.adjusted(self.BUBBLE_PADDING_H, self.BUBBLE_PADDING_V,
                                                 -self.BUBBLE_PADDING_H, -self.BUBBLE_PADDING_V)
        current_y_offset = content_draw_rect.top()

        # 1. Draw Text Content (if any)
        if message_data.text and message_data.text.strip():
            # Get prepared QTextDocument (handles Markdown, color, font, width constraint)
            text_doc_to_draw = self._get_prepared_text_document(message_data, content_draw_rect.width())

            painter.save()
            painter.translate(content_draw_rect.left(), current_y_offset)
            # Clip drawing to the document's actual height to prevent overflow
            clip_rect = QRect(0, 0, content_draw_rect.width(), int(text_doc_to_draw.size().height()))
            text_doc_to_draw.drawContents(painter, clip_rect)
            painter.restore()
            current_y_offset += int(text_doc_to_draw.size().height())

        # 2. Draw Image Content (if any)
        if message_data.has_images:
            if message_data.text and message_data.text.strip():  # Add padding if text was above
                current_y_offset += self.IMAGE_PADDING_INTERNAL

            for img_idx, img_data_dict in enumerate(message_data.image_data):
                img_pixmap = self._get_image_pixmap_from_data(img_data_dict)
                if img_pixmap and not img_pixmap.isNull():
                    if img_idx > 0: current_y_offset += self.IMAGE_PADDING_INTERNAL  # Padding between images

                    # Scale image to fit content width and max dimensions
                    img_target_width = min(img_pixmap.width(), content_draw_rect.width(),
                                           self.MAX_IMAGE_WIDTH_IN_BUBBLE)
                    scaled_img = img_pixmap.scaledToWidth(img_target_width, Qt.TransformationMode.SmoothTransformation)
                    if scaled_img.height() > self.MAX_IMAGE_HEIGHT_IN_BUBBLE:
                        scaled_img = scaled_img.scaledToHeight(self.MAX_IMAGE_HEIGHT_IN_BUBBLE,
                                                               Qt.TransformationMode.SmoothTransformation)

                    # Center image horizontally within the content_draw_rect
                    img_x_pos = content_draw_rect.left() + (content_draw_rect.width() - scaled_img.width()) // 2
                    painter.drawPixmap(img_x_pos, current_y_offset, scaled_img)
                    current_y_offset += scaled_img.height()

        # 3. Draw Loading/Completion Indicator for AI messages
        persistent_idx = QPersistentModelIndex(index)  # For map key
        if message_data.role == "assistant" and loading_state != MessageLoadingState.IDLE:
            # Position indicator at bottom-right of the bubble
            indicator_rect_x = bubble_rect.right() - self.INDICATOR_SIZE.width() - self.INDICATOR_PADDING_X
            indicator_rect_y = bubble_rect.bottom() - self.INDICATOR_SIZE.height() - self.INDICATOR_PADDING_Y
            final_indicator_rect = QRect(QPoint(indicator_rect_x, indicator_rect_y), self.INDICATOR_SIZE)

            if loading_state == MessageLoadingState.LOADING:
                active_movie = self._active_loading_movies.get(persistent_idx)
                if not active_movie and self._loading_movie_template:  # Create new movie instance for this item
                    active_movie = QMovie(self._loading_movie_template.fileName(), QByteArray(),
                                          self._view_widget_ref or self.parent())  # Parent it
                    if active_movie.isValid():
                        active_movie.setScaledSize(self.INDICATOR_SIZE)
                        active_movie.frameChanged.connect(self._on_movie_frame_changed)
                        self._active_loading_movies[persistent_idx] = active_movie
                        active_movie.start()
                    else:
                        active_movie = None  # Failed to create
                if active_movie and active_movie.isValid():
                    painter.drawPixmap(final_indicator_rect, active_movie.currentPixmap())

            elif loading_state == MessageLoadingState.COMPLETED:
                if persistent_idx in self._active_loading_movies:  # Cleanup movie if it was loading before
                    old_movie = self._active_loading_movies.pop(persistent_idx)
                    old_movie.stop();
                    old_movie.frameChanged.disconnect(self._on_movie_frame_changed);
                    old_movie.deleteLater()
                if self._completed_icon_pixmap:
                    painter.drawPixmap(final_indicator_rect, self._completed_icon_pixmap)
            # No specific icon for ERROR state yet, but could be added. IDLE means no indicator.
            # If state becomes IDLE or ERROR after loading, cleanup movie:
            elif loading_state in [MessageLoadingState.IDLE, MessageLoadingState.ERROR]:
                if persistent_idx in self._active_loading_movies:
                    old_movie = self._active_loading_movies.pop(persistent_idx)
                    old_movie.stop();
                    old_movie.frameChanged.disconnect(self._on_movie_frame_changed);
                    old_movie.deleteLater()

        # 4. Draw Timestamp (below the bubble)
        timestamp_str = self._format_timestamp_display(message_data.timestamp)
        if timestamp_str:
            painter.setFont(self.timestamp_font)
            painter.setPen(self.TIMESTAMP_TEXT_COLOR)
            ts_width = self.timestamp_font_metrics.horizontalAdvance(timestamp_str)
            # Align timestamp to the right of the bubble
            ts_x = bubble_rect.right() - ts_width
            ts_y = bubble_rect.bottom() + self.TIMESTAMP_PADDING_TOP + self.timestamp_font_metrics.ascent()
            # Ensure timestamp is within item bounds
            if ts_y < option.rect.bottom() - self.BUBBLE_MARGIN_V:
                painter.drawText(QPoint(ts_x, ts_y), timestamp_str)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        message_data: Optional[ChatMessage] = index.data(ChatMessageRole)
        if not isinstance(message_data, ChatMessage):
            return super().sizeHint(option, index)

        is_user_role = message_data.role == "user"
        available_width = option.rect.width()

        # Calculate dimensions of content *inside* the bubble (text + images)
        content_dims_inside_bubble = self._calculate_content_size(message_data, available_width, is_user_role)

        # Total height of the item = bubble content height + top/bottom bubble margins + timestamp height
        total_height = content_dims_inside_bubble.height()  # This already includes BUBBLE_PADDING_V
        if self._format_timestamp_display(message_data.timestamp):
            total_height += self.TIMESTAMP_PADDING_TOP + self.TIMESTAMP_HEIGHT

        final_item_height = total_height + (2 * self.BUBBLE_MARGIN_V)

        # Ensure a minimum height for very short messages
        min_height_one_line = self.ui_font_metrics.height() + (2 * self.BUBBLE_PADDING_V) + \
                              (self.TIMESTAMP_PADDING_TOP + self.TIMESTAMP_HEIGHT if message_data.timestamp else 0) + \
                              (2 * self.BUBBLE_MARGIN_V)

        return QSize(available_width, max(final_item_height, min_height_one_line))

    def _calculate_content_size(self, message: ChatMessage, available_item_width: int, is_user: bool) -> QSize:
        """Calculates the QSize needed for the content *within* the bubble, including internal padding."""
        current_content_height = 0
        max_content_width_used = 0  # Max width used by text or an image

        # Determine max width for the bubble itself
        max_bubble_width_allowed = int(available_item_width * self.BUBBLE_MAX_WIDTH_FACTOR)
        if is_user:  # User bubbles are indented from right
            max_bubble_width_allowed = min(max_bubble_width_allowed, available_item_width - (
                        2 * self.BUBBLE_MARGIN_H) - self.USER_BUBBLE_INDENT_FROM_RIGHT)

        # Ensure bubble width is at least a minimum, plus its own horizontal padding
        max_bubble_width_allowed = max(max_bubble_width_allowed,
                                       self.MIN_BUBBLE_WIDTH_FOR_CONTENT + (2 * self.BUBBLE_PADDING_H))

        # Max width available for content *inside* the bubble (text, images)
        inner_content_width_limit = max(1, max_bubble_width_allowed - (2 * self.BUBBLE_PADDING_H))

        # 1. Calculate Text Height
        if message.text and message.text.strip():
            text_doc = self._get_prepared_text_document(message, inner_content_width_limit)
            # Set width constraint for height calculation
            text_doc.setTextWidth(inner_content_width_limit)
            text_render_height = int(text_doc.size().height())

            # For width, check ideal width without constraint first
            text_doc.setTextWidth(-1)  # Remove constraint
            ideal_text_width = int(text_doc.size().width())
            actual_text_render_width = min(ideal_text_width, inner_content_width_limit)

            current_content_height += text_render_height
            max_content_width_used = max(max_content_width_used, actual_text_render_width)

        # 2. Calculate Image Heights & Max Width
        if message.has_images:
            if message.text and message.text.strip() and current_content_height > 0:  # If text above, add padding
                current_content_height += self.IMAGE_PADDING_INTERNAL

            img_count_in_bubble = 0
            for img_data_dict in message.image_data:
                pixmap = self._get_image_pixmap_from_data(img_data_dict)
                if pixmap and not pixmap.isNull():
                    if img_count_in_bubble > 0: current_content_height += self.IMAGE_PADDING_INTERNAL

                    img_target_width = min(pixmap.width(), inner_content_width_limit, self.MAX_IMAGE_WIDTH_IN_BUBBLE)
                    scaled_img = pixmap.scaledToWidth(img_target_width, Qt.TransformationMode.SmoothTransformation)
                    if scaled_img.height() > self.MAX_IMAGE_HEIGHT_IN_BUBBLE:
                        scaled_img = scaled_img.scaledToHeight(self.MAX_IMAGE_HEIGHT_IN_BUBBLE,
                                                               Qt.TransformationMode.SmoothTransformation)

                    current_content_height += scaled_img.height()
                    max_content_width_used = max(max_content_width_used, scaled_img.width())
                    img_count_in_bubble += 1
                else:  # Placeholder for failed image
                    if img_count_in_bubble > 0: current_content_height += self.IMAGE_PADDING_INTERNAL
                    current_content_height += self.ui_font_metrics.height()  # Approx height of an error text line
                    max_content_width_used = max(max_content_width_used,
                                                 self.ui_font_metrics.horizontalAdvance("[Image Error]"))
                    img_count_in_bubble += 1

        # Final dimensions for the content area itself (before bubble padding is added back for bubble rect)
        final_bubble_internal_content_width = max(self.MIN_BUBBLE_WIDTH_FOR_CONTENT, max_content_width_used)
        final_bubble_internal_content_height = current_content_height

        # Return size including bubble's own internal padding
        return QSize(final_bubble_internal_content_width + (2 * self.BUBBLE_PADDING_H),
                     final_bubble_internal_content_height + (2 * self.BUBBLE_PADDING_V))

    def _calculate_bubble_rect(self, item_option_rect: QRect, content_dims_with_padding: QSize, is_user: bool) -> QRect:
        """Calculates the QRect for the chat bubble itself."""
        bubble_w = content_dims_with_padding.width()
        bubble_h = content_dims_with_padding.height()

        bubble_y_pos = item_option_rect.top() + self.BUBBLE_MARGIN_V
        bubble_x_pos: int
        if is_user:
            bubble_x_pos = item_option_rect.right() - self.BUBBLE_MARGIN_H - bubble_w
            # Ensure user bubble doesn't go too far left if content is very narrow
            min_x_for_user_bubble = item_option_rect.left() + self.BUBBLE_MARGIN_H + self.USER_BUBBLE_INDENT_FROM_RIGHT
            bubble_x_pos = max(bubble_x_pos, min_x_for_user_bubble)
        else:  # AI/System/Error
            bubble_x_pos = item_option_rect.left() + self.BUBBLE_MARGIN_H

        return QRect(bubble_x_pos, bubble_y_pos, bubble_w, bubble_h)

    def _get_prepared_text_document(self, message: ChatMessage, width_constraint: int) -> QTextDocument:
        text_content = message.text if message.text and message.text.strip() else ""
        # Use a hash of the content for caching, plus width and role for styling differences
        content_hash = hashlib.sha1(text_content.encode('utf-8')).hexdigest()[:12]
        # Message ID is important for streaming updates; a new chunk changes content_hash
        cache_key = (message.id, content_hash, width_constraint, message.role)

        cached_doc = self._text_doc_cache.get(cache_key)
        if cached_doc:
            # Ensure text width is still correct if constraint changed slightly
            if abs(cached_doc.textWidth() - max(1, width_constraint)) > 2:  # Tolerance of 2px
                cached_doc.setTextWidth(max(1, width_constraint))
            return cached_doc

        doc = QTextDocument()
        doc.setDefaultFont(self.ui_font)  # Base font for the document
        doc.setDocumentMargin(0)  # Padding is handled by bubble

        _, text_color = self.ROLE_COLORS.get(message.role, self.DEFAULT_AI_COLOR)

        # Convert text to HTML (Markdown or plain escaped)
        html_for_doc = self._convert_text_to_html(text_content, text_color)

        # Apply the QSS stylesheet for Markdown elements
        doc.setDefaultStyleSheet(self._bubble_stylesheet_content)
        doc.setHtml(html_for_doc)
        doc.setTextWidth(max(1, width_constraint))  # Set width for layout calculation

        # Cache eviction
        if len(self._text_doc_cache) > 150:  # Keep cache size manageable
            try:
                self._text_doc_cache.pop(next(iter(self._text_doc_cache)))  # Remove an old item
            except StopIteration:
                pass

        self._text_doc_cache[cache_key] = doc
        return doc

    def _convert_text_to_html(self, text: str, base_text_color: QColor) -> str:
        if not text: return ""

        # Markdown library handles its own HTML escaping for content it processes.
        # For plain text fallback, we must escape.
        if MARKDOWN_AVAILABLE and markdown:
            try:
                md_extensions = [
                    'fenced_code',  # For ```code``` blocks
                    'nl2br',  # Newlines to <br>
                    'tables',  # Markdown tables
                    'sane_lists',  # More predictable list behavior
                    'extra'  # Includes abbreviations, def lists, footnotes, etc.
                ]
                html_content_from_md = markdown.markdown(text, extensions=md_extensions)
            except Exception as e_md:
                logger.warning(f"Markdown conversion failed: {e_md}. Using basic HTML escaping.")
                html_content_from_md = html.escape(text).replace('\n', '<br/>')
        else:
            html_content_from_md = html.escape(text).replace('\n', '<br/>')

        # Wrap in a body tag with the base text color. Stylesheet handles further details.
        # The delegate sets the default font on the QTextDocument.
        return f"""<body style="color: {base_text_color.name()};">{html_content_from_md}</body>"""

    def _get_image_pixmap_from_data(self, image_data_dict: Dict[str, Any]) -> Optional[QPixmap]:
        base64_str = image_data_dict.get("data")
        if not base64_str or not isinstance(base64_str, str): return None

        # Use original_path if available for cache key, otherwise hash of data
        cache_key_source = image_data_dict.get("original_path", base64_str[:64])  # Truncate for safety if using data
        data_hash = hashlib.sha1(cache_key_source.encode()).hexdigest()[:16]

        if data_hash in self._image_pixmap_cache:
            return self._image_pixmap_cache[data_hash]

        try:
            missing_padding = len(base64_str) % 4
            if missing_padding: base64_str += '=' * (4 - missing_padding)
            image_bytes = base64.b64decode(base64_str)
            q_image = QImage()
            if q_image.loadFromData(image_bytes):
                pixmap = QPixmap.fromImage(q_image)
                if not pixmap.isNull():
                    if len(self._image_pixmap_cache) > 30:  # Cache eviction
                        try:
                            self._image_pixmap_cache.pop(next(iter(self._image_pixmap_cache)))
                        except StopIteration:
                            pass
                    self._image_pixmap_cache[data_hash] = pixmap
                    return pixmap
            logger.warning(f"Failed to load QImage from base64 data for source: {cache_key_source[:50]}...")
        except Exception as e_img:
            logger.error(f"Error decoding/loading image from base64 (source: {cache_key_source[:50]}...): {e_img}")
        return None

    def _format_timestamp_display(self, iso_timestamp_str: Optional[str]) -> Optional[str]:
        if not iso_timestamp_str: return None
        try:
            dt_obj = datetime.fromisoformat(iso_timestamp_str)
            return dt_obj.strftime("%H:%M")  # HH:MM format
        except (ValueError, TypeError):
            return None