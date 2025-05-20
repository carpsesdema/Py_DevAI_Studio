import datetime
import uuid
from typing import List, Optional, Dict, Any, NamedTuple

try:
    from .message_enums import MessageLoadingState  # Forward declaration for type hint
except ImportError:
    # Define a placeholder if message_enums isn't created yet,
    # this helps with type hinting during generation.
    class MessageLoadingState:  # type: ignore
        IDLE = 0
        LOADING = 1
        COMPLETED = 2
        ERROR = 3


class ChatMessage:
    def __init__(self,
                 role: str,
                 content: str,
                 id: Optional[str] = None,
                 timestamp: Optional[str] = None,
                 image_data: Optional[List[Dict[str, str]]] = None,
                 metadata: Optional[Dict[str, Any]] = None,
                 loading_state: Optional[Any] = None):  # Use Any for placeholder MessageLoadingState

        self.id: str = id or str(uuid.uuid4())
        self.role: str = role
        self.content: str = content
        self.timestamp: str = timestamp or datetime.datetime.now().isoformat()

        self.image_data: List[Dict[str, str]] = image_data or []
        self.metadata: Dict[str, Any] = metadata or {}

        # Ensure loading_state is an actual MessageLoadingState enum member if possible
        # For now, direct assignment, will be correct once message_enums.py is defined
        self.loading_state: Any = loading_state if loading_state is not None else MessageLoadingState.IDLE

    @property
    def text(self) -> str:  # Alias for content for simpler access if needed
        return self.content

    @property
    def has_images(self) -> bool:
        return bool(self.image_data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "image_data": self.image_data,
            "metadata": self.metadata,
            "loading_state": self.loading_state.value if hasattr(self.loading_state, 'value') else self.loading_state
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatMessage':
        # Handle loading_state conversion if it's stored as int/str
        loading_state_val = data.get("loading_state")
        actual_loading_state = MessageLoadingState.IDLE  # Default
        if isinstance(loading_state_val, int):
            try:
                actual_loading_state = MessageLoadingState(loading_state_val)
            except ValueError:
                pass  # Keep default
        elif isinstance(loading_state_val, str):  # If stored as string name
            try:
                actual_loading_state = MessageLoadingState[loading_state_val.upper()]
            except KeyError:
                pass

        return cls(
            id=data.get("id"),
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp"),
            image_data=data.get("image_data"),
            metadata=data.get("metadata"),
            loading_state=actual_loading_state
        )