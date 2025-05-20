import logging
import os
import shutil
import pickle
from typing import List, Dict, Any, Optional, Tuple

from utils import constants

try:
    import faiss
    import numpy as np

    FAISS_NUMPY_AVAILABLE = True
except ImportError:
    faiss = None
    np = None
    FAISS_NUMPY_AVAILABLE = False
    logging.critical("VectorDBService: FAISS or NumPy library not found. RAG DB cannot function.")

logger = logging.getLogger(constants.APP_NAME)


class VectorDBService:
    _INDEX_FILENAME = "vector_store.faiss"
    _METADATA_FILENAME = "vector_store.meta.pkl"

    def __init__(self, index_dimension: int, base_persist_directory: str):
        if not FAISS_NUMPY_AVAILABLE:
            raise ImportError("FAISS or NumPy is not installed, VectorDBService cannot operate.")

        if not isinstance(index_dimension, int) or index_dimension <= 0:
            raise ValueError("Index dimension must be a positive integer.")

        self.index_dimension = index_dimension
        self.base_persist_directory = base_persist_directory
        self._collections: Dict[str, Tuple[Optional[faiss.Index], List[Dict[str, Any]]]] = {}

        os.makedirs(self.base_persist_directory, exist_ok=True)
        self._load_all_collections_from_disk()
        logger.info(
            f"VectorDBService initialized. Base directory: {self.base_persist_directory}, Index Dim: {self.index_dimension}")

    def _get_collection_path(self, collection_id: str) -> str:
        return os.path.join(self.base_persist_directory, collection_id)

    def _load_collection_from_disk(self, collection_id: str) -> bool:
        if not FAISS_NUMPY_AVAILABLE: return False
        collection_path = self._get_collection_path(collection_id)
        index_file = os.path.join(collection_path, self._INDEX_FILENAME)
        metadata_file = os.path.join(collection_path, self._METADATA_FILENAME)

        if os.path.exists(index_file) and os.path.exists(metadata_file):
            try:
                index = faiss.read_index(index_file)
                if index.d != self.index_dimension:
                    logger.error(
                        f"Dimension mismatch for collection '{collection_id}'. Expected {self.index_dimension}, got {index.d}. Cannot load.")
                    return False
                with open(metadata_file, 'rb') as f:
                    metadata = pickle.load(f)

                if not isinstance(metadata, list):
                    logger.error(
                        f"Corrupted metadata for collection '{collection_id}'. Expected list, got {type(metadata)}.")
                    return False

                if index.ntotal != len(metadata):
                    logger.warning(
                        f"Index size ({index.ntotal}) and metadata length ({len(metadata)}) mismatch for '{collection_id}'. Data might be inconsistent.")

                self._collections[collection_id] = (index, metadata)
                logger.info(
                    f"Successfully loaded collection '{collection_id}' from disk. Index size: {index.ntotal}, Metadata items: {len(metadata)}")
                return True
            except Exception as e:
                logger.exception(f"Error loading collection '{collection_id}' from disk: {e}")
                if collection_id in self._collections:
                    del self._collections[collection_id]  # Ensure inconsistent state is removed
                return False
        return False

    def _load_all_collections_from_disk(self) -> None:
        if not os.path.isdir(self.base_persist_directory):
            logger.warning(
                f"Base persist directory '{self.base_persist_directory}' does not exist. No collections to load.")
            return

        loaded_count = 0
        for item_name in os.listdir(self.base_persist_directory):
            collection_dir = os.path.join(self.base_persist_directory, item_name)
            if os.path.isdir(collection_dir):
                if self._load_collection_from_disk(item_name):
                    loaded_count += 1
        logger.info(f"Attempted to load all collections. Successfully loaded: {loaded_count}")

    def _save_collection_to_disk(self, collection_id: str) -> bool:
        if not FAISS_NUMPY_AVAILABLE: return False
        if collection_id not in self._collections:
            logger.error(f"Cannot save collection '{collection_id}': Not found in memory.")
            return False

        index, metadata = self._collections[collection_id]
        if index is None:  # Should not happen if collection is in _collections properly
            logger.error(f"Cannot save collection '{collection_id}': Index is None in memory.")
            return False

        collection_path = self._get_collection_path(collection_id)
        os.makedirs(collection_path, exist_ok=True)
        index_file = os.path.join(collection_path, self._INDEX_FILENAME)
        metadata_file = os.path.join(collection_path, self._METADATA_FILENAME)

        try:
            faiss.write_index(index, index_file)
            with open(metadata_file, 'wb') as f:
                pickle.dump(metadata, f)
            logger.info(
                f"Successfully saved collection '{collection_id}' to disk. Index size: {index.ntotal}, Metadata items: {len(metadata)}")
            return True
        except Exception as e:
            logger.exception(f"Error saving collection '{collection_id}' to disk: {e}")
            return False

    def get_or_create_collection(self, collection_id: str) -> bool:
        if not FAISS_NUMPY_AVAILABLE: return False
        if collection_id in self._collections and self._collections[collection_id][0] is not None:
            return True

        if self._load_collection_from_disk(collection_id):
            return True

        logger.info(f"Collection '{collection_id}' not found. Creating new empty collection.")
        try:
            index = faiss.IndexFlatL2(self.index_dimension)
            metadata: List[Dict[str, Any]] = []
            self._collections[collection_id] = (index, metadata)
            return self._save_collection_to_disk(collection_id)
        except Exception as e:
            logger.exception(f"Failed to create new FAISS index for collection '{collection_id}': {e}")
            if collection_id in self._collections:  # Clean up if partially added
                del self._collections[collection_id]
            return False

    def is_ready(self, collection_id: Optional[str] = None) -> bool:
        if not FAISS_NUMPY_AVAILABLE: return False
        if collection_id:
            return collection_id in self._collections and self._collections[collection_id][0] is not None

        # Check if global collection is ready as a general service readiness indicator
        return constants.GLOBAL_RAG_COLLECTION_ID in self._collections and \
            self._collections[constants.GLOBAL_RAG_COLLECTION_ID][0] is not None

    def add_embeddings(self, collection_id: str, embeddings: np.ndarray, metadatas: List[Dict[str, Any]]) -> bool:
        if not FAISS_NUMPY_AVAILABLE: return False
        if not self.get_or_create_collection(collection_id):  # Ensure collection exists
            logger.error(f"Failed to add embeddings: Collection '{collection_id}' could not be accessed/created.")
            return False

        index, collection_metadata_list = self._collections[collection_id]
        if index is None:  # Should be created by get_or_create_collection
            logger.error(
                f"Index for collection '{collection_id}' is None after ensuring collection. This should not happen.")
            return False

        if not isinstance(embeddings, np.ndarray) or embeddings.ndim != 2 or embeddings.shape[
            1] != self.index_dimension:
            logger.error(
                f"Invalid embeddings shape for collection '{collection_id}'. Expected (n, {self.index_dimension}), got {embeddings.shape if isinstance(embeddings, np.ndarray) else type(embeddings)}")
            return False
        if len(embeddings) != len(metadatas):
            logger.error(
                f"Embeddings count ({len(embeddings)}) and metadatas count ({len(metadatas)}) mismatch for '{collection_id}'.")
            return False
        if len(embeddings) == 0:
            logger.info(f"No embeddings provided to add to collection '{collection_id}'.")
            return True

        try:
            index.add(embeddings.astype(np.float32))
            collection_metadata_list.extend(metadatas)
            logger.info(f"Added {len(embeddings)} embeddings to collection '{collection_id}' in memory.")
            return self._save_collection_to_disk(collection_id)
        except Exception as e:
            logger.exception(f"Error adding embeddings to FAISS index for collection '{collection_id}': {e}")
            return False

    def search(self, collection_id: str, query_embedding: np.ndarray, k: int) -> List[Dict[str, Any]]:
        if not FAISS_NUMPY_AVAILABLE: return []
        if collection_id not in self._collections:
            logger.warning(f"Collection '{collection_id}' not found for search.")
            return []

        index, metadata_list = self._collections[collection_id]
        if index is None or index.ntotal == 0:
            logger.info(f"Collection '{collection_id}' is empty or index is None. No search results.")
            return []

        if not isinstance(query_embedding, np.ndarray) or query_embedding.ndim != 2 or query_embedding.shape[0] != 1 or \
                query_embedding.shape[1] != self.index_dimension:
            logger.error(
                f"Invalid query embedding shape for search. Expected (1, {self.index_dimension}), got {query_embedding.shape if isinstance(query_embedding, np.ndarray) else type(query_embedding)}")
            return []

        effective_k = min(k, index.ntotal)
        if effective_k <= 0:
            return []

        try:
            distances, indices = index.search(query_embedding.astype(np.float32), effective_k)
            results = []
            for i in range(effective_k):
                idx = indices[0][i]
                dist = distances[0][i]
                if 0 <= idx < len(metadata_list):
                    # Return a copy of metadata to prevent external modification
                    result_item = metadata_list[idx].copy()
                    result_item['distance'] = float(dist)
                    results.append(result_item)
                else:
                    logger.warning(
                        f"Search index {idx} out of bounds for metadata list (len {len(metadata_list)}) in collection '{collection_id}'.")
            logger.info(f"Search in '{collection_id}' found {len(results)} results for k={effective_k}.")
            return results
        except Exception as e:
            logger.exception(f"Error during FAISS search in collection '{collection_id}': {e}")
            return []

    def get_collection_size(self, collection_id: str) -> int:
        if collection_id in self._collections:
            index, _ = self._collections[collection_id]
            if index:
                return index.ntotal
        return 0

    def get_all_metadata(self, collection_id: str) -> List[Dict[str, Any]]:
        if collection_id in self._collections:
            _, metadata_list = self._collections[collection_id]
            return [m.copy() for m in metadata_list]  # Return copies
        return []

    def get_available_collection_ids(self) -> List[str]:
        return list(self._collections.keys())

    def delete_collection(self, collection_id: str) -> bool:
        if collection_id == constants.GLOBAL_RAG_COLLECTION_ID:
            logger.error(f"Deletion of the global RAG collection '{collection_id}' is not allowed.")
            return False

        if collection_id in self._collections:
            del self._collections[collection_id]
            logger.info(f"Removed collection '{collection_id}' from memory.")

        collection_path = self._get_collection_path(collection_id)
        if os.path.exists(collection_path):
            try:
                shutil.rmtree(collection_path)
                logger.info(f"Successfully deleted collection '{collection_id}' from disk: {collection_path}")
                return True
            except Exception as e:
                logger.exception(f"Error deleting collection directory '{collection_path}' from disk: {e}")
                return False
        logger.warning(
            f"Collection '{collection_id}' not found on disk for deletion, but removed from memory if present.")
        return True  # Considered success if not on disk and removed from memory

    def clear_collection_content(self, collection_id: str) -> bool:
        if not FAISS_NUMPY_AVAILABLE: return False
        if collection_id not in self._collections:
            logger.warning(f"Cannot clear content: Collection '{collection_id}' not loaded.")
            if self.get_or_create_collection(collection_id):  # Try to load/create it
                logger.info(f"Collection '{collection_id}' loaded/created, now attempting clear.")
            else:
                logger.error(f"Failed to load/create collection '{collection_id}' for clearing.")
                return False

        logger.info(f"Clearing all content from collection '{collection_id}'.")
        try:
            new_index = faiss.IndexFlatL2(self.index_dimension)
            new_metadata: List[Dict[str, Any]] = []
            self._collections[collection_id] = (new_index, new_metadata)
            return self._save_collection_to_disk(collection_id)  # Save the empty state
        except Exception as e:
            logger.exception(f"Error clearing content from collection '{collection_id}': {e}")
            return False

    def shutdown(self) -> None:
        logger.info("VectorDBService shutting down. Saving all collections...")
        for collection_id in list(self._collections.keys()):  # Iterate over keys copy
            self._save_collection_to_disk(collection_id)
        logger.info("All collections saved. VectorDBService shutdown complete.")