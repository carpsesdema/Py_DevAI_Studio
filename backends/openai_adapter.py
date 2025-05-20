# PyDevAI_Studio/backends/openai_adapter.py
import asyncio
import logging
import os
import base64
from typing import List, Optional, AsyncGenerator, Dict, Any, Tuple

try:
    import openai
    from openai import AsyncOpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    openai = None
    AsyncOpenAI = None
    OPENAI_AVAILABLE = False

from .base_adapter import LLMAdapterInterface, ChatMessage

logger = logging.getLogger(__name__)


class OpenAIAdapter(LLMAdapterInterface):

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        self.client: Optional[AsyncOpenAI] = None
        self.current_model_id: Optional[str] = None
        self._is_configured: bool = False
        self._last_error: Optional[str] = None
        self._comms_logger: Optional[Any] = None
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._api_key_used_for_configure: Optional[str] = None
        self.system_prompt_content: Optional[str] = None

        if not OPENAI_AVAILABLE:
            self._last_error = "OpenAI library not found. Please install it: pip install openai"
            logger.critical(self._last_error)
            return

    async def configure_model(self, model_id: str, api_key: Optional[str] = None,
                              model_parameters: Optional[Dict[str, Any]] = None,
                              system_prompt: Optional[str] = None) -> Tuple[bool, str]:
        self._is_configured = False
        self._last_error = None
        self.client = None
        self._prompt_tokens = 0
        self._completion_tokens = 0

        if not OPENAI_AVAILABLE:
            self._last_error = "OpenAI library is not installed."
            return False, self._last_error

        effective_api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not effective_api_key:
            self._last_error = "OpenAI API key not provided and not found in environment variable (OPENAI_API_KEY)."
            logger.error(self._last_error)
            return False, self._last_error

        if not model_id:
            self._last_error = "Model ID is required for OpenAI configuration."
            logger.error(self._last_error)
            return False, self._last_error

        try:
            self.client = AsyncOpenAI(api_key=effective_api_key)
            self._api_key_used_for_configure = effective_api_key
            self.current_model_id = model_id
            self.system_prompt_content = system_prompt

            await self.client.models.list(limit=1)

            self._is_configured = True
            logger.info(
                f"OpenAIAdapter configured for model '{model_id}'. System prompt {'set' if system_prompt else 'not set'}.")
            return True, f"Successfully configured OpenAI model: {model_id}"
        except openai.AuthenticationError as e:
            self._last_error = f"OpenAI API Authentication Error: {e}. Check your API key."
            logger.error(self._last_error)
        except openai.APIConnectionError as e:
            self._last_error = f"OpenAI API Connection Error: {e}. Check your network connection."
            logger.error(self._last_error)
        except openai.RateLimitError as e:
            self._last_error = f"OpenAI API Rate Limit Error: {e}."
            logger.error(self._last_error)
        except openai.APIError as e:
            self._last_error = f"OpenAI API Error: {e}"
            logger.error(self._last_error)
        except Exception as e:
            self._last_error = f"Failed to initialize OpenAI client or test connection for model '{model_id}': {e}"
            logger.exception(f"OpenAI configuration error for model {model_id}:")

        self.current_model_id = None
        self.client = None
        return False, self._last_error

    def is_configured(self) -> bool:
        return self._is_configured and self.client is not None and self.current_model_id is not None

    def get_current_model_id(self) -> Optional[str]:
        return self.current_model_id

    def _prepare_api_messages(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        api_messages = []
        if self.system_prompt_content and self.supports_system_prompt():
            api_messages.append({"role": "system", "content": self.system_prompt_content})

        for msg in messages:
            if msg.role == "system" and self.system_prompt_content:
                continue

            content_parts = []
            if msg.content:
                content_parts.append({"type": "text", "text": msg.content})

            if msg.image_data and self.supports_images():
                for img_item in msg.image_data:
                    base64_image = img_item.get("data")
                    mime_type = img_item.get("mime_type", "image/jpeg")
                    if base64_image:
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            }
                        })

            if content_parts:
                api_messages.append({"role": msg.role, "content": content_parts if len(content_parts) > 1 or any(
                    p["type"] == "image_url" for p in content_parts) else msg.content})
            elif msg.content:
                api_messages.append({"role": msg.role, "content": msg.content})

        return api_messages

    async def get_response_stream(
            self,
            messages: List[ChatMessage],
            temperature: float = 0.7,
            max_tokens: Optional[int] = None,
            top_p: Optional[float] = None,
            stop_sequences: Optional[List[str]] = None
    ) -> AsyncGenerator[Tuple[str, Optional[str]], None]:
        if not self.is_configured() or not self.client:
            error_msg = "OpenAIAdapter is not configured."
            logger.error(error_msg)
            yield "", error_msg
            return

        self._last_error = None
        self._prompt_tokens = 0
        self._completion_tokens = 0

        api_messages = self._prepare_api_messages(messages)

        request_params: Dict[str, Any] = {
            "model": self.current_model_id,
            "messages": api_messages,
            "temperature": temperature,
            "stream": True
        }
        if max_tokens is not None: request_params["max_tokens"] = max_tokens
        if top_p is not None: request_params["top_p"] = top_p
        if stop_sequences is not None: request_params["stop"] = stop_sequences

        if self._comms_logger:
            log_msg_prompt = f"OpenAI Stream Request to '{self.current_model_id}': Messages count: {len(api_messages)}, Config: { {k: v for k, v in request_params.items() if k not in ['messages', 'stream', 'model']} }"
            self._comms_logger.log(log_msg_prompt, source="OpenAIAdapter")

        try:
            stream = await self.client.chat.completions.create(**request_params)
            full_response_content = ""
            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                chunk_text = delta.content if delta and delta.content else ""

                if self._comms_logger and chunk_text:
                    self._comms_logger.log(f"OpenAI Raw Stream Chunk: '{chunk_text[:70]}...'",
                                           source=f"OpenAIStream ({self.current_model_id})")

                if chunk_text:
                    full_response_content += chunk_text
                    yield chunk_text, None
            if self._comms_logger:
                self._comms_logger.log(f"OpenAI Stream Response Full: '{full_response_content[:200]}...'",
                                       source="OpenAIAdapter")

        except openai.APIError as e:
            self._last_error = f"OpenAI API Error during stream: {e.__class__.__name__} - {str(e)}"
            logger.error(self._last_error)
            yield "", self._last_error
        except Exception as e:
            self._last_error = f"Unexpected error during OpenAI stream: {type(e).__name__} - {e}"
            logger.exception("OpenAIAdapter stream failed:")
            yield "", self._last_error

    async def get_response_complete(
            self,
            messages: List[ChatMessage],
            temperature: float = 0.7,
            max_tokens: Optional[int] = None,
            top_p: Optional[float] = None,
            stop_sequences: Optional[List[str]] = None
    ) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, int]]]:
        if not self.is_configured() or not self.client:
            error_msg = "OpenAIAdapter is not configured."
            logger.error(error_msg)
            return None, error_msg, None

        self._last_error = None
        self._prompt_tokens = 0
        self._completion_tokens = 0

        api_messages = self._prepare_api_messages(messages)

        request_params: Dict[str, Any] = {
            "model": self.current_model_id,
            "messages": api_messages,
            "temperature": temperature,
        }
        if max_tokens is not None: request_params["max_tokens"] = max_tokens
        if top_p is not None: request_params["top_p"] = top_p
        if stop_sequences is not None: request_params["stop"] = stop_sequences

        if self._comms_logger:
            log_msg_prompt = f"OpenAI Complete Request to '{self.current_model_id}': Messages count: {len(api_messages)}, Config: { {k: v for k, v in request_params.items() if k not in ['messages', 'model']} }"
            self._comms_logger.log(log_msg_prompt, source="OpenAIAdapter")

        try:
            response = await self.client.chat.completions.create(**request_params)

            full_response_text = None
            if response.choices and response.choices[0].message:
                full_response_text = response.choices[0].message.content

            if self._comms_logger and full_response_text:
                self._comms_logger.log(f"OpenAI Complete Response: '{full_response_text[:200]}...'",
                                       source="OpenAIAdapter")

            if response.usage:
                self._prompt_tokens = response.usage.prompt_tokens or 0
                self._completion_tokens = response.usage.completion_tokens or 0

            return full_response_text, None, self.get_token_usage()

        except openai.APIError as e:
            self._last_error = f"OpenAI API Error: {e.__class__.__name__} - {str(e)}"
            logger.error(self._last_error)
            return None, self._last_error, self.get_token_usage()
        except Exception as e:
            self._last_error = f"Unexpected error during OpenAI complete request: {type(e).__name__} - {e}"
            logger.exception("OpenAIAdapter complete request failed:")
            return None, self._last_error, self.get_token_usage()

    async def list_available_models(self, api_key: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if not OPENAI_AVAILABLE:
            self._last_error = "OpenAI library is not installed."
            return [], self._last_error

        temp_client: Optional[AsyncOpenAI] = None
        if self.client and (not api_key or api_key == self._api_key_used_for_configure):
            temp_client = self.client
        else:
            effective_api_key = api_key or os.getenv("OPENAI_API_KEY") or self._api_key_used_for_configure
            if not effective_api_key:
                self._last_error = "API key required to list OpenAI models. Provide one or configure adapter first."
                logger.warning(self._last_error)
                return [], self._last_error
            try:
                temp_client = AsyncOpenAI(api_key=effective_api_key)
            except Exception as e_cfg:
                self._last_error = f"Failed to configure temporary OpenAI client for listing models: {e_cfg}"
                logger.error(self._last_error)
                return [], self._last_error

        if not temp_client:
            self._last_error = "OpenAI client not available for listing models."
            return [], self._last_error

        self._last_error = None
        models_info = []
        try:
            models_page = await temp_client.models.list()
            for model in models_page.data:
                if model.id.startswith("gpt-"):
                    models_info.append({
                        "id": model.id,
                        "name": model.id,
                        "provider": "OpenAI",
                        "created": model.created,
                        "owned_by": model.owned_by
                    })
            return sorted(models_info, key=lambda m: m["id"]), None
        except openai.APIError as e:
            self._last_error = f"OpenAI API Error listing models: {type(e).__name__} - {str(e)}"
            logger.error(self._last_error)
            return [], self._last_error
        except Exception as e:
            self._last_error = f"Failed to list OpenAI models: {type(e).__name__} - {e}"
            logger.error(self._last_error)
            return [], self._last_error

    def get_last_error(self) -> Optional[str]:
        return self._last_error

    def get_token_usage(self) -> Dict[str, int]:
        return {
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "total_tokens": self._prompt_tokens + self._completion_tokens
        }

    def supports_system_prompt(self) -> bool:
        if self.current_model_id:
            return "gpt-" in self.current_model_id.lower()
        return True

    def supports_images(self) -> bool:
        if self.current_model_id:
            return "vision" in self.current_model_id.lower() or \
                self.current_model_id.lower().startswith("gpt-4o")
        return False

    def set_comms_logger(self, comms_logger: Any) -> None:
        self._comms_logger = comms_logger
        logger.info(f"OpenAIAdapter ({self.current_model_id or 'Unconfigured'}): AICommsLogger instance set.")