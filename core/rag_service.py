# core/rag_service.py
import logging
import os
import re
from typing import List, Optional, Dict, Any, Set, Tuple

from utils import constants
from .app_settings import AppSettings
from .project_manager import ProjectManager

# --- Service Imports ---
try:
    from services.embedding_service import EmbeddingService
except ImportError:
    EmbeddingService = type("EmbeddingService", (object,),
                            {"embed_texts": lambda self, texts, project_id=None: [([0.1] * 10) for _ in texts], # Adjusted mock
                             "get_embedding_dimension": lambda self: 10})
    logging.warning("RAGService: EmbeddingService not found, using placeholder.")

try:
    from services.chunking_service import ChunkingService
except ImportError:
    ChunkingService = type("ChunkingService", (object,), {"chunk_document": lambda self, content, source_id, file_ext: [
        {"content": content,
         "metadata": {"source": source_id, "filename": os.path.basename(source_id), "chunk_index": 0, "start_line": 1,
                      "end_line": 10, "code_entities": []}}]})
    logging.warning("RAGService: ChunkingService not found, using placeholder.")

try:
    from services.vector_db_service import VectorDBService
except ImportError:
    VectorDBService = type("VectorDBService", (object,), {
        "is_ready": lambda self, cid=None: True,
        "get_or_create_collection": lambda self, cid: True,
        "add_embeddings": lambda self, cid, embs, metas: True,
        "search": lambda self, cid, q_emb, k: [
            {"metadata": {"content": "Placeholder chunk", "source": "dummy.py", "code_entities": []}, "distance": 0.5}],
        "get_collection_size": lambda self, cid: 0,
        "get_all_metadata": lambda self, cid: []
    })
    logging.warning("RAGService: VectorDBService not found, using placeholder.")

try:
    from core.file_manager import FileManager # Retain for now, but FileHandlerService will take over file reading
except ImportError:
    FileManager = type("FileManager", (object,), {"read_file": lambda self, fp: (None, "FileManager placeholder")})
    logging.warning("RAGService: FileManager not found, using placeholder.")

# --- NEW: Import FileHandlerService and CodeAnalysisService ---
try:
    from services.file_handler_service import FileHandlerService
    FILE_HANDLER_SERVICE_AVAILABLE = True
except ImportError:
    FileHandlerService = None # type: ignore
    FILE_HANDLER_SERVICE_AVAILABLE = False
    logging.error("RAGService: FileHandlerService not found. PDF/DOCX processing will be unavailable.")

try:
    from services.code_analysis_service import CodeAnalysisService
    CODE_ANALYSIS_SERVICE_AVAILABLE = True
except ImportError:
    CodeAnalysisService = None # type: ignore
    CODE_ANALYSIS_SERVICE_AVAILABLE = False
    logging.error("RAGService: CodeAnalysisService not found. Python code structure analysis will be unavailable.")
# --- END NEW IMPORTS ---

logger = logging.getLogger(constants.APP_NAME)


