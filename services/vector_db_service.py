# services/vector_db_service.py
import logging
import os
import pickle  # For saving/loading metadata (simple persistence)
import shutil  # For deleting collection directories

# Ensure faiss and numpy are imported
try:
    import faiss
    import numpy as np

    FAISS_AVAILABLE = True
except ImportError:
    faiss = None  # type: ignore
    np = None  # type: ignore
    FAISS_AVAILABLE = False
    logging.critical(
        "VectorDBService: FAISS or NumPy library not found. RAG DB cannot function. Install: pip install faiss-cpu numpy")

from typing import List, Dict, Any, Optional, Tuple

# --- Local Imports ---
from utils import constants

# Define GLOBAL_COLLECTION_ID, typically imported from constants
GLOBAL_COLLECTION_ID = constants.GLOBAL_COLLECTION_ID

logger = logging.getLogger(__name__)


class VectorDBService:
    """
    Manages interactions with FAISS vector indices, supporting multiple collections.
    Each collection is stored in a separate directory containing a FAISS index file
    and a pickled metadata file.
    Relies on external embedding generation (embeddings passed to add_embeddings).
    """

    def __init__(self, index_dimension: int, base_persist_directory: Optional[str] = None):
        logger.info("VectorDBService initializing (FAISS implementation)...")
        self._service_ready = False
        self._collections_data: Dict[str, Tuple[faiss.Index, List[Dict[str, Any]]]] = {}

        if not FAISS_AVAILABLE:
            logger.critical("FAISS or NumPy library not available. VectorDBService cannot initialize.")
            return

        if not isinstance(index_dimension, int) or index_dimension <= 0:
            logger.critical(f"Invalid index dimension provided: {index_dimension}. Cannot initialize FAISS.")
            return
        self._index_dim = index_dimension
        logger.info(f"Using index dimension: {self._index_dim}")

        self.base_persist_directory = base_persist_directory or constants.RAG_COLLECTIONS_PATH
        logger.info(f"Using FAISS base persist directory: {self.base_persist_directory}")
        try:
            os.makedirs(self.base_persist_directory, exist_ok=True)
            logger.info(f"FAISS base directory ensured: {self.base_persist_directory}")
        except OSError as e:
            logger.critical(f"Failed to create FAISS base directory '{self.base_persist_directory}': {e}")
            return

        if FAISS_AVAILABLE:
            self._service_ready = True
            logger.info("VectorDBService: Core dependencies (FAISS) ready. Proceeding with collection loading.")
        else:
            logger.critical("VectorDBService: FAISS not available at a critical point. Cannot set service as ready.")
            return

        self._load_all_collections_from_disk()
        global_coll_exists_and_loaded = self.get_or_create_collection(GLOBAL_COLLECTION_ID)

        if global_coll_exists_and_loaded and GLOBAL_COLLECTION_ID in self._collections_data:
            logger.info("VectorDBService initialized successfully and global collection is ready.")
        else:
            logger.error(
                "VectorDBService initialized, but the global collection ('%s') could not be properly created or loaded. "
                "RAG functionality relying on the global context may be impaired.", GLOBAL_COLLECTION_ID
            )

    def _load_all_collections_from_disk(self):
        logger.info(f"Scanning directory '{self.base_persist_directory}' for existing collections...")
        loaded_count = 0
        try:
            if os.path.isdir(self.base_persist_directory):
                for item_name in os.listdir(self.base_persist_directory):
                    collection_dir = os.path.join(self.base_persist_directory, item_name)
                    if os.path.isdir(collection_dir):
                        collection_id = item_name
                        logger.debug(f"  Attempting to load collection '{collection_id}' from {collection_dir}...")
                        loaded_data = self._load_collection_data(collection_id)
                        if loaded_data:
                            self._collections_data[collection_id] = loaded_data
                            loaded_count += 1
                            logger.debug(f"  Successfully loaded collection '{collection_id}'.")
                        else:
                            logger.warning(f"  Failed to load collection '{collection_id}'. Skipping.")
            logger.info(f"Finished scanning. Loaded {loaded_count} existing collections.")
        except Exception as e:
            logger.exception(f"Error scanning or loading collections from disk: {e}")

    def _load_collection_data(self, collection_id: str) -> Optional[Tuple[faiss.Index, List[Dict[str, Any]]]]:
        collection_dir = os.path.join(self.base_persist_directory, collection_id)
        index_path = os.path.join(collection_dir, "faiss.index")
        metadata_path = os.path.join(collection_dir, "metadata.pkl")

        if not os.path.exists(index_path) or not os.path.exists(metadata_path):
            logger.debug(f"Collection files not found for '{collection_id}' at {collection_dir}")
            return None
        try:
            if faiss is None: logger.error("FAISS library not available for reading index."); return None
            index = faiss.read_index(index_path)
            with open(metadata_path, 'rb') as f:
                metadata = pickle.load(f)

            if not isinstance(metadata, list):
                logger.error(f"Loaded metadata for '{collection_id}' is not a list ({type(metadata)}). Corrupt?")
                return None
            if index.ntotal != len(metadata):
                logger.warning(
                    f"Mismatch between FAISS index size ({index.ntotal}) and metadata count ({len(metadata)}) for collection '{collection_id}'. Data might be inconsistent.")
                if len(metadata) < index.ntotal:  # If metadata is shorter, something went wrong during a save
                    logger.error(
                        f"  Metadata for '{collection_id}' is SHORTER ({len(metadata)}) than index ({index.ntotal}). Critical inconsistency. Cannot load.")
                    return None
                # If metadata is longer, it might be from a failed add_with_ids where index wasn't rolled back but metadata was extended.
                # For safety, best not to load.
                logger.error(
                    f"  Metadata for '{collection_id}' is LONGER ({len(metadata)}) than index ({index.ntotal}). Critical inconsistency. Cannot load.")
                return None

            if index.d != self._index_dim:
                logger.error(
                    f"Loaded FAISS index dimension ({index.d}) for collection '{collection_id}' does not match service dimension ({self._index_dim}). Cannot load.")
                return None
            return index, metadata
        except Exception as e:
            logger.error(f"Error loading collection data for '{collection_id}': {e}", exc_info=True)
            return None

    def _save_collection_data(self, collection_id: str, index: faiss.Index, metadata: List[Dict[str, Any]]) -> bool:
        if not FAISS_AVAILABLE: logger.error("Cannot save collection data: FAISS not available."); return False
        collection_dir = os.path.join(self.base_persist_directory, collection_id)
        index_path = os.path.join(collection_dir, "faiss.index")
        metadata_path = os.path.join(collection_dir, "metadata.pkl")
        try:
            os.makedirs(collection_dir, exist_ok=True)
            faiss.write_index(index, index_path)  # Save FAISS index first

            # --- START FOCUSED PICKLE DEBUGGING for YOUR version ---
            logger.debug(
                f"[VDB YOUR_VER_SAVE_DEBUG] Attempting to pickle {len(metadata)} metadata entries for '{collection_id}'.")
            problematic_item_details = "No specific item identified as problematic by individual check."
            can_pickle_all_items_individually = True
            for i, item_to_check in enumerate(metadata):
                try:
                    # Test pickling individual item
                    _ = pickle.dumps(item_to_check)  # Store to a throwaway var to ensure it runs
                except Exception as e_item_pickle:
                    can_pickle_all_items_individually = False
                    problematic_item_details = (
                        f"Item at index {i} (source: {item_to_check.get('source', 'N/A')}, "
                        f"filename: {item_to_check.get('filename', 'N/A')}, "
                        f"chunk_idx: {item_to_check.get('chunk_index', 'N/A')}) "
                        f"failed individual pickling. Error: {e_item_pickle}. Item keys: {list(item_to_check.keys()) if isinstance(item_to_check, dict) else 'Not a dict'}"
                    )
                    logger.error(f"[VDB YOUR_VER_SAVE_DEBUG] {problematic_item_details}")
                    # Log types of values in the problematic item
                    if isinstance(item_to_check, dict):
                        for key, value in item_to_check.items():
                            logger.debug(
                                f"  [VDB YOUR_VER_SAVE_DEBUG] Problematic Item Key: '{key}', Value Type: {type(value)}")
                    break  # Stop after first problematic item

            if not can_pickle_all_items_individually:
                logger.error(
                    f"[VDB YOUR_VER_SAVE_DEBUG] CRITICAL ERROR: One or more metadata items are not pickleable for '{collection_id}'. Details: {problematic_item_details}")
                return False  # Indicate save failure

            # If all items are individually pickleable, try to pickle the whole list
            try:
                with open(metadata_path, 'wb') as f:
                    pickle.dump(metadata, f)
                logger.debug(
                    f"[VDB YOUR_VER_SAVE_DEBUG] Successfully pickled and wrote entire metadata list for '{collection_id}'.")
            except Exception as e_pickle_list:
                logger.error(
                    f"[VDB YOUR_VER_SAVE_DEBUG] CRITICAL ERROR: Failed to pickle the entire metadata list for '{collection_id}', even if individual items seemed okay: {e_pickle_list}",
                    exc_info=True)
                return False
            # --- END FOCUSED PICKLE DEBUGGING ---

            logger.debug(
                f"Saved collection '{collection_id}' to {collection_dir}")  # This line will only be reached if pickle succeeded
            return True
        except Exception as e:  # Catch other errors like os.makedirs or faiss.write_index
            logger.exception(f"Error saving collection data (non-pickle stage) for '{collection_id}': {e}")
            return False

    def get_or_create_collection(self, collection_id: str) -> bool:
        if not FAISS_AVAILABLE or not self._service_ready:
            logger.error(
                f"Cannot get/create collection '{collection_id}': FAISS not available ({FAISS_AVAILABLE}) or Service not ready ({self._service_ready}).")
            return False
        if not isinstance(collection_id, str) or not collection_id.strip():
            logger.error("Cannot get/create collection: Invalid or empty collection_id provided.")
            return False
        if collection_id in self._collections_data:
            logger.debug(f"Collection '{collection_id}' already loaded in memory.")
            return True
        loaded_data = self._load_collection_data(collection_id)
        if loaded_data:
            self._collections_data[collection_id] = loaded_data
            logger.info(f"Loaded collection '{collection_id}' from disk.")
            return True
        logger.info(f"Collection '{collection_id}' not found. Creating new...")
        try:
            if faiss is None: logger.error(
                "FAISS library became unavailable during get_or_create_collection."); return False
            new_index = faiss.IndexFlatL2(self._index_dim)
            new_index_mapped = faiss.IndexIDMap(new_index)
            new_metadata: List[Dict[str, Any]] = []
            if self._save_collection_data(collection_id, new_index_mapped, new_metadata):
                self._collections_data[collection_id] = (new_index_mapped, new_metadata)
                logger.info(f"Created and loaded new collection '{collection_id}' with IndexIDMap.")
                return True
            else:
                logger.error(f"Failed to save newly created collection '{collection_id}' to disk.")
                return False
        except Exception as e:
            logger.exception(f"Error creating new collection '{collection_id}': {e}")
            return False

    def is_ready(self, collection_id: Optional[str] = None) -> bool:
        if not FAISS_AVAILABLE or not self._service_ready:
            return False
        if collection_id is None:
            return GLOBAL_COLLECTION_ID in self._collections_data
        return collection_id in self._collections_data

    def add_embeddings(self, collection_id: str, embeddings: np.ndarray, metadatas: List[Dict[str, Any]]) -> bool:
        if not self.is_ready(collection_id): logger.error(
            f"Cannot add embeddings: Collection '{collection_id}' not loaded or service not ready."); return False
        if not isinstance(embeddings, np.ndarray) or not isinstance(metadatas, list): logger.error(
            "Invalid input: embeddings must be a NumPy array, metadatas a list."); return False
        if embeddings.shape[0] != len(metadatas): logger.error(
            f"Input length mismatch: embeddings count ({embeddings.shape[0]}) != metadata count ({len(metadatas)})."); return False
        if embeddings.ndim != 2 or embeddings.shape[1] != self._index_dim: logger.error(
            f"Embedding dimension mismatch or incorrect shape: Got {embeddings.shape}, expected (n, {self._index_dim})."); return False
        if embeddings.shape[0] == 0: logger.warning(
            f"No embeddings provided to add to collection '{collection_id}'."); return True

        index, collection_metadata = self._collections_data[collection_id]
        if not isinstance(index, faiss.IndexIDMap):
            logger.error(
                f"Collection '{collection_id}' index is not an IndexIDMap. Recreate collection.")
            return False

        logger.info(f"Adding {embeddings.shape[0]} embeddings to collection '{collection_id}'...")
        try:
            start_id = index.ntotal
            new_ids = np.arange(start_id, start_id + embeddings.shape[0]).astype('int64')

            # --- VDB DEBUG for your version ---
            logger.debug(f"[VDB YOUR_VER_ADD_DEBUG] Collection='{collection_id}', Current index.ntotal={start_id}")
            logger.debug(
                f"[VDB YOUR_VER_ADD_DEBUG] Embeddings shape={embeddings.shape}, Embeddings dtype={embeddings.dtype}")
            logger.debug(
                f"[VDB YOUR_VER_ADD_DEBUG] New IDs shape={new_ids.shape}, IDs dtype={new_ids.dtype}, First 5 IDs: {new_ids[:5] if new_ids.size > 0 else 'N/A'}")
            if embeddings.shape[0] != len(metadatas):
                logger.error(
                    f"[VDB YOUR_VER_ADD_DEBUG] CRITICAL MISMATCH before add_with_ids: Embeddings count {embeddings.shape[0]} != Metadatas count {len(metadatas)}")
                return False
            # --- END VDB DEBUG ---

            index.add_with_ids(embeddings, new_ids)
            collection_metadata.extend(metadatas)
            if self._save_collection_data(collection_id, index, collection_metadata):
                logger.info(
                    f"Successfully added and saved {embeddings.shape[0]} embeddings to '{collection_id}'. New index ntotal: {index.ntotal}")
                return True
            else:
                logger.error(
                    f"Successfully added embeddings to '{collection_id}' in-memory index but FAILED TO SAVE to disk.")
                # Attempt to rollback the in-memory add if save failed
                try:
                    logger.warning(
                        f"Attempting to rollback in-memory add for '{collection_id}'. Removing last {embeddings.shape[0]} items.")
                    index.remove_ids(new_ids)  # remove the IDs just added
                    del collection_metadata[-embeddings.shape[0]:]  # remove the metadata just added
                    logger.info(
                        f"In-memory rollback for '{collection_id}' attempted. Index ntotal now: {index.ntotal}, Metadata len: {len(collection_metadata)}")
                except Exception as e_rollback:
                    logger.error(
                        f"Error during in-memory rollback for '{collection_id}': {e_rollback}. Index and metadata may be INCONSISTENT.")
                return False
        except Exception as e:
            logger.exception(f"Error adding embeddings to collection '{collection_id}': {e}")
            return False

    def remove_document_chunks_by_source(self, collection_id: str, source_path_to_remove: str) -> bool:
        if not self.is_ready(collection_id): return False
        if not isinstance(source_path_to_remove, str) or not source_path_to_remove.strip(): return False

        index, collection_metadata = self._collections_data[collection_id]
        if not isinstance(index, faiss.IndexIDMap): return False

        logger.info(
            f"Removing chunks for source '{source_path_to_remove}' from '{collection_id}'. Original ntotal: {index.ntotal}, meta_len: {len(collection_metadata)}")

        ids_to_remove_from_faiss = []
        new_metadata_list = []
        original_indices_removed_from_metadata = []  # For debugging

        for i, meta_entry in enumerate(collection_metadata):
            if isinstance(meta_entry, dict) and meta_entry.get("source") == source_path_to_remove:
                # We are assuming the FAISS ID is the original index 'i' before any removals.
                # This is where the brittleness lies if not managed perfectly.
                ids_to_remove_from_faiss.append(np.int64(i))
                original_indices_removed_from_metadata.append(i)
            else:
                new_metadata_list.append(meta_entry)

        if not ids_to_remove_from_faiss:
            logger.info(f"No chunks found with source '{source_path_to_remove}' in metadata of '{collection_id}'.")
            return True

        num_expected_to_remove = len(ids_to_remove_from_faiss)
        try:
            ids_to_remove_np_array = np.array(ids_to_remove_from_faiss, dtype='int64')
            num_actually_removed_from_faiss = index.remove_ids(ids_to_remove_np_array)

            if num_actually_removed_from_faiss != num_expected_to_remove:
                logger.warning(f"FAISS remove_ids reported removing {num_actually_removed_from_faiss} vectors, "
                               f"but expected to remove {num_expected_to_remove} for source '{source_path_to_remove}'. "
                               f"IDs attempted to remove: {ids_to_remove_from_faiss}. Original metadata indices marked for removal: {original_indices_removed_from_metadata}")
            else:
                logger.info(
                    f"Successfully removed {num_actually_removed_from_faiss} vectors from FAISS index for source '{source_path_to_remove}'.")

            self._collections_data[collection_id] = (index, new_metadata_list)  # Update in-memory metadata

            if self._save_collection_data(collection_id, index, new_metadata_list):
                logger.info(
                    f"Saved collection '{collection_id}' after removing {num_expected_to_remove} metadata entries. New index ntotal: {index.ntotal}, new meta_len: {len(new_metadata_list)}")
                return True
            else:
                logger.error(
                    f"Removed chunks from FAISS for '{source_path_to_remove}' but FAILED TO SAVE collection '{collection_id}'. Data on disk is stale.")
                # Attempt to revert in-memory metadata change (index change is harder to revert safely without re-adding)
                self._collections_data[collection_id] = (index, collection_metadata)  # Put back old metadata list
                logger.warning(
                    f"Attempted to revert in-memory metadata for '{collection_id}'. FAISS index itself was modified but not saved after modification.")
                return False
        except Exception as e:
            logger.exception(
                f"Error during remove_document_chunks for '{source_path_to_remove}' from '{collection_id}': {e}")
            return False

    def search(self, collection_id: str, query_embedding: np.ndarray, k: int = 5) -> List[Dict[str, Any]]:
        if not self.is_ready(collection_id): return []
        if not isinstance(query_embedding, np.ndarray) or query_embedding.ndim != 2 or query_embedding.shape[0] != 1 or \
                query_embedding.shape[1] != self._index_dim: return []

        collection_index, collection_metadata = self._collections_data[collection_id]
        if collection_index.ntotal == 0: return []
        effective_k = min(k, collection_index.ntotal)
        if effective_k == 0: return []

        try:
            distances, faiss_ids = collection_index.search(query_embedding, effective_k)
            results = []
            for i in range(effective_k):
                faiss_id_val = faiss_ids[0][i]
                if faiss_id_val == -1: continue

                # This is the potentially problematic part if IDs are not direct indices
                # into the *current state* of collection_metadata after removals.
                if 0 <= faiss_id_val < len(collection_metadata):
                    metadata_found = collection_metadata[faiss_id_val]
                    results.append({'content': metadata_found.get('content', '[Content Missing]'),
                                    'metadata': metadata_found,
                                    'distance': float(distances[0][i])})
                else:
                    logger.warning(f"Search in '{collection_id}' returned FAISS ID {faiss_id_val} "
                                   f"which is out of bounds for current metadata list (len {len(collection_metadata)}). "
                                   "This indicates an inconsistency, likely after deletions.")
            return results
        except Exception as e:
            logger.exception(f"Error searching collection '{collection_id}': {e}")
            return []

    def get_all_metadata(self, collection_id: str) -> List[Dict[str, Any]]:
        if not self.is_ready(collection_id): return []
        _, collection_metadata = self._collections_data[collection_id]
        return list(collection_metadata)

    def get_collection_size(self, collection_id: str) -> int:
        if not self.is_ready(collection_id): return -1
        collection_index, _ = self._collections_data[collection_id]
        return collection_index.ntotal

    def clear_collection(self, collection_id: str) -> bool:
        if collection_id == GLOBAL_COLLECTION_ID: return False
        if not self.is_ready(collection_id): return False
        logger.warning(f"Clearing collection '{collection_id}' by re-creating.")
        try:
            new_index = faiss.IndexFlatL2(self._index_dim)
            new_index_mapped = faiss.IndexIDMap(new_index)
            new_metadata: List[Dict[str, Any]] = []
            if self._save_collection_data(collection_id, new_index_mapped, new_metadata):
                self._collections_data[collection_id] = (new_index_mapped, new_metadata)
                logger.info(f"Collection '{collection_id}' cleared successfully.")
                return True
            else:
                logger.error(f"Failed to save cleared collection '{collection_id}'.")
                return False
        except Exception as e:
            logger.exception(f"Error clearing collection '{collection_id}': {e}")
            return False

    def get_available_collections(self) -> List[str]:
        return list(self._collections_data.keys())

    def delete_collection(self, collection_id: str) -> bool:
        if not self._service_ready: return False
        if collection_id == GLOBAL_COLLECTION_ID: return False

        collection_dir = os.path.join(self.base_persist_directory, collection_id)
        removed_from_memory = False
        if collection_id in self._collections_data:
            del self._collections_data[collection_id]
            removed_from_memory = True

        disk_deleted = False
        if os.path.isdir(collection_dir):
            try:
                shutil.rmtree(collection_dir)
                disk_deleted = True
            except Exception as e:
                logger.exception(f"Error deleting disk collection '{collection_id}': {e}")

        if removed_from_memory or disk_deleted:
            logger.info(f"Collection '{collection_id}' deleted (Memory: {removed_from_memory}, Disk: {disk_deleted}).")
            return True
        logger.warning(f"Collection '{collection_id}' not found for deletion (neither in memory nor on disk).")
        return False