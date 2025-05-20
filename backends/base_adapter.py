from abc import ABC, abstractmethod
from typing import List, Optional, AsyncGenerator, Dict, Any, Tuple

class ChatMessage:
    def __init__(self, role: str, content: str, # Simplified for this example
                 image_data: Optional[List[Dict[str, str]]] = None,
                 metadata: Optional[Dict[str, Any]] = None):
        self.role = role
        self.content = content
        self.image_data = image_data or []
        self.metadata = metadata or {}

class LLMAdapterInterface(ABC):

    @abstractmethod
    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        pass

    @abstractmethod
    async def configure_model(self, model_id: str, api_key: Optional[str] = None,
                              model_parameters: Optional[Dict[str, Any]] = None,
                              system_prompt: Optional[str] = None) -> Tuple[bool, str]:
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        pass

    @abstractmethod
    def get_current_model_id(self) -> Optional[str]:
        pass

    @abstractmethod
    async def get_response_stream(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        stop_sequences: Optional[List[str]] = None
    ) -> AsyncGenerator[Tuple[str, Optional[str]], None]:
        # Yields (text_chunk, error_message)
        # If error_message is not None, streaming should stop.
        # Placeholder to make it a generator
        if False:
            yield "", None
        pass

    @abstractmethod
    async def get_response_complete(
        self,
        messages: List[ChatMessage],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        stop_sequences: Optional[List[str]] = None
    ) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, int]]]:
        # Returns (full_response_text, error_message, usage_dict)
        pass

    @abstractmethod
    async def list_available_models(self, api_key: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        # Returns (list_of_model_dicts, error_message)
        # Model dict example: {"id": "model-id", "name": "Model Name", "provider": "ProviderName"}
        pass

    @abstractmethod
    def get_last_error(self) -> Optional[str]:
        pass

    @abstractmethod
    def get_token_usage(self) -> Dict[str, int]:
        # Example: {"prompt_tokens": X, "completion_tokens": Y, "total_tokens": Z}
        pass

    @abstractmethod
    def supports_system_prompt(self) -> bool:
        pass

    @abstractmethod
    def supports_images(self) -> bool:
        pass

    @abstractmethod
    def set_comms_logger(self, comms_logger: Any) -> None:
        pass