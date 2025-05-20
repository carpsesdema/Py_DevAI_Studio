import logging
import os
from typing import Optional

from PyQt6.QtWidgets import QLabel, QSizePolicy, QWidget
from PyQt6.QtGui import QMovie
from PyQt6.QtCore import QSize, Qt, QTimer

from utils import constants

logger = logging.getLogger(constants.APP_NAME)


class LoadingIndicatorWidget(QLabel):
    _DEFAULT_MIN_SIZE = QSize(16, 16)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("LoadingIndicatorLabelWidget")

        self._movie: Optional[QMovie] = None
        self._is_setup_done: bool = False

        self.setMinimumSize(self._DEFAULT_MIN_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(True)
        self.setVisible(False)

        QTimer.singleShot(0, self._initialize_movie)

    def _initialize_movie(self) -> None:
        if self._is_setup_done:
            return
        self._is_setup_done = True

        gif_path = os.path.join(constants.ASSETS_DIR, constants.LOADING_GIF_FILENAME)
        if not os.path.exists(gif_path):
            logger.error(
                f"LoadingIndicatorWidget: GIF asset '{constants.LOADING_GIF_FILENAME}' not found at {gif_path}.")
            self.setText("[!]")
            self.setStyleSheet("QLabel { color: red; font-weight: bold; }")
            return

        try:
            self._movie = QMovie(gif_path, parent=self)  # Ensure parent is set for QMovie
            if not self._movie.isValid():
                logger.error(f"LoadingIndicatorWidget: QMovie reported invalid GIF format for {gif_path}.")
                self._movie = None
                self.setText("[X]")
                self.setStyleSheet("QLabel { color: orange; font-weight: bold; }")
                return

            self.setMovie(self._movie)
            logger.info(f"LoadingIndicatorWidget: GIF '{constants.LOADING_GIF_FILENAME}' loaded successfully.")
        except Exception as e:
            logger.exception(f"LoadingIndicatorWidget: Critical failure during QMovie setup for {gif_path}: {e}")
            self._movie = None
            self.setText("[E]")
            self.setStyleSheet("QLabel { color: darkred; font-weight: bold; }")

    def start(self) -> None:
        if not self._movie or not self._movie.isValid():
            self.setVisible(False)
            return

        if self.size().isEmpty() or not self.size().isValid():
            logger.warning("LoadingIndicatorWidget: Label size is invalid or empty. Movie might not scale as expected.")

        # QMovie.setScaledSize is not needed when QLabel.setScaledContents(True) is used.
        # The QLabel will handle scaling the movie's current pixmap.

        if not self.isVisible():
            self.setVisible(True)

        if self._movie.state() != QMovie.MovieState.Running:
            self._movie.start()

        self.raise_()

    def stop(self) -> None:
        if self._movie and self._movie.state() == QMovie.MovieState.Running:
            self._movie.stop()

        if self.isVisible():
            self.setVisible(False)

    def setFixedSize(self, size: QSize) -> None:
        super().setFixedSize(size)
        # If movie is already loaded, and QLabel.setScaledContents is true,
        # the movie frames will scale automatically. No need to call movie.setScaledSize here.

    def minimumSizeHint(self) -> QSize:
        if self._movie and self._movie.isValid():
            # Return a reasonable default or the movie's original frame size if preferred
            # For a fixed size indicator, this might not be as critical.
            original_size = self._movie.currentPixmap().size()
            if not original_size.isEmpty():
                return original_size
        return self._DEFAULT_MIN_SIZE

    def sizeHint(self) -> QSize:
        return self.minimumSizeHint()