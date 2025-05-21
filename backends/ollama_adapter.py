import asyncio
import logging
from typing import List, Optional, AsyncGenerator, Dict, Any, Tuple

import ollama

from .base_adapter import LLMAdapterInterface, ChatMessage

logger = logging.getLogger(__name__)

class OllamaAdapter(LLMAdapterInterface):

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        self.client = None
        self.current_model_id = None
        self.host = None
        self.system_prompt = None
        self._is_configured = False
        self._last_error = None
        self._comms_logger = None
        self._prompt_tokens = 0
        self._completion_tokens = 0

        if settings:
            self.host = settings.get("ollama_host")

        try:
            self.client = ollama.AsyncClient(host=self.host)
        except Exception as e:
            self._last_error = f"Failed to initialize Ollama client: {e}"
            logger.error(self._last_error)
            self.client = None

    async def configure_model(self, model_id: str, api_key: Optional[str] = None,
                              model_parameters: Optional[Dict[str, Any]] = None,
                              system_prompt: Optional[str] = None) -> Tuple[bool, str]:
        self._is_configured = False
        self._last_error = None
        self._prompt_tokens = 0
        self._completion_tokens = 0

        if not self.client:
            self._last_error = "Ollama client not initialized."
            try:
                self.client = ollama.AsyncClient(host=self.host)
            except Exception as e:
                self._last_error = f"Failed to re-initialize Ollama client during configure: {e}"
                logger.error(self._last_error)
                return False, self._last_error

        if not model_id:
            self._last_error = "Model ID is required for Ollama configuration."
            logger.error(self._last_error)
            return False, self._last_error

        self.current_model_id = model_id
        self.system_prompt = system_prompt

        try:
            await self.client.list()
            self._is_configured = True
            logger.info(
                f"OllamaAdapter configured for model '{model_id}' on host '{self.host or 'default'}'. System prompt {'set' if system_prompt else 'not set'}.")
            return True, f"Successfully configured Ollama model: {model_id}"
        except Exception as e:
            self._last_error = f"Failed to connect to Ollama or verify model during configuration: {e}"
            logger.error(f"Ollama configuration error for model {model_id}: {e}")
            self.current_model_id = None
            return False, self._last_error

    def is_configured(self) -> bool:
        return self._is_configured and self.client is not None

    def get_current_model_id(self) -> Optional[str]:
        return self.current_model_id

    async def get_response_stream(
            self,
            messages: List[ChatMessage],
            temperature: float = 0.7,
            max_tokens: Optional[int] = None,
            top_p: Optional[float] = None,
            stop_sequences: Optional[List[str]] = None
    ) -> AsyncGenerator[Tuple[str, Optional[str]], None]:
        if not self.is_configured() or not self.client or not self.current_model_id:
            error_msg = "OllamaAdapter is not configured or client/model_id is missing."
            logger.error(error_msg)
            yield "", error_msg
            return

        self._last_error = None
        self._prompt_tokens = 0
        self._completion_tokens = 0

        api_messages = []
        if self.system_prompt:
            api_messages.append({'role': 'system', 'content': self.system_prompt})

        for msg in messages:
            msg_dict = {'role': msg.role, 'content': msg.content}
            if msg.image_data and self.supports_images():
                images_bytes_list = []
                for img_item in msg.image_data:
                    base64_data = img_item.get("data")
                    if base64_data:
                        try:
                            import base64
                            img_bytes = base64.b64decode(base64_data)
                            images_bytes_list.append(img_bytes)
                        except Exception as e_b64:
                            logger.error(f"OllamaAdapter: Failed to decode base64 image for message: {e_b64}")
                if images_bytes_list:
                    msg_dict['images'] = images_bytes_list
            api_messages.append(msg_dict)

        options = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if top_p is not None:
            options["top_p"] = top_p
        if stop_sequences is not None:
            options["stop"] = stop_sequences

        if self._comms_logger:
            log_msg_prompt = f"Ollama Request to '{self.current_model_id}': Messages: {len(api_messages)}, Options: {options}"
            self._comms_logger.log(log_msg_prompt, source="OllamaAdapter")


        try:
            stream_response = await self.client.chat(
                model=self.current_model_id,
                messages=api_messages,
                stream=True,
                options=options
            )

            full_response_content = ""
            async for part in stream_response:
                if self._comms_logger:
                    self._comms_logger.log(
                        f"Ollama Raw Chunk: Done={part.get('done', False)}, Content='{part.get('message', {}).get('content', '')[:70]}...'",
                        source=f"OllamaStream ({self.current_model_id})")

                chunk_text = part.get('message', {}).get('content', '')
                if chunk_text:
                    full_response_content += chunk_text
                    yield chunk_text, None

                if part.get('done'):
                    if 'total_duration' in part:
                        logger.info(f"Ollama stream finished. Total duration: {part.get('total_duration')}")
                        self._prompt_tokens = part.get('prompt_eval_count', 0)
                        self._completion_tokens = part.get('eval_count', 0)
                    break

            if self._comms_logger:
                self._comms_logger.log(f"Ollama Response Full: '{full_response_content[:200]}...'",
                                       source="OllamaAdapter")

        except ollama.ResponseError as e:
            self._last_error = f"Ollama API ResponseError: {e.status_code} - {e.error}"
            logger.error(self._last_error)
            yield "", self._last_error
        except Exception as e:
            self._last_error = f"Unexpected error during Ollama stream: {type(e).__name__} - {e}"
            logger.exception("OllamaAdapter stream failed:")
            yield "", self._last_error

    async def get_response_complete(
            self,
            messages: List[ChatMessage],
            temperature: float = 0.7,
            max_tokens: Optional[int] = None,
            top_p: Optional[float] = None,
            stop_sequences: Optional[List[str]] = None
    ) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, int]]]:

        full_response_text = ""
        final_error_message = None

        async for chunk, error_message in self.get_response_stream(
                messages, temperature, max_tokens, top_p, stop_sequences):
            if error_message:
                final_error_message = error_message
                break
            full_response_text += chunk

        if final_error_message:
            return None, final_error_message, self.get_token_usage()

        return full_response_text, None, self.get_token_usage()

    async def list_available_models(self, api_key: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        if not self.client:
            self._last_error = "Ollama client not initialized. Cannot list models."
            try:
                self.client = ollama.AsyncClient(host=self.host)
            except Exception as e_init:
                self._last_error = f"Failed to re-initialize Ollama client during list_models: {e_init}"
                logger.error(self._last_error)
                return [], self._last_error


        self._last_error = None
        try:
            response = await self.client.list()
            models_info = []
            if isinstance(response, dict) and "models" in response:
                for model_data in response["models"]:
                    models_info.append({
                        "id": model_data.get("name"),
                        "name": model_data.get("name"),
                        "provider": "Ollama",
                        "details": {
                            "model": model_data.get("model"),
                            "modified_at": model_data.get("modified_at"),
                            "size": model_data.get("size"),
                            "family": model_data.get("details", {}).get("family"),
                        }
                    })
            return models_info, None
        except Exception as e:
            self._last_error = f"Failed to list Ollama models: {e}"
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
        return True

    def supports_images(self) -> bool:
        if self.current_model_id:
            return "llava" in self.current_model_id.lower() or \
                "bakllava" in self.current_model_id.lower()
        return False

    def set_comms_logger(self, comms_logger: Any) -> None:
        self._comms_logger = comms_logger
        logger.info(f"OllamaAdapter ({self.current_model_id or 'Unconfigured'}): AICommsLogger instance set.")