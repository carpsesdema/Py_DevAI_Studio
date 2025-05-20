import asyncio
import logging
from typing import List, Optional, Union

from utils import constants
from core.app_settings import AppSettings

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SentenceTransformer = None
    np = None
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logging.critical("EmbeddingService: sentence-transformers or numpy library not found. Embedding will not work.")

logger = logging.getLogger(constants.APP_NAME)


class EmbeddingService:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.model_name: str = self.settings.get("rag_embedding_model", constants.DEFAULT_EMBEDDING_MODEL)
        self.model: Optional[SentenceTransformer] = None
        self._embedding_dimension: Optional[int] = None

        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.error("Sentence Transformers library is not available. EmbeddingService will be non-functional.")
            return

        try:
            self.model = SentenceTransformer(self.model_name)
            dummy_emb = self.model.encode(["test sentence"])
            if hasattr(dummy_emb, 'shape') and len(dummy_emb.shape) > 1:
                self._embedding_dimension = dummy_emb.shape[1]
            else:  # Fallback for some models or if encode returns list of lists
                if isinstance(dummy_emb, list) and len(dummy_emb) > 0 and isinstance(dummy_emb[0], list):
                    self._embedding_dimension = len(dummy_emb[0])
                else:  # Try with numpy if it's a 1D numpy array for a single sentence
                    if np and isinstance(dummy_emb, np.ndarray) and dummy_emb.ndim == 1:
                        self._embedding_dimension = dummy_emb.shape[0]
                    else:
                        raise ValueError("Could not determine embedding dimension from dummy encoding.")

            logger.info(
                f"EmbeddingService initialized with model '{self.model_name}'. Dimension: {self._embedding_dimension}")
        except Exception as e:
            logger.exception(f"Failed to load SentenceTransformer model '{self.model_name}': {e}")
            self.model = None
            self._embedding_dimension = None

    def get_embedding_dimension(self) -> int:
        if self._embedding_dimension is not None:
            return self._embedding_dimension

        logger.warning("Embedding dimension not determined during init. Defaulting to 0 or trying a re-check.")
        if self.model:  # Attempt a re-check if model loaded but dimension failed
            try:
                dummy_emb = self.model.encode(["re-check"])
                if hasattr(dummy_emb, 'shape') and len(dummy_emb.shape) > 1:
                    self._embedding_dimension = dummy_emb.shape[1]
                    return self._embedding_dimension
                elif np and isinstance(dummy_emb, np.ndarray) and dummy_emb.ndim == 1:
                    self._embedding_dimension = dummy_emb.shape[0]
                    return self._embedding_dimension
            except Exception:
                pass
        return 0

    async def embed_texts(self, texts: List[str]) -> Optional[List[List[float]]]:
        if not self.model:
            logger.error("Embedding model not loaded. Cannot embed texts.")
            return None
        if not texts:
            return []

        try:
            # The encode method of SentenceTransformer is typically synchronous.
            # We run it in a thread pool executor to avoid blocking the asyncio event loop.
            loop = asyncio.get_running_loop()
            embeddings_np = await loop.run_in_executor(
                None,
                self.model.encode,
                texts,
                {"show_progress_bar": False}
            )

            if np and isinstance(embeddings_np, np.ndarray):
                return embeddings_np.tolist()  # Convert numpy array to list of lists
            elif isinstance(embeddings_np, list):  # If it already returned a list of lists
                return embeddings_np
            else:
                logger.error(f"Unexpected embedding result type: {type(embeddings_np)}")
                return None

        except Exception as e:
            logger.exception(f"Error during text embedding with model '{self.model_name}': {e}")
            return None

    def is_ready(self) -> bool:
        return self.model is not None and self._embedding_dimension is not None and self._embedding_dimension > 0