class RAGService:
    _TECHNICAL_KEYWORDS: Set[str] = {
        'python', 'code', 'error', 'fix', 'implement', 'explain', 'how to',
        'def ', 'class ', 'import ', ' module', ' function', ' method',
        ' attribute', ' bug', ' issue', ' traceback', ' install', ' pip',
        ' library', ' package', ' api', ' request', ' data', ' typeerror',
        ' indexerror', ' keyerror', ' exception', ' syntax', ' logic', ' algorithm',
        ' self.', ' args', ' kwargs', ' return', ' yield', ' async', ' await',
        ' decorator', ' lambda', ' list', ' dict', ' tuple', ' set', ' numpy', ' pandas',
        'pyqt6', 'pyqt', 'qwidget', 'qapplication', 'qdialog', 'qlabel', 'qpixmap',
        'rag', 'vector db', 'embedding', 'chunking', 'context', 'prompt', 'llm', 'ollama', 'faiss',
        'collection', 'document', 'similarity', 'query', 'index',
        'my code', 'my project', 'refactor this', 'debug this', 'in my implementation',
        'according to the file', 'based on the documents', 'in these files', 'the provided context',
        'summarize this', 'search', 'find', 'lookup', 'relevant context',
        'change', 'update', 'modify',
    }
    _GREETING_PATTERNS: re.Pattern = re.compile(
        r"^\s*(hi|hello|hey|yo|sup|good\s+(morning|afternoon|evening)|how\s+are\s+you)\b.*", re.IGNORECASE)
    _CODE_FENCE_PATTERN: re.Pattern = re.compile(r"```")

    def __init__(self, settings: AppSettings, project_manager: ProjectManager):
        self.settings = settings
        self.project_manager = project_manager

        self.embedding_service = EmbeddingService(settings=self.settings) # Pass settings
        self.chunking_service = ChunkingService(settings=self.settings) # Pass settings

        self.vector_db_service = VectorDBService(
            index_dimension=self.embedding_service.get_embedding_dimension(),
            base_persist_directory=constants.RAG_COLLECTIONS_DIR
        )
        self.file_manager = FileManager(settings=self.settings, project_manager=self.project_manager) # May be deprecated for RAG

        # --- NEW: Instantiate FileHandlerService and CodeAnalysisService ---
        if FILE_HANDLER_SERVICE_AVAILABLE:
            self.file_handler_service = FileHandlerService()
        else:
            self.file_handler_service = None # type: ignore
            logging.error("RAGService: FileHandlerService could not be instantiated.")

        if CODE_ANALYSIS_SERVICE_AVAILABLE:
            self.code_analysis_service = CodeAnalysisService()
        else:
            self.code_analysis_service = None # type: ignore
            logging.error("RAGService: CodeAnalysisService could not be instantiated.")
        # --- END NEW INSTANTIATIONS ---

        logger.info("RAGService initialized.")

    async def initialize_rag_for_active_project(self) -> bool:
        active_project = self.project_manager.get_active_project()
        if active_project:
            project_rag_id = self._get_project_rag_collection_id(active_project.id)
            if self.vector_db_service.get_or_create_collection(project_rag_id):
                logger.info(f"RAG collection '{project_rag_id}' for active project '{active_project.name}' ensured.")
                return True
            else:
                logger.error(f"Failed to ensure RAG collection for active project '{active_project.name}'.")
                return False
        # Ensure global collection exists if no active project or specific project fails
        if self.vector_db_service.get_or_create_collection(constants.GLOBAL_RAG_COLLECTION_ID):
            logger.info(f"Global RAG collection '{constants.GLOBAL_RAG_COLLECTION_ID}' ensured.")
        return False

    def _get_project_rag_collection_id(self, project_id: str) -> str:
        # Ensure project_id is just the UUID part if a full "project_..." string is passed
        clean_project_id = project_id.replace("project_", "").replace("_rag", "")
        return f"project_{clean_project_id}_rag"


    def _get_rag_collection_id_for_current_project(self) -> Optional[str]:
        active_project = self.project_manager.get_active_project()
        if active_project:
            return self._get_project_rag_collection_id(active_project.id)
        return None

    async def add_text_to_rag(self, text_content: str, source_identifier: str, project_id: Optional[str] = None,
                              metadata_extra: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        target_project_id = project_id or (
            self.project_manager.get_active_project_id() if self.project_manager.get_active_project() else None)

        if not target_project_id: # If still no target_project_id, default to global
             logger.warning("No target project ID specified or active for RAG, defaulting to global collection.")
             collection_id = constants.GLOBAL_RAG_COLLECTION_ID
        elif target_project_id == constants.GLOBAL_RAG_COLLECTION_ID:
            collection_id = constants.GLOBAL_RAG_COLLECTION_ID
        else: # It's a specific project ID
            collection_id = self._get_project_rag_collection_id(target_project_id)


        if not self.vector_db_service.get_or_create_collection(collection_id):
            return False, f"Could not access RAG collection '{collection_id}'."

        logger.info(f"Processing text from '{source_identifier}' for RAG into collection '{collection_id}'")

        file_extension = os.path.splitext(source_identifier).lower() if '.' in source_identifier else ".txt"


        try:
            # ChunkingService will be responsible for using CodeAnalysisService internally if file_ext is .py
            chunks_data = self.chunking_service.chunk_document(text_content, source_id=source_identifier,
                                                               file_ext=file_extension)
            if not chunks_data:
                return True, f"Content from '{source_identifier}' processed, but no chunks generated."

            chunk_contents = [chunk['content'] for chunk in chunks_data]
            chunk_metadatas = [chunk['metadata'] for chunk in chunks_data]

            if metadata_extra:
                for meta in chunk_metadatas:
                    meta.update(metadata_extra)

            if not chunk_contents:
                return True, f"No textual content to embed from '{source_identifier}'."

            # EmbeddingService now takes an optional project_id if needed for model selection/rate limits
            embeddings = await self.embedding_service.embed_texts(chunk_contents) # project_id removed from here
            if embeddings is None or len(embeddings) != len(chunk_metadatas):
                return False, f"Embedding failed or mismatch for '{source_identifier}'."

            import numpy as np # Ensure numpy is imported
            embeddings_np = np.array(embeddings, dtype=np.float32)

            success = self.vector_db_service.add_embeddings(collection_id, embeddings_np, chunk_metadatas)
            if success:
                return True, f"Successfully added content from '{source_identifier}' to RAG collection '{collection_id}'."
            else:
                return False, f"Failed to add embeddings from '{source_identifier}' to RAG collection '{collection_id}'."
        except Exception as e:
            logger.exception(f"Error adding text from '{source_identifier}' to RAG:")
            return False, f"Error processing '{source_identifier}' for RAG: {e}"

    async def add_file_to_rag(self, absolute_file_path: str, project_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Adds a single file to the RAG system. Uses FileHandlerService to read content.
        The project_id determines which RAG collection to add to. If None, uses active project or global.
        """
        if not self.file_handler_service:
            return False, "FileHandlerService is not available."
        if not os.path.isfile(absolute_file_path):
            return False, f"File not found: {absolute_file_path}"

        filename_display = os.path.basename(absolute_file_path)
        logger.info(f"RAGService: Adding file '{filename_display}' (Path: {absolute_file_path}) to RAG.")

        content, file_type, error_msg = self.file_handler_service.read_file_content(absolute_file_path)

        if error_msg or content is None:
            err = error_msg or f"Failed to read file content from {filename_display}."
            logger.warning(f"RAGService: Skipping file '{filename_display}'. Reason: {err}")
            return False, err
        if file_type == "binary":
            msg = f"File '{filename_display}' is binary and cannot be added to RAG."
            logger.info(msg)
            return False, msg
        if file_type not in ["text", "pdf", "docx"]:
            msg = f"File '{filename_display}' type '{file_type}' not supported for RAG text extraction."
            logger.info(msg)
            return False, msg

        # Determine target collection ID based on provided project_id or active project
        target_collection_project_id = project_id
        if not target_collection_project_id: # If project_id is None, try to use active project
            active_project = self.project_manager.get_active_project()
            if active_project:
                target_collection_project_id = active_project.id
            # If still no target_collection_project_id, add_text_to_rag will default to global

        return await self.add_text_to_rag(content, source_identifier=absolute_file_path, project_id=target_collection_project_id)

    async def add_folder_to_rag(self, folder_path: str, project_id: Optional[str] = None) -> Tuple[int, int, List[str]]:
        """
        Recursively adds files from a folder to the RAG system for the specified project_id.
        If project_id is None, uses the active project or defaults to global.

        Returns:
            Tuple (success_count, failure_count, list_of_error_messages)
        """
        if not os.path.isdir(folder_path):
            logger.error(f"RAGService: Folder not found for RAG processing: {folder_path}")
            return 0, 1, [f"Folder not found: {folder_path}"]

        success_count = 0
        failure_count = 0
        error_messages: List[str] = []

        # Determine target collection ID
        target_collection_project_id = project_id
        if not target_collection_project_id:
            active_project = self.project_manager.get_active_project()
            if active_project:
                target_collection_project_id = active_project.id
            # If still None, add_file_to_rag -> add_text_to_rag will handle defaulting to global

        logger.info(f"RAGService: Starting to process folder '{folder_path}' for project_id '{target_collection_project_id or 'default (active/global)'}'.")

        for root, dirs, files in os.walk(folder_path, topdown=True):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if d not in constants.DEFAULT_IGNORED_DIRS and not d.startswith('.')]

            for file_name in files:
                file_ext = os.path.splitext(file_name).lower()
                if file_name.startswith('.') or file_ext not in constants.ALLOWED_TEXT_EXTENSIONS:
                    logger.debug(f"Skipping file due to extension or hidden: {os.path.join(root, file_name)}")
                    continue

                absolute_file_path = os.path.join(root, file_name)
                try:
                    file_size = os.path.getsize(absolute_file_path)
                    max_size_bytes = constants.RAG_MAX_FILE_SIZE_MB * 1024 * 1024
                    if file_size == 0:
                        logger.info(f"Skipping empty file: {absolute_file_path}")
                        failure_count +=1
                        error_messages.append(f"Empty file skipped: {file_name}")
                        continue
                    if file_size > max_size_bytes:
                        logger.warning(
                            f"Skipping file larger than {constants.RAG_MAX_FILE_SIZE_MB}MB: {absolute_file_path}")
                        failure_count += 1
                        error_messages.append(f"File too large: {file_name} ({file_size / (1024*1024):.2f}MB)")
                        continue

                    # Pass the determined target_collection_project_id to add_file_to_rag
                    added, msg = await self.add_file_to_rag(absolute_file_path, project_id=target_collection_project_id)
                    if added:
                        success_count += 1
                    else:
                        failure_count += 1
                        error_messages.append(f"Failed '{file_name}': {msg}")
                except OSError as e_os:
                    logger.error(f"OS error processing file {absolute_file_path} in folder scan: {e_os}")
                    failure_count += 1
                    error_messages.append(f"OS Error '{file_name}': {e_os}")
                except Exception as e_gen:
                    logger.exception(f"Unexpected error processing file {absolute_file_path} in folder scan:")
                    failure_count += 1
                    error_messages.append(f"Unexpected Error '{file_name}': {e_gen}")

        logger.info(
            f"RAGService: Folder processing for '{folder_path}' complete. Added: {success_count}, Failed: {failure_count}.")
        if error_messages:
            logger.warning(f"Errors during folder processing of '{folder_path}': {error_messages}")
        return success_count, failure_count, error_messages

    def get_displayable_collections(self) -> List[Dict[str, str]]:
        collections_info: List[Dict[str, str]] = []
        available_ids = self.vector_db_service.get_available_collection_ids()

        for coll_id in available_ids:
            display_name = ""
            if coll_id == constants.GLOBAL_RAG_COLLECTION_ID:
                display_name = constants.GLOBAL_CONTEXT_DISPLAY_NAME
            elif coll_id.startswith("project_") and coll_id.endswith("_rag"):
                proj_uuid_candidate = coll_id[len("project_"):-len("_rag")]
                project = self.project_manager.get_project_by_id(proj_uuid_candidate)
                if project:
                    display_name = f"Project: {project.name}"
                else:
                    display_name = f"Project RAG (Orphaned ID: {proj_uuid_candidate[:8]}...)"
            else:
                display_name = f"Other: {coll_id}"
            collections_info.append({"id": coll_id, "name": display_name, "raw_id": coll_id})

        return sorted(collections_info, key=lambda x: x["name"])

    def clear_rag_collection(self, collection_id: str) -> bool:
        logger.info(f"RAGService: Request to clear collection '{collection_id}'.")
        if not self.vector_db_service.is_ready(collection_id):
             logger.warning(f"RAGService: Collection '{collection_id}' not ready or does not exist. Cannot clear.")
             # Try to create it to ensure it's there, then clear. This might be desired if user expects to clear a non-existent one.
             if not self.vector_db_service.get_or_create_collection(collection_id):
                 logger.error(f"RAGService: Failed to ensure collection '{collection_id}' exists before clearing.")
                 return False

        return self.vector_db_service.clear_collection_content(collection_id)

    def delete_rag_collection(self, collection_id: str) -> bool:
        logger.info(f"RAGService: Request to delete collection '{collection_id}'.")
        if collection_id == constants.GLOBAL_RAG_COLLECTION_ID:
            logger.error(f"RAGService: Deletion of the global RAG collection '{collection_id}' is not allowed.")
            return False
        return self.vector_db_service.delete_collection(collection_id)


    def should_perform_rag(self, query: str, project_id: Optional[str] = None) -> bool:
        target_project_id = project_id or (
            self.project_manager.get_active_project_id() if self.project_manager.get_active_project() else None)

        if not target_project_id: # If still no target_project_id, RAG is likely not relevant unless global is intended
            collection_id_to_check = constants.GLOBAL_RAG_COLLECTION_ID
        elif target_project_id == constants.GLOBAL_RAG_COLLECTION_ID:
            collection_id_to_check = constants.GLOBAL_RAG_COLLECTION_ID
        else:
            collection_id_to_check = self._get_project_rag_collection_id(target_project_id)


        global_ready = self.vector_db_service.is_ready(
            constants.GLOBAL_RAG_COLLECTION_ID) and self.vector_db_service.get_collection_size(
            constants.GLOBAL_RAG_COLLECTION_ID) > 0

        project_collection_actual_id = self._get_project_rag_collection_id(target_project_id) if target_project_id and target_project_id != constants.GLOBAL_RAG_COLLECTION_ID else collection_id_to_check
        project_ready = self.vector_db_service.is_ready(
            project_collection_actual_id) and self.vector_db_service.get_collection_size(project_collection_actual_id) > 0


        if not (global_ready or project_ready):
            return False
        if not query:
            return False

        query_lower = query.lower().strip()
        if len(query_lower) < 10 and self._GREETING_PATTERNS.match(query_lower):
            return False
        if len(query_lower) < 8: # Very short queries unlikely to benefit from broad RAG
            return False # Consider making this configurable
        if self._CODE_FENCE_PATTERN.search(query): # If user pastes code, RAG is likely useful
            return True
        if any(keyword in query_lower for keyword in self._TECHNICAL_KEYWORDS):
            return True
        # If query contains specific syntax characters common in code or technical questions
        if re.search(r"[_.(){}\[\]=:]", query) and len(query_lower) > 15:
            return True
        return False

    def extract_code_entities(self, query: str) -> Set[str]:
        entities: Set[str] = set()
        if not query:
            return entities

        call_pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\('
        def_class_pattern = r'\b(?:def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)'
        try:
            for match in re.finditer(call_pattern, query): entities.add(match.group(1))
            for match in re.finditer(def_class_pattern, query): entities.add(match.group(1))
        except Exception as e:
            logger.warning(f"Regex error during query entity extraction: {e}")

        entities = {e for e in entities if len(e) > 2 and e not in ['def', 'class', 'self', 'True', 'False', 'None']}
        return entities

    async def get_formatted_context(
            self,
            query: str,
            project_id: Optional[str] = None,
            top_k: Optional[int] = None,
            focus_paths: Optional[List[str]] = None,
            is_modification_request: bool = False
    ) -> Tuple[str, List[str]]:

        context_str = ""
        queried_collections_ids: List[str] = []

        target_project_id_for_context = project_id or (
            self.project_manager.get_active_project_id() if self.project_manager.get_active_project() else None)

        if not target_project_id_for_context:
            logger.warning("RAGService: Cannot get context, no target_project_id provided or active. Assuming global.")
            target_project_id_for_context = constants.GLOBAL_RAG_COLLECTION_ID


        collections_to_query: List[str] = []
        if target_project_id_for_context != constants.GLOBAL_RAG_COLLECTION_ID:
            project_collection_id = self._get_project_rag_collection_id(target_project_id_for_context)
            if self.vector_db_service.is_ready(project_collection_id) and self.vector_db_service.get_collection_size(
                    project_collection_id) > 0:
                collections_to_query.append(project_collection_id)

        # Always consider global collection if it's ready and has data
        if self.vector_db_service.is_ready(constants.GLOBAL_RAG_COLLECTION_ID) and \
           self.vector_db_service.get_collection_size(constants.GLOBAL_RAG_COLLECTION_ID) > 0:
            if constants.GLOBAL_RAG_COLLECTION_ID not in collections_to_query: # Avoid duplicates
                 collections_to_query.append(constants.GLOBAL_RAG_COLLECTION_ID)


        if not collections_to_query:
            logger.info(f"No ready RAG collections with data for project context '{target_project_id_for_context}' or global.")
            return "", []

        query_embedding = await self.embedding_service.embed_texts([query]) # project_id removed
        if query_embedding is None or not query_embedding:
            logger.error("Failed to generate query embedding for RAG.")
            return "[Error: Could not process query for RAG]", []

        import numpy as np
        query_embedding_np = np.array(query_embedding, dtype=np.float32)

        num_results_setting = self.settings.get("rag_top_k", constants.DEFAULT_RAG_TOP_K)
        effective_top_k = top_k if top_k is not None else num_results_setting

        num_initial_results_multiplier = 3 if is_modification_request else 2
        num_initial_results = effective_top_k * num_initial_results_multiplier

        all_retrieved_chunks: List[Dict[str, Any]] = []
        for coll_id in collections_to_query:
            results = self.vector_db_service.search(coll_id, query_embedding_np, k=num_initial_results)
            for res_dict in results:
                if isinstance(res_dict, dict) and 'metadata' in res_dict:
                    res_dict['metadata']['retrieved_from_collection'] = coll_id
                all_retrieved_chunks.append(res_dict)
            if results:
                queried_collections_ids.append(coll_id)

        if not all_retrieved_chunks:
            logger.info(f"No relevant RAG chunks found for query in collections: {collections_to_query}")
            return "", queried_collections_ids

        normalized_focus_paths: Set[str] = set()
        if focus_paths:
            try:
                normalized_focus_paths = {os.path.normcase(os.path.abspath(p)) for p in focus_paths}
            except Exception as e_norm:
                logger.error(f"Error normalizing focus paths {focus_paths}: {e_norm}")

        query_entities = self.extract_code_entities(query)
        entity_boost_factor = 0.80
        focus_boost_factor = 0.60

        boosted_chunks: List[Dict[str, Any]] = []
        for chunk_dict in all_retrieved_chunks:
            if not isinstance(chunk_dict, dict): continue
            metadata = chunk_dict.get('metadata')
            distance = chunk_dict.get('distance')

            if not isinstance(metadata, dict) or not isinstance(distance, (int, float)):
                continue

            new_distance = float(distance)
            boost_reason_applied = ""

            chunk_source_path = metadata.get('source')
            if normalized_focus_paths and chunk_source_path:
                try:
                    norm_chunk_path = os.path.normcase(os.path.abspath(chunk_source_path))
                    is_focused = False
                    for focus_path_item in normalized_focus_paths:
                        if os.path.isdir(focus_path_item):
                            if norm_chunk_path.startswith(focus_path_item + os.sep):
                                is_focused = True;
                                break
                        elif norm_chunk_path == focus_path_item:
                            is_focused = True;
                            break
                    if is_focused:
                        new_distance *= focus_boost_factor
                        boost_reason_applied = 'focus'
                except Exception as e_focus:
                    logger.warning(f"Error applying focus boost for chunk '{chunk_source_path}': {e_focus}")

            if not boost_reason_applied and query_entities:
                chunk_code_entities = set(metadata.get('code_entities', []))
                if not query_entities.isdisjoint(chunk_code_entities):
                    new_distance *= entity_boost_factor
                    boost_reason_applied = 'entity'

            chunk_dict_copy = chunk_dict.copy()
            chunk_dict_copy['distance'] = new_distance
            if boost_reason_applied:
                chunk_dict_copy['boost_reason'] = boost_reason_applied
            boosted_chunks.append(chunk_dict_copy)

        sorted_results = sorted(boosted_chunks, key=lambda x: x.get('distance', float('inf')))
        final_results = sorted_results[:effective_top_k]

        context_parts: List[str] = []
        retrieved_sources_for_log: List[str] = []
        for i, chunk_data_dict in enumerate(final_results):
            meta = chunk_data_dict.get("metadata", {})
            filename_display = meta.get("filename", "unknown_source")
            coll_id_display = meta.get("retrieved_from_collection", "N/A")
            coll_name_from_id = coll_id_display
            if coll_id_display == constants.GLOBAL_RAG_COLLECTION_ID:
                coll_name_from_id = constants.GLOBAL_CONTEXT_DISPLAY_NAME
            elif coll_id_display.startswith("project_"):
                proj_uuid_cand = coll_id_display[len("project_"):-len("_rag")]
                proj_obj = self.project_manager.get_project_by_id(proj_uuid_cand)
                if proj_obj: coll_name_from_id = f"Proj: {proj_obj.name}"


            chunk_content_display = meta.get("content", "[Content Missing]")
            dist_val = chunk_data_dict.get('distance', -1.0)
            boost_applied_reason = chunk_data_dict.get('boost_reason', '')

            debug_info = f"(Dist: {dist_val:.4f}"
            if boost_applied_reason: debug_info += f", Boost: {boost_applied_reason}"

            chunk_ents = meta.get('code_entities', [])
            if query_entities and chunk_ents:
                matches = query_entities.intersection(set(chunk_ents))
                if matches: debug_info += f", Matches: {list(matches)}"
            debug_info += ")"

            context_parts.append(
                f"--- Snippet {i + 1} from `{filename_display}` (Source: {coll_name_from_id}) {debug_info} ---\n```python\n{chunk_content_display}\n```\n")
            retrieved_sources_for_log.append(f"{filename_display} ({coll_name_from_id}) {debug_info}")


        if context_parts:
            context_str = ("--- Relevant Code Context Start ---\n" + "\n".join(
                context_parts) + "--- Relevant Code Context End ---")
            logger.info(
                f"Final RAG context includes {len(final_results)} chunks: [{', '.join(retrieved_sources_for_log)}]")
        else:
            logger.info("No valid RAG chunks remained after processing/sorting.")

        return context_str, list(set(queried_collections_ids))

    def shutdown(self) -> None:
        if self.vector_db_service and hasattr(self.vector_db_service, 'shutdown'): # Changed to check for shutdown
            self.vector_db_service.shutdown() # Call shutdown if it exists
        logger.info("RAGService shutdown.")