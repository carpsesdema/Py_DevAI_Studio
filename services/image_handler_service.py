import logging
import os
import base64
from io import BytesIO
from typing import Optional, Tuple, Union

from PyQt6.QtGui import QImage, QPixmap, QImageReader
from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, Qt

from utils import constants

logger = logging.getLogger(constants.APP_NAME)

try:
    from PIL import Image, UnidentifiedImageError, ImageOps

    PIL_AVAILABLE = True
except ImportError:
    Image = None
    UnidentifiedImageError = None
    ImageOps = None
    PIL_AVAILABLE = False
    logger.warning(
        "ImageHandlerService: Pillow (PIL) library not found. Image processing capabilities will be limited or unavailable.")


class ImageHandlerService:
    MAX_IMAGE_FILE_SIZE_MB = 5
    MAX_IMAGE_DIMENSION = 1024  # Max width or height for LLM, can be adjusted
    DEFAULT_OUTPUT_FORMAT = "WEBP"  # WEBP is good for quality/size, or use PNG/JPEG
    DEFAULT_QUALITY = 85  # For JPEG/WEBP

    def __init__(self):
        if not PIL_AVAILABLE and Image is None:  # Double check due to conditional import
            logger.error("Pillow (PIL) is essential for ImageHandlerService. Service will be non-functional.")
        logger.info(f"ImageHandlerService initialized. PIL available: {PIL_AVAILABLE}")

    def _get_mime_type(self, image_format: str) -> str:
        normalized_format = image_format.upper()
        if normalized_format == "JPEG":
            return "image/jpeg"
        elif normalized_format == "PNG":
            return "image/png"
        elif normalized_format == "GIF":
            return "image/gif"
        elif normalized_format == "BMP":
            return "image/bmp"
        elif normalized_format == "WEBP":
            return "image/webp"
        else:
            logger.warning(f"Unknown image format '{image_format}', defaulting MIME type to application/octet-stream.")
            return "application/octet-stream"  # Fallback

    def process_image_to_base64(self, file_path: str) -> Optional[Tuple[str, str]]:
        if not os.path.exists(file_path):
            logger.error(f"Image file not found: {file_path}")
            return None

        try:
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if file_size_mb > self.MAX_IMAGE_FILE_SIZE_MB:
                logger.warning(
                    f"Image file '{os.path.basename(file_path)}' exceeds max size ({file_size_mb:.2f}MB > {self.MAX_IMAGE_FILE_SIZE_MB}MB). Skipping.")
                return None

            if PIL_AVAILABLE and Image and ImageOps:
                try:
                    with Image.open(file_path) as img:
                        original_format = img.format or self.DEFAULT_OUTPUT_FORMAT  # Keep original if good, else convert

                        # Ensure image is in RGB or RGBA for consistent processing
                        if img.mode not in ['RGB', 'RGBA']:
                            img = img.convert('RGBA') if 'A' in img.mode or original_format == 'PNG' else img.convert(
                                'RGB')

                        # Resize if necessary
                        if img.width > self.MAX_IMAGE_DIMENSION or img.height > self.MAX_IMAGE_DIMENSION:
                            img.thumbnail((self.MAX_IMAGE_DIMENSION, self.MAX_IMAGE_DIMENSION),
                                          Image.Resampling.LANCZOS)

                        # Fix orientation based on EXIF data if present
                        img = ImageOps.exif_transpose(img)

                        output_buffer = BytesIO()
                        save_format = self.DEFAULT_OUTPUT_FORMAT
                        if original_format in ["JPEG", "PNG", "WEBP", "BMP"]:  # Prefer original if suitable
                            save_format = original_format

                        if save_format == "JPEG":
                            # Ensure RGB for JPEG
                            if img.mode == 'RGBA': img = img.convert('RGB')
                            img.save(output_buffer, format="JPEG", quality=self.DEFAULT_QUALITY, optimize=True)
                        elif save_format == "PNG":
                            img.save(output_buffer, format="PNG", optimize=True)
                        elif save_format == "WEBP":
                            img.save(output_buffer, format="WEBP", quality=self.DEFAULT_QUALITY, lossless=False)
                        else:  # Fallback to PNG for other types or if default output is not JPEG/PNG/WEBP
                            img.save(output_buffer, format="PNG")
                            save_format = "PNG"

                        image_bytes = output_buffer.getvalue()
                        base64_str = base64.b64encode(image_bytes).decode('utf-8')
                        mime_type = self._get_mime_type(save_format)
                        logger.info(
                            f"Processed image '{os.path.basename(file_path)}' to {save_format} ({len(base64_str)} chars b64).")
                        return base64_str, mime_type
                except UnidentifiedImageError:
                    logger.warning(f"Pillow could not identify image file: {file_path}. Trying Qt.")
                except Exception as e_pil:
                    logger.error(f"Error processing image with Pillow: {file_path} - {e_pil}")
                    # Fall through to Qt method if PIL fails for some reason

            # Fallback or primary method using Qt if PIL is not available or failed
            q_image_reader = QImageReader(file_path)
            if not q_image_reader.canRead():
                logger.error(
                    f"QImageReader cannot read image file: {file_path}. Format: {q_image_reader.format().data().decode()}")
                return None

            q_image = q_image_reader.read()
            if q_image.isNull():
                logger.error(
                    f"Failed to load image with QImageReader: {file_path}. Error: {q_image_reader.errorString()}")
                return None

            original_qt_format_bytes = q_image_reader.format()  # QByteArray
            original_qt_format_str = original_qt_format_bytes.data().decode().upper() if original_qt_format_bytes else "PNG"

            if q_image.width() > self.MAX_IMAGE_DIMENSION or q_image.height() > self.MAX_IMAGE_DIMENSION:
                q_image = q_image.scaled(self.MAX_IMAGE_DIMENSION, self.MAX_IMAGE_DIMENSION,
                                         Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)

            # Determine save format for Qt
            qt_save_format = "PNG"  # Default safe format
            if original_qt_format_str in ["JPG", "JPEG"]:
                qt_save_format = "JPG"
            elif original_qt_format_str == "WEBP":
                qt_save_format = "WEBP"

            success = q_image.save(buffer, format=qt_save_format,
                                   quality=self.DEFAULT_QUALITY if qt_save_format != "PNG" else -1)
            buffer.close()

            if not success:
                logger.error(f"Failed to save QImage to buffer for: {file_path}")
                return None

            base64_str = base64.b64encode(byte_array.data()).decode('utf-8')
            mime_type = self._get_mime_type(qt_save_format)
            logger.info(
                f"Processed image '{os.path.basename(file_path)}' with Qt to {qt_save_format} ({len(base64_str)} chars b64).")
            return base64_str, mime_type

        except Exception as e:
            logger.exception(f"Unexpected error processing image {file_path}: {e}")
            return None

    def get_image_dimensions(self, file_path: str) -> Optional[Tuple[int, int]]:
        if not os.path.exists(file_path): return None
        try:
            if PIL_AVAILABLE and Image:
                with Image.open(file_path) as img:
                    return img.size
            else:  # Fallback to Qt
                q_image = QImage(file_path)
                if not q_image.isNull():
                    return q_image.width(), q_image.height()
        except Exception as e:
            logger.error(f"Could not get dimensions for image {file_path}: {e}")
        return None