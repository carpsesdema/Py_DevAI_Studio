# services/chunking_service.py
import logging
import os
import bisect # For efficient line number lookup
from typing import List, Dict, Any, Optional, Union

from utils import constants
from core.app_settings import AppSettings

# --- LangChain imports ---
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter, PythonCodeTextSplitter
    LANGCHAIN_SPLITTERS_AVAILABLE = True
except ImportError:
    RecursiveCharacterTextSplitter = None # type: ignore
    PythonCodeTextSplitter = None # type: ignore
    LANGCHAIN_SPLITTERS_AVAILABLE = False
    logging.critical("ChunkingService: langchain-text-splitters not found. Chunking will be basic or fail. Install with: pip install langchain-text-splitters")

# --- CodeAnalysisService Import ---
try:
    from .code_analysis_service import CodeAnalysisService
    CODE_ANALYSIS_SERVICE_AVAILABLE = True
except ImportError:
    CodeAnalysisService = None # type: ignore
    CODE_ANALYSIS_SERVICE_AVAILABLE = False
    logging.error("ChunkingService: CodeAnalysisService not found. Python code entity extraction will be disabled.")


logger = logging.getLogger(constants.APP_NAME)

class ChunkingService:
    """
    Handles chunking of documents using LangChain splitters.
    Integrates CodeAnalysisService to associate code entities (functions, classes)
    with chunks for Python files.
    """

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.chunk_size = self.settings.get("rag_chunk_size", constants.DEFAULT_RAG_CHUNK_SIZE)
        self.chunk_overlap = self.settings.get("rag_chunk_overlap", constants.DEFAULT_RAG_CHUNK_OVERLAP)

        self.recursive_splitter: Optional[RecursiveCharacterTextSplitter] = None
        self.python_splitter: Optional[PythonCodeTextSplitter] = None
        self.code_analysis_service: Optional[CodeAnalysisService] = None

        if not LANGCHAIN_SPLITTERS_AVAILABLE:
            logger.error("Langchain text splitters are not available. ChunkingService will not function correctly.")
            # Service is essentially non-functional without splitters
            return

        try:
            self.recursive_splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                length_function=len,
                is_separator_regex=False, # Common setting
            )
            self.python_splitter = PythonCodeTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap
            )
            logger.info(
                f"ChunkingService initialized with chunk_size={self.chunk_size}, overlap={self.chunk_overlap} using Langchain splitters.")
        except Exception as e:
            logger.exception(f"Failed to initialize Langchain splitters: {e}")
            self.recursive_splitter = None
            self.python_splitter = None
            # Fallback to recursive if python splitter fails, but main check is LANGCHAIN_SPLITTERS_AVAILABLE

        if CODE_ANALYSIS_SERVICE_AVAILABLE and CodeAnalysisService is not None:
            try:
                self.code_analysis_service = CodeAnalysisService()
                logger.info("ChunkingService: CodeAnalysisService instantiated successfully.")
            except Exception as e:
                logger.error(f"ChunkingService: Failed to instantiate CodeAnalysisService: {e}")
                self.code_analysis_service = None
        else:
            logger.warning("ChunkingService: CodeAnalysisService is not available. Python entity association will be skipped.")


    def _get_line_start_indices(self, text: str) -> List[int]:
        """Calculates the starting character index of each line."""
        indices = [0] # Line 1 starts at index 0
        current_pos = 0
        while True:
            next_newline = text.find('\n', current_pos)
            if next_newline == -1:
                break
            indices.append(next_newline + 1)
            current_pos = next_newline + 1
        return indices

    def _get_line_number(self, char_index: int, line_start_indices: List[int]) -> int:
        """Finds the 1-based line number for a given character index."""
        line_num_0_based = bisect.bisect_right(line_start_indices, char_index) - 1
        return max(1, line_num_0_based + 1) # Ensure minimum line number is 1

    def chunk_document(self, content: str, source_id: str, file_ext: str) -> List[Dict[str, Any]]:
        """
        Chunks a document and associates code entities for Python files.

        Args:
            content: The text content of the document.
            source_id: The original identifier (e.g., file path) of the document.
            file_ext: The lowercased file extension (e.g., '.py', '.txt').

        Returns:
            A list of dictionaries, where each dictionary represents a chunk
            and contains 'content' and 'metadata' (including code_entities).
        """
        filename_base = os.path.basename(source_id) if source_id else "unknown_source"
        if not content or not content.strip():
            logger.warning(f"Skipping chunking for empty content from '{filename_base}'")
            return []

        if not LANGCHAIN_SPLITTERS_AVAILABLE:
            logger.error("Cannot chunk document: Langchain splitters are unavailable.")
            return []

        splitter_to_use: Optional[Union[RecursiveCharacterTextSplitter, PythonCodeTextSplitter]] = None
        if file_ext == '.py' and self.python_splitter:
            splitter_to_use = self.python_splitter
        elif self.recursive_splitter: # Fallback for non-Python or if python_splitter failed
            splitter_to_use = self.recursive_splitter
        else:
            logger.error(f"No suitable text splitter available for '{filename_base}'. Cannot chunk.")
            return []

        logger.debug(f"Chunking document '{filename_base}' (ext: {file_ext}) using {type(splitter_to_use).__name__}")

        code_structures: List[Dict[str, Any]] = []
        if file_ext == '.py' and self.code_analysis_service:
            try:
                code_structures = self.code_analysis_service.parse_python_structures(content, source_id)
                logger.info(f"Found {len(code_structures)} code structures in '{filename_base}' for entity association.")
            except Exception as e_cas:
                logger.error(f"Error parsing code structures for '{filename_base}' with CodeAnalysisService: {e_cas}")
        elif file_ext == '.py':
            logger.warning(f"CodeAnalysisService not available, cannot extract entities for '{filename_base}'.")


        try:
            line_start_indices = self._get_line_start_indices(content)
            split_texts = splitter_to_use.split_text(content)
            chunks_result: List[Dict[str, Any]] = []
            current_original_content_offset = 0

            for i, text_chunk in enumerate(split_texts):
                if not text_chunk.strip():
                    continue

                chunk_start_in_original = -1
                try:
                    chunk_start_in_original = content.find(text_chunk, current_original_content_offset)
                except Exception: pass # Broad catch for find issues

                if chunk_start_in_original == -1:
                    try: chunk_start_in_original = content.find(text_chunk)
                    except Exception:
                        chunk_start_in_original = current_original_content_offset
                        logger.warning(
                            f"Could not reliably find start index for chunk {i} of '{filename_base}'. Using estimated pos: {current_original_content_offset}")

                chunk_end_in_original = chunk_start_in_original + len(text_chunk)
                start_line = self._get_line_number(chunk_start_in_original, line_start_indices)
                last_char_index_of_chunk = max(0, chunk_end_in_original - 1)
                end_line = self._get_line_number(last_char_index_of_chunk, line_start_indices)

                # --- Associate Code Entities ---
                entities_in_chunk: List[str] = []
                if code_structures: # Only if we have structures (i.e., for Python files and CAS worked)
                    for struct in code_structures:
                        struct_start_line = struct.get("start_line")
                        struct_end_line = struct.get("end_line")
                        struct_name = struct.get("name")

                        if struct_start_line is not None and struct_end_line is not None and struct_name:
                            # Check for overlap: if the structure's line range overlaps with the chunk's line range
                            if max(start_line, struct_start_line) <= min(end_line, struct_end_line):
                                entities_in_chunk.append(struct_name)
                # --- End Entity Association ---

                metadata = {
                    "source": str(source_id), # Full path or identifier
                    "filename": filename_base, # Just the filename for display
                    "chunk_index": i,
                    "start_char_index": chunk_start_in_original,
                    "chunk_length_chars": len(text_chunk),
                    "start_line": start_line,
                    "end_line": end_line,
                    "content": text_chunk, # Storing original chunk content in metadata for easy retrieval
                    "code_entities": list(set(entities_in_chunk)) # Store unique entity names
                }
                chunks_result.append({"content": text_chunk, "metadata": metadata})
                current_original_content_offset = chunk_start_in_original + 1

            logger.info(f"Created {len(chunks_result)} non-empty chunks for '{filename_base}'. Entities associated where applicable.")
            return chunks_result

        except Exception as e:
            logger.exception(f"Error chunking document '{filename_base}' using {type(splitter_to_use).__name__}: {e}")
            return []

    def is_ready(self) -> bool:
        """Checks if the service has necessary components initialized."""
        return LANGCHAIN_SPLITTERS_AVAILABLE and (self.recursive_splitter is not None or self.python_splitter is not None)