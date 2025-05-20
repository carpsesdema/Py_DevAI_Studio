import asyncio
import logging
import os
from typing import List, Optional, AsyncGenerator, Dict, Any, Tuple

try:
    import google.generativeai as genai
    from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
    from google.api_core import exceptions as google_exceptions

    GEMINI_AVAILABLE = True
except ImportError:
    genai = None
    HarmCategory = None
    HarmBlockThreshold = None
    GenerationConfig = None
    google_exceptions = None
    GEMINI_AVAILABLE = False

from .base_adapter import LLMAdapterInterface, ChatMessage

logger = logging.getLogger(__name__)


class GeminiAdapter(LLMAdapterInterface):

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        self.model: Optional[genai.GenerativeModel] = None
        self.current_model_id: Optional[str] = None
        self.system_prompt_parts: Optional[List[Dict[str, str]]] = None
        self._is_configured: bool = False
        self._last_error: Optional[str] = None
        self._comms_logger: Optional[Any] = None
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0
        self._api_key_used_for_configure: Optional[str] = None

        if not GEMINI_AVAILABLE:
            self._last_error = "Google Generative AI library not found. Please install it: pip install google-generativeai"
            logger.critical(self._last_error)
            return

    async def configure_model(self, model_id: str, api_key: Optional[str] = None,
                              model_parameters: Optional[Dict[str, Any]] = None,
                              system_prompt: Optional[str] = None) -> Tuple[bool, str]:
        self._is_configured = False
        self._last_error = None
        self.model = None
        self._prompt_tokens = 0
        self._completion_tokens = 0

        if not GEMINI_AVAILABLE:
            self._last_error = "Google Generative AI library is not installed."
            return False, self._last_error

        effective_api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

        if not effective_api_key:
            self._last_error = "Gemini API key not provided and not found in environment variables (GEMINI_API_KEY, GOOGLE_API_KEY)."
            logger.error(self._last_error)
            return False, self._last_error

        if not model_id:
            self._last_error = "Model ID is required for Gemini configuration."
            logger.error(self._last_error)
            return False, self._last_error

        if self._api_key_used_for_configure != effective_api_key:
            try:
                genai.configure(api_key=effective_api_key)
                self._api_key_used_for_configure = effective_api_key
                logger.info("Gemini API key configured with google.generativeai library.")
            except Exception as e:
                self._last_error = f"Failed to configure Gemini API key with library: {e}"
                logger.error(self._last_error)
                return False, self._last_error

        self.current_model_id = model_id

        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        system_instruction = None
        if system_prompt and self.supports_system_prompt():
            system_instruction = system_prompt
            logger.info(f"Using system instruction for Gemini model {model_id}.")
        elif system_prompt:
            logger.warning(
                f"System prompt provided for Gemini model {model_id}, but this adapter version may not fully support it via system_instruction param for all models. It will be prepended to history if needed.")
            self.system_prompt_parts = [{"role": "user", "parts": [system_prompt]},
                                        {"role": "model", "parts": ["Okay, I will adhere to that system prompt."]}]

        try:
            self.model = genai.GenerativeModel(
                model_name=model_id,
                safety_settings=safety_settings,
                system_instruction=system_instruction
            )
            self._is_configured = True
            logger.info(
                f"GeminiAdapter configured for model '{model_id}'. System prompt {'used directly' if system_instruction else ('will be prepended' if self.system_prompt_parts else 'not set')}.")
            return True, f"Successfully configured Gemini model: {model_id}"
        except Exception as e:
            self._last_error = f"Failed to instantiate Gemini GenerativeModel '{model_id}': {e}"
            logger.error(f"Gemini configuration error for model {model_id}: {e}")
            self.current_model_id = None
            return False, self._last_error

    def is_configured(self) -> bool:
        return self._is_configured and self.model is not None

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
        if not self.is_configured() or not self.model:
            error_msg = "GeminiAdapter is not configured."
            logger.error(error_msg)
            yield "", error_msg
            return

        self._last_error = None
        self._prompt_tokens = 0
        self._completion_tokens = 0

        api_history = []
        if self.system_prompt_parts and not self.model.system_instruction:  # If system prompt is handled by prepending
            api_history.extend(self.system_prompt_parts)

        for msg in messages:
            parts_content = []
            if msg.content:
                parts_content.append(msg.content)
            if msg.image_data and self.supports_images():
                for img_item in msg.image_data:  # Assuming img_item["data"] is base64
                    try:
                        from PIL import Image
                        import io
                        import base64
                        img_bytes = base64.b64decode(img_item["data"])
                        img = Image.open(io.BytesIO(img_bytes))
                        parts_content.append(img)
                    except Exception as e_img:
                        logger.error(f"Could not process image data for Gemini: {e_img}")

            if parts_content:
                api_history.append({'role': 'model' if msg.role == 'assistant' else msg.role, 'parts': parts_content})

        generation_config_dict: Dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            generation_config_dict["max_output_tokens"] = max_tokens
        if top_p is not None:
            generation_config_dict["top_p"] = top_p
        if stop_sequences is not None:
            generation_config_dict["stop_sequences"] = stop_sequences

        effective_generation_config = GenerationConfig(**generation_config_dict)

        if self._comms_logger:
            log_msg_prompt = f"Gemini Request to '{self.current_model_id}': History items: {len(api_history)}, Config: {generation_config_dict}"
            self._comms_logger.log(log_msg_prompt, source="GeminiAdapter")

        try:
            stream_response = await self.model.generate_content_async(
                api_history,
                stream=True,
                generation_config=effective_generation_config
            )

            full_response_content = ""
            async for chunk in stream_response:
                if self._comms_logger:
                    self._comms_logger.log(
                        f"Gemini Raw Chunk: Parts: {len(chunk.parts)}, Text(first part): '{chunk.parts[0].text[:70] if chunk.parts and chunk.parts[0].text else 'N/A'}'",
                        source=f"GeminiStream ({self.current_model_id})")

                chunk_text = ""
                try:
                    if chunk.parts:
                        for part in chunk.parts:
                            if hasattr(part, 'text'):
                                chunk_text += part.text
                except Exception as e_part:  # Fallback for unexpected chunk structure
                    logger.warning(f"Error processing Gemini chunk part: {e_part}, chunk: {chunk}")
                    chunk_text = ""  # Or some error marker

                if chunk_text:
                    full_response_content += chunk_text
                    yield chunk_text, None

                if stream_response._done:  # Accessing internal flag, might change
                    break

            if self._comms_logger:
                self._comms_logger.log(f"Gemini Response Full: '{full_response_content[:200]}...'",
                                       source="GeminiAdapter")

            if hasattr(stream_response, 'usage_metadata') and stream_response.usage_metadata:
                usage = stream_response.usage_metadata
                self._prompt_tokens = getattr(usage, 'prompt_token_count', 0)
                self._completion_tokens = getattr(usage, 'candidates_token_count',
                                                  0)  # Sum of tokens from all candidates
            elif hasattr(stream_response, 'prompt_feedback') and stream_response.prompt_feedback and \
                    hasattr(stream_response.prompt_feedback,
                            'usage_metadata') and stream_response.prompt_feedback.usage_metadata:  # For some errors, it's nested
                usage = stream_response.prompt_feedback.usage_metadata
                self._prompt_tokens = getattr(usage, 'prompt_token_count', 0)
                self._completion_tokens = getattr(usage, 'candidates_token_count', 0)


        except google_exceptions.GoogleAPIError as e:
            self._last_error = f"Gemini API Error: {e.__class__.__name__} - {e}"
            logger.error(self._last_error)
            yield "", self._last_error
        except Exception as e:
            self._last_error = f"Unexpected error during Gemini stream: {type(e).__name__} - {e}"
            logger.exception("GeminiAdapter stream failed:")
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
        final_error_message: Optional[str] = None

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
        if not GEMINI_AVAILABLE:
            self._last_error = "Google Generative AI library is not installed."
            return [], self._last_error

        effective_api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not effective_api_key and not self._api_key_used_for_configure:
            self._last_error = "API key required to list Gemini models. Provide one or configure adapter first."
            logger.warning(self._last_error)
            return [], self._last_error

        if effective_api_key and self._api_key_used_for_configure != effective_api_key:
            try:
                genai.configure(api_key=effective_api_key)
                logger.info("Gemini API key re-configured for list_available_models with new key.")
            except Exception as e_cfg:
                self._last_error = f"Failed to configure new API key for listing models: {e_cfg}"
                logger.error(self._last_error)
                return [], self._last_error

        self._last_error = None
        models_info = []
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    model_details = {
                        "id": m.name,
                        "name": m.display_name,
                        "provider": "Google Gemini",
                        "description": m.description,
                        "version": m.version,
                        "input_token_limit": m.input_token_limit,
                        "output_token_limit": m.output_token_limit,
                    }
                    models_info.append(model_details)
            return models_info, None
        except Exception as e:
            self._last_error = f"Failed to list Gemini models: {type(e).__name__} - {e}"
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
        # Gemini API supports system_instruction in GenerativeModel constructor
        return True

    def supports_images(self) -> bool:
        # Check current_model_id for vision capabilities
        if self.current_model_id:
            return "gemini-pro-vision" in self.current_model_id.lower() or \
                "gemini-1.5-pro" in self.current_model_id.lower() or \
                "gemini-1.5-flash" in self.current_model_id.lower()  # Add other vision model names
        return False

    def set_comms_logger(self, comms_logger: Any) -> None:
        self._comms_logger = comms_logger
        logger.info(f"GeminiAdapter ({self.current_model_id or 'Unconfigured'}): AICommsLogger instance set.")