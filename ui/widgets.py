import logging
import os

# --- PyQt6 Imports ---
from PyQt6.QtGui import (
    QIcon
)

# --- Local Imports ---
from utils.constants import ASSETS_PATH  # Use constants for paths

logger = logging.getLogger(__name__)


# --- Helper to load icons ---
def load_icon(filename: str) -> QIcon:
    """Loads an icon from the assets directory."""
    path = os.path.join(ASSETS_PATH, filename)
    if not os.path.exists(path):
        logger.warning(f"Icon not found: {path}")
        return QIcon()  # Return empty icon
    icon = QIcon(path)
    if icon.isNull():
        logger.warning(f"Icon loaded but is null: {path}")
    return icon


# --- Icons loaded for external import (e.g., by dialogs.py, left_panel.py) ---
COPY_ICON = load_icon("copy_icon.svg")
CHECK_ICON = load_icon("checkmark_icon.svg")
# ATTACH_ICON = load_icon("attach_icon.svg") # Loaded directly in ChatInputBar now

# --- ChatBubbleWidget Class REMOVED ---
# class ChatBubbleWidget(QWidget):
#    ... (Implementation removed) ...

# Add other custom widgets here if needed in the future
