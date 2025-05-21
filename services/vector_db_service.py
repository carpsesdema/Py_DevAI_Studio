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
            if index.ntotal != len(metadata):  # FAISS indices start from 0. index.ntotal is count.
                logger.warning(
                    f"Mismatch between FAISS index size ({index.ntotal}) and metadata count ({len(metadata)}) for collection '{collection_id}'. Data might be inconsistent.")
                # Attempt to reconcile if metadata is shorter (e.g. incomplete save)
                if len(metadata) < index.ntotal:
                    logger.warning(
                        f"  Metadata for '{collection_id}' is shorter than index. Truncating index for safety.")
                    # This is complex; a simple approach is to rebuild, or for now, just warn and proceed cautiously.
                    # A more robust solution might involve trying to remove the excess vectors from FAISS if possible,
                    # or re-indexing if metadata is the source of truth. For now, we'll log and it might lead to errors.
                    # A simple fix is to not load if this happens, forcing a re-index.
                    # return None # Or, try to trim index: index.remove_ids(np.arange(len(metadata), index.ntotal))
                    # For now, let's not load if there's a mismatch that can't be easily fixed.
                    return None
            if index.d != self._index_dim:
                logger.error(
                    f"Loaded FAISS index dimension ({index.d}) for collection '{collection_id}' does not match service dimension ({self._index_dim}). Cannot load.")
                return None
            return index, metadata
        except Exception as e:
            logger.error(f"Error loading collection data for '{collection_id}': {e}")
            return None

    def _save_collection_data(self, collection_id: str, index: faiss.Index, metadata: List[Dict[str, Any]]) -> bool:
        if not FAISS_AVAILABLE: logger.error("Cannot save collection data: FAISS not available."); return False
        collection_dir = os.path.join(self.base_persist_directory, collection_id)
        index_path = os.path.join(collection_dir, "faiss.index")
        metadata_path = os.path.join(collection_dir, "metadata.pkl")
        try:
            os.makedirs(collection_dir, exist_ok=True)
            faiss.write_index(index, index_path)
            with open(metadata_path, 'wb') as f:
                pickle.dump(metadata, f)
            logger.debug(f"Saved collection '{collection_id}' to {collection_dir}")
            return True
        except Exception as e:
            logger.exception(f"Error saving collection data for '{collection_id}': {e}")
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
            new_index = faiss.IndexFlatL2(self._index_dim)  # L2 distance
            # To support remove_ids, the index needs to be an IndexIDMap or similar.
            # We wrap the IndexFlatL2 with IndexIDMap.
            new_index_mapped = faiss.IndexIDMap(new_index)
            new_metadata: List[Dict[str, Any]] = []
            # Save the mapped index
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
        logger.debug(
            f"[RAG_VIEW_DEBUG] is_ready called. collection_id: '{collection_id}', _service_ready: {self._service_ready}, FAISS_AVAILABLE: {FAISS_AVAILABLE}")
        logger.debug(f"[RAG_VIEW_DEBUG] Current _collections_data keys: {list(self._collections_data.keys())}")
        if not FAISS_AVAILABLE or not self._service_ready:
            logger.debug(
                f"[RAG_VIEW_DEBUG] is_ready returning False (FAISS_AVAILABLE={FAISS_AVAILABLE}, _service_ready={self._service_ready})")
            return False
        if collection_id is None:  # General service readiness (e.g. global collection)
            is_global_loaded = GLOBAL_COLLECTION_ID in self._collections_data
            logger.debug(
                f"[RAG_VIEW_DEBUG] is_ready (global check for '{GLOBAL_COLLECTION_ID}') returning {is_global_loaded}.")
            return is_global_loaded
        is_specific_loaded = collection_id in self._collections_data
        logger.debug(
            f"[RAG_VIEW_DEBUG] is_ready (specific check for '{collection_id}') returning {is_specific_loaded}.")
        return is_specific_loaded

    def get_available_collections(self) -> List[str]:
        return list(self._collections_data.keys())

    def delete_collection(self, collection_id: str) -> bool:
        if not self._service_ready: logger.error(
            f"Cannot delete collection '{collection_id}': Service not ready."); return False
        if collection_id == GLOBAL_COLLECTION_ID: logger.error(
            f"Cannot delete the global collection '{GLOBAL_COLLECTION_ID}'."); return False
        collection_dir = os.path.join(self.base_persist_directory, collection_id)
        removed_from_memory = False
        if collection_id in self._collections_data:
            del self._collections_data[collection_id]
            removed_from_memory = True
            logger.debug(f"Collection '{collection_id}' removed from memory.")
        else:
            logger.warning(f"Attempted to delete collection '{collection_id}', but it's not loaded in memory.")
        disk_deleted = False
        if os.path.isdir(collection_dir):
            logger.info(f"Attempting to delete collection directory from disk: {collection_dir}")
            try:
                shutil.rmtree(collection_dir); logger.info(
                    f"Collection directory '{collection_id}' deleted successfully from disk."); disk_deleted = True
            except Exception as e:
                logger.exception(f"Error deleting collection directory '{collection_id}': {e}")
        else:
            logger.warning(f"Collection directory '{collection_id}' not found on disk either.")
            if not removed_from_memory: return False  # If not in memory and not on disk, it didn't exist
        return removed_from_memory or disk_deleted

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
        if not isinstance(index, faiss.IndexIDMap):  # Ensure it's an IndexIDMap
            logger.error(
                f"Collection '{collection_id}' index is not an IndexIDMap. Cannot reliably add/remove with IDs. Recreate collection.")
            return False

        logger.info(f"Adding {embeddings.shape[0]} embeddings to collection '{collection_id}'...")
        try:
            # Generate unique IDs for new embeddings. These IDs must be int64.
            # A simple way is to use current count as starting ID if index is empty, or max_id + 1.
            # However, FAISS IndexIDMap can take any int64 IDs.
            # For simplicity, if we are always appending, we can use sequential IDs based on current count.
            # But if we remove and add, IDs can get reused or become non-contiguous.
            # A safer approach for general use is to ensure new IDs are unique.
            # For now, let's assume we are adding to the end and IDs correspond to position if index was empty.
            # If index.ntotal > 0, we need to generate IDs that don't clash.
            # A robust way is to maintain a separate ID counter or use UUIDs mapped to int64,
            # or simply use the new vector's position in the *overall combined index* as its ID.
            # If `index.add_with_ids` is used, the IDs must be provided.

            # Let's use the current total count as the starting ID for the new batch.
            # This assumes IDs are contiguous and we are appending.
            # This is a simplification. A robust system might need more complex ID management if
            # vectors are frequently removed and re-added non-sequentially.
            # For `IndexIDMap.add_with_ids`, the `ids` array must be of type int64.

            start_id = index.ntotal
            new_ids = np.arange(start_id, start_id + embeddings.shape[0]).astype('int64')

            index.add_with_ids(embeddings, new_ids)  # Use add_with_ids for IndexIDMap
            collection_metadata.extend(metadatas)
            if self._save_collection_data(collection_id, index, collection_metadata):
                logger.info(f"Successfully added and saved {embeddings.shape[0]} embeddings to '{collection_id}'.")
                return True
            else:
                logger.error(
                    f"Successfully added embeddings to '{collection_id}' index but FAILED TO SAVE metadata/index.")
                # Potentially try to revert the add operation if save fails (complex)
                return False
        except Exception as e:
            logger.exception(f"Error adding embeddings to collection '{collection_id}': {e}")
            return False

    # --- NEW METHOD ---
    def remove_document_chunks_by_source(self, collection_id: str, source_path_to_remove: str) -> bool:
        """
        Removes all chunks (vectors and metadata) associated with a specific source_path
        from the given collection.
        """
        if not self.is_ready(collection_id):
            logger.error(
                f"Cannot remove document chunks: Collection '{collection_id}' not loaded or service not ready.")
            return False
        if not isinstance(source_path_to_remove, str) or not source_path_to_remove.strip():
            logger.error("Invalid source_path_to_remove provided.")
            return False

        index, collection_metadata = self._collections_data[collection_id]

        if not isinstance(index, faiss.IndexIDMap):
            logger.error(
                f"Collection '{collection_id}' index is not an IndexIDMap. Cannot remove by ID. Operation aborted.")
            # This is critical. If it's not IndexIDMap, remove_ids will not work as expected.
            # Consider forcing re-creation of the collection if this state is encountered.
            return False

        logger.info(
            f"Attempting to remove all chunks for source '{source_path_to_remove}' from collection '{collection_id}'.")

        ids_to_remove_np = []
        new_metadata = []
        removed_count = 0

        # Iterate through metadata to find matching chunks and their original indices (which are their FAISS IDs)
        # We need to map metadata list indices to FAISS vector IDs.
        # If we used `add_with_ids` and the IDs were simply `0, 1, 2... ntotal-1` at the time of adding,
        # then the metadata index corresponds to the FAISS ID.
        # This assumption is critical for `IndexIDMap.remove_ids`.

        # Let's assume IDs are 0-based contiguous matching metadata list index for now.
        # This relies on how `add_embeddings` assigns IDs.
        # If IDs were arbitrary, we'd need to store the FAISS ID in metadata or have another mapping.

        current_faiss_ids_to_check = []
        metadata_indices_to_keep = []

        for i, meta_entry in enumerate(collection_metadata):
            # Assuming `i` is the FAISS ID if added sequentially with `add_with_ids(embeddings, np.arange(start, start+N))`
            faiss_id_for_this_meta = i

            if isinstance(meta_entry, dict) and meta_entry.get("source") == source_path_to_remove:
                current_faiss_ids_to_check.append(faiss_id_for_this_meta)
                removed_count += 1
            else:
                metadata_indices_to_keep.append(i)  # Keep track of metadata to preserve

        if not current_faiss_ids_to_check:
            logger.info(
                f"No chunks found for source '{source_path_to_remove}' in collection '{collection_id}'. Nothing to remove.")
            return True  # Operation considered successful as there's nothing to do

        try:
            # FAISS remove_ids expects a numpy array of int64 IDs
            ids_to_remove_np_array = np.array(current_faiss_ids_to_check, dtype='int64')

            # Perform the removal from FAISS index
            # The `remove_ids` function returns the number of elements removed.
            num_actually_removed_from_faiss = index.remove_ids(ids_to_remove_np_array)

            if num_actually_removed_from_faiss != removed_count:
                logger.warning(f"FAISS remove_ids reported removing {num_actually_removed_from_faiss} vectors, "
                               f"but expected to remove {removed_count} for source '{source_path_to_remove}'. "
                               "Index might be in an inconsistent state if this happens frequently.")
            else:
                logger.info(
                    f"Successfully removed {num_actually_removed_from_faiss} vectors from FAISS index for source '{source_path_to_remove}'.")

            # Rebuild the metadata list, keeping only non-removed items
            updated_metadata_list = [collection_metadata[i] for i in metadata_indices_to_keep]

            # Update the collection data in memory
            self._collections_data[collection_id] = (index, updated_metadata_list)

            # Save the changes to disk
            if self._save_collection_data(collection_id, index, updated_metadata_list):
                logger.info(
                    f"Successfully removed {removed_count} chunks for source '{source_path_to_remove}' and saved collection '{collection_id}'.")
                return True
            else:
                logger.error(
                    f"Removed chunks for '{source_path_to_remove}' from index but FAILED TO SAVE collection '{collection_id}'. Data is now inconsistent on disk!")
                # This is a critical error state. Consider how to handle (e.g., attempt rollback, mark collection as dirty)
                return False
        except Exception as e:
            logger.exception(
                f"Error removing document chunks for source '{source_path_to_remove}' from collection '{collection_id}': {e}")
            return False

    # --- END NEW METHOD ---

    def search(self, collection_id: str, query_embedding: np.ndarray, k: int = 5) -> List[Dict[str, Any]]:
        if not self.is_ready(collection_id): logger.error(
            f"Cannot search: Collection '{collection_id}' not loaded or service not ready."); return []
        if not isinstance(query_embedding, np.ndarray) or query_embedding.ndim != 2 or query_embedding.shape[0] != 1 or \
                query_embedding.shape[1] != self._index_dim:
            logger.error(
                f"Invalid query embedding format/dimension: Expected (1, {self._index_dim}), got {query_embedding.shape}.");
            return []
        if not isinstance(k, int) or k <= 0: logger.warning(f"Invalid k value ({k}), using default 5."); k = 5

        collection_index, collection_metadata = self._collections_data[collection_id]
        if collection_index.ntotal == 0: logger.info(
            f"Collection '{collection_id}' is empty. Returning no search results."); return []
        effective_k = min(k, collection_index.ntotal)
        if effective_k == 0: return []

        logger.info(f"Searching collection '{collection_id}' ({collection_index.ntotal} items) with k={effective_k}...")
        try:
            distances, indices = collection_index.search(query_embedding, effective_k)
            results = []
            for i in range(effective_k):
                vector_index_in_collection = indices[0][i]  # This is the FAISS ID if IndexIDMap was used correctly
                distance_val = distances[0][i]
                if vector_index_in_collection == -1: continue  # Should not happen with L2 if k <= ntotal

                # Find metadata by matching FAISS ID.
                # This is inefficient if IDs are not == metadata list index.
                # If IDs are contiguous 0..N-1 and match metadata list, direct access is fine.
                # For now, we assume the ID corresponds to the original position IF NO DELETIONS HAPPENED.
                # After deletions, this assumption breaks down unless the index is rebuilt or IDs are carefully managed.
                # This is a key area for robustness improvement.
                # A simple approach: if ID is out of bounds of current metadata, log error.
                # A better approach: store FAISS ID in metadata when adding, or use a dict to map FAISS ID to metadata.

                # Assuming current IDs in `indices` are direct indices into the `collection_metadata` list.
                # This holds if `remove_ids` correctly compacts the index OR if `IndexIDMap` handles mapping.
                # With IndexIDMap, the `indices` returned by `search` are the actual IDs we added.
                # We need a way to map these IDs back to the correct metadata entry.
                # Simplest if metadata list is kept in sync and IDs are effectively indices.
                # If `remove_document_chunks_by_source` rebuilds metadata list, this should be okay.

                metadata_to_use = None
                if 0 <= vector_index_in_collection < len(
                        collection_metadata):  # Simple check if ID is a valid list index
                    metadata_to_use = collection_metadata[vector_index_in_collection]
                else:
                    # This case means the ID from FAISS does not map to a current metadata entry.
                    # This can happen if `remove_ids` was used and metadata wasn't perfectly re-indexed,
                    # or if IDs are not simple 0-based indices.
                    # For IndexIDMap, `indices` are the *original* IDs. We need to find the metadata
                    # that had this ID. This requires either storing the ID in metadata or iterating.
                    # Let's assume for now `remove_document_chunks_by_source` keeps metadata list compact.
                    logger.warning(f"Search for '{collection_id}' returned FAISS ID {vector_index_in_collection} "
                                   f"which is out of bounds for current metadata list (len {len(collection_metadata)}). "
                                   "This indicates a potential inconsistency after deletions if IDs are not managed carefully.")
                    # Try to find by iterating if we stored a unique 'id' or 'faiss_id' in metadata:
                    # for meta_item in collection_metadata:
                    #     if meta_item.get('faiss_id_stored_in_meta') == vector_index_in_collection:
                    #         metadata_to_use = meta_item
                    #         break
                    # if not metadata_to_use:
                    continue  # Skip this result if we can't map ID to metadata

                if metadata_to_use:
                    content = metadata_to_use.get('content', '[Content not found in metadata]')
                    if "collection_id" not in metadata_to_use: metadata_to_use["collection_id"] = collection_id
                    results.append({'content': content, 'metadata': metadata_to_use, 'distance': float(distance_val)})

            logger.info(f"Search completed for collection '{collection_id}'. Found {len(results)} relevant items.")
            return results
        except Exception as e:
            logger.exception(f"Error searching collection '{collection_id}': {e}")
            return []

    def get_all_metadata(self, collection_id: str) -> List[Dict[str, Any]]:
        if not self.is_ready(collection_id): logger.error(
            f"Cannot get metadata: Collection '{collection_id}' not loaded or service not ready."); return []
        _, collection_metadata = self._collections_data[collection_id]
        logger.info(f"Retrieving all metadata ({len(collection_metadata)} items) from collection '{collection_id}'.")
        return list(collection_metadata)  # Return a copy

    def get_collection_size(self, collection_id: str) -> int:
        logger.debug(f"[RAG_VIEW_DEBUG] get_collection_size called for ID: '{collection_id}'")
        if not self.is_ready(collection_id): logger.warning(
            f"[RAG_VIEW_DEBUG] Cannot get size for '{collection_id}': is_ready() returned False."); return -1
        try:
            if collection_id not in self._collections_data:
                logger.warning(
                    f"[RAG_VIEW_DEBUG] Cannot get size: Collection ID '{collection_id}' not found in _collections_data, though is_ready passed for it. This is unexpected.");
                return -1
            collection_index, _ = self._collections_data[collection_id]
            count = collection_index.ntotal
            logger.debug(f"[RAG_VIEW_DEBUG] Collection '{collection_id}' FAISS index.ntotal = {count}")
            return count
        except KeyError:
            logger.warning(
                f"[RAG_VIEW_DEBUG] Cannot get size: Collection ID '{collection_id}' not found in _collections_data (KeyError during access)."); return -1
        except Exception as e:
            logger.exception(f"[RAG_VIEW_DEBUG] Error getting count for collection '{collection_id}': {e}"); return -1

    def clear_collection(self, collection_id: str) -> bool:
        if collection_id == GLOBAL_COLLECTION_ID: logger.error(
            f"Clearing the global collection ('{GLOBAL_COLLECTION_ID}') is not permitted via this method."); return False
        if not self.is_ready(collection_id): logger.error(
            f"Cannot clear collection '{collection_id}': Not loaded or service not ready."); return False
        logger.warning(
            f"Attempting to clear all items from collection '{collection_id}' by re-creating index and metadata...")
        try:
            if faiss is None: logger.error("FAISS library not available for clearing collection."); return False
            new_index = faiss.IndexFlatL2(self._index_dim)
            new_index_mapped = faiss.IndexIDMap(new_index)  # Ensure it's an IDMap for future removals
            new_metadata: List[Dict[str, Any]] = []
            if self._save_collection_data(collection_id, new_index_mapped, new_metadata):
                self._collections_data[collection_id] = (new_index_mapped, new_metadata)
                logger.info(f"Collection '{collection_id}' cleared successfully (by recreating).")
                return True
            else:
                logger.error(f"Failed to save cleared collection '{collection_id}' to disk.")
                return False
        except Exception as e:
            logger.exception(f"Error during the process of clearing collection '{collection_id}': {e}")
            return False