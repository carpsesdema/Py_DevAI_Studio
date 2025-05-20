# services/file_handler_service.py
import os
import logging
from typing import Tuple, Optional

# --- Dependency Imports ---
try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PyPDF2 = None
    PYPDF2_AVAILABLE = False
    logging.warning("FileHandlerService: PyPDF2 library not found. PDF handling will be unavailable. Install with: pip install pypdf2")

try:
    import docx # From python-docx library
    DOCX_AVAILABLE = True
except ImportError:
    docx = None
    DOCX_AVAILABLE = False
    logging.warning("FileHandlerService: python-docx library not found. DOCX handling will be unavailable. Install with: pip install python-docx")

# --- Local Imports ---
from utils import constants # For RAG_MAX_FILE_SIZE_MB

logger = logging.getLogger(constants.APP_NAME) # Use PyDevAI_Studio's app name for logger

class FileHandlerService:
    """Provides methods to read and extract text content from various file types."""

    def __init__(self):
        logger.info("FileHandlerService initialized.")
        if not PYPDF2_AVAILABLE:
            logger.warning("PDF handling will be unavailable due to missing PyPDF2.")
        if not DOCX_AVAILABLE:
            logger.warning("DOCX handling will be unavailable due to missing python-docx.")

    def read_file_content(self, file_path: str) -> Tuple[Optional[str], str, Optional[str]]:
        """
        Safely reads file content, identifies type (text, pdf, docx, binary, error),
        and extracts text from supported document types.

        Args:
            file_path: The absolute path to the file.

        Returns:
            A tuple containing:
            - content (Optional[str]): The extracted text content, or None on error/binary.
            - file_type (str): "text", "pdf", "docx", "binary", or "error".
            - error_msg (Optional[str]): An error message if file_type is "error", otherwise None.
        """
        if not os.path.exists(file_path):
            err_msg = "File not found"
            logger.warning(f"{err_msg}: {file_path}")
            return None, "error", err_msg
        if not os.path.isfile(file_path):
            err_msg = "Path is not a file"
            logger.warning(f"{err_msg}: {file_path}")
            return None, "error", err_msg

        display_name = os.path.basename(file_path)
        file_ext_lower = os.path.splitext(file_path)[1].lower()

        # --- File Size Check ---
        try:
            file_size = os.path.getsize(file_path)
            # Use RAG_MAX_FILE_SIZE_MB from PyDevAI_Studio's constants
            max_size_mb = getattr(constants, 'RAG_MAX_FILE_SIZE_MB', 50)
            max_size_bytes = max_size_mb * 1024 * 1024
            if file_size > max_size_bytes:
                err_msg = f"File exceeds max size ({max_size_mb}MB)"
                logger.warning(f"{err_msg}: '{display_name}' ({file_size / (1024*1024):.2f}MB)")
                return None, "error", err_msg
            if file_size == 0:
                logger.warning(f"File is empty: '{display_name}'")
                return None, "error", "File is empty"
        except OSError as e:
            err_msg = f"OS Error accessing file (size check): {e}"
            logger.error(f"Error getting size for '{display_name}': {e}")
            return None, "error", err_msg

        # --- PDF Handling ---
        if file_ext_lower == '.pdf':
            if not PYPDF2_AVAILABLE:
                logger.error(f"Cannot read PDF '{display_name}': PyPDF2 library not installed.")
                return None, "error", "PyPDF2 not installed"
            try:
                content_list = []
                with open(file_path, 'rb') as pdf_file:
                    reader = PyPDF2.PdfReader(pdf_file)
                    num_pages = len(reader.pages)
                    logger.info(f"Reading {num_pages} pages from PDF: '{display_name}'")
                    for page_num in range(num_pages):
                        try:
                            page_text = reader.pages[page_num].extract_text()
                            if page_text: # Ensure text was actually extracted
                                content_list.append(page_text)
                        except Exception as e_page:
                            logger.warning(f"Error extracting text from page {page_num+1} of '{display_name}': {e_page}")
                pdf_content = "\n\n--- Page Break ---\n\n".join(content_list).strip()
                if not pdf_content:
                    logger.warning(f"No text extracted from PDF: '{display_name}'")
                    return None, "error", "No text extracted from PDF"
                logger.info(f"Successfully extracted text from PDF: '{display_name}' (Length: {len(pdf_content)})")
                return pdf_content, "pdf", None # file_type is "pdf"
            except Exception as e_pdf:
                logger.exception(f"Error reading PDF '{display_name}': {e_pdf}")
                return None, "error", f"PDF Read Error: {e_pdf}"

        # --- DOCX Handling ---
        elif file_ext_lower == '.docx':
            if not DOCX_AVAILABLE:
                logger.error(f"Cannot read DOCX '{display_name}': python-docx library not installed.")
                return None, "error", "python-docx not installed"
            try:
                logger.info(f"Reading DOCX file: '{display_name}'")
                document = docx.Document(file_path)
                content_list = [p.text for p in document.paragraphs if p.text and p.text.strip()]
                docx_content = "\n\n".join(content_list).strip() # Join paragraphs with double newline
                if not docx_content:
                    logger.warning(f"No text extracted from DOCX: '{display_name}'")
                    return None, "error", "No text extracted from DOCX"
                logger.info(f"Successfully extracted text from DOCX: '{display_name}' (Length: {len(docx_content)})")
                return docx_content, "docx", None # file_type is "docx"
            except Exception as e_docx:
                logger.exception(f"Error reading DOCX '{display_name}': {e_docx}")
                return None, "error", f"DOCX Read Error: {e_docx}"

        # --- Generic Text Reading (for other allowed extensions) ---
        elif file_ext_lower in constants.ALLOWED_TEXT_EXTENSIONS:
            try:
                with open(file_path, "r", encoding="utf-8", errors='strict') as f:
                    content = f.read()
                # Basic check for null bytes to guess if binary, even for known text types
                if '\x00' in content[:1024]: # Check first 1KB
                    logger.warning(f"File '{display_name}' (ext: {file_ext_lower}) likely binary despite extension (null bytes found).")
                    return None, "binary", "Contains null bytes"
                return content, "text", None
            except UnicodeDecodeError:
                logger.warning(f"UTF-8 decode failed for '{display_name}'. Trying latin-1...")
                try:
                    with open(file_path, "r", encoding="latin-1") as f:
                        content = f.read()
                    if '\x00' in content[:1024]:
                        logger.warning(f"File '{display_name}' (read as latin-1) likely binary (null bytes found).")
                        return None, "binary", "Contains null bytes (latin-1)"
                    logger.info(f"Successfully read '{display_name}' using latin-1 encoding.")
                    return content, "text", None
                except Exception as e_fallback:
                    err_msg = f"Fallback read (latin-1) failed: {e_fallback}"
                    logger.warning(f"Failed to read '{display_name}' with fallback encoding. Error: {err_msg}")
                    return None, "error", err_msg
            except FileNotFoundError: # Should have been caught by os.path.exists, but defensive
                logger.error(f"File not found during read attempt: '{display_name}'")
                return None, "error", "File not found"
            except OSError as e_os:
                err_msg = f"OS Error reading text file: {e_os}"
                logger.error(f"OS error reading '{display_name}': {e_os}")
                return None, "error", err_msg
            except Exception as e_gen:
                err_msg = f"Unexpected error reading text file: {e_gen}"
                logger.exception(f"Unexpected read error for '{display_name}': {e_gen}")
                return None, "error", err_msg
        else:
            # File extension not explicitly handled or in allowed text extensions
            logger.info(f"File extension '{file_ext_lower}' for '{display_name}' not in primary handlers or allowed text list. Treating as binary/unsupported.")
            # Could try a speculative utf-8 read here too, or just mark as binary
            return None, "binary", "Unsupported file extension for text extraction"