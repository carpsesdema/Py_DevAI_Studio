from enum import Enum

class MessageLoadingState(Enum):
    IDLE = 0      # Message is static, not expecting updates (e.g., user message, fully loaded AI message)
    LOADING = 1   # AI is actively generating/streaming this message
    COMPLETED = 2 # AI has finished generating/streaming this message successfully
    ERROR = 3     # An error occurred while generating/fetching this message

    @property
    def display_name(self) -> str:
        # Provides a human-readable version if needed, though not strictly necessary for enum usage
        return self.name.replace("_", " ").title()

    def __str__(self) -> str:
        return self.name