# PyDevAI_Studio/core/llm_manager.py PART 1
import logging
import asyncio
import json
import re
from typing import Optional, Dict, Any, List, Tuple, AsyncGenerator

from PyQt6.QtCore import QObject, pyqtSignal

from utils import constants
from core.app_settings import AppSettings
from core.ai_comms_logger import AICommsLogger
from backends.base_adapter import LLMAdapterInterface, ChatMessage
from backends.ollama_adapter import OllamaAdapter
from backends.gemini_adapter import GeminiAdapter
from backends.openai_adapter import OpenAIAdapter


class LLMManager(QObject):
    chat_llm_response_received = pyqtSignal(str, bool)
    coding_llm_response_received = pyqtSignal(str, str, bool)
    coding_instructions_generated = pyqtSignal(dict, str)
    instruction_generation_failed = pyqtSignal(str, str)

    llm_error_occurred = pyqtSignal(str, str)
    active_llms_changed = pyqtSignal(str, str, bool)

    def __init__(self, settings: AppSettings, comms_logger: AICommsLogger, rag_service: Optional[Any]):
        super().__init__()
        self.settings = settings
        self.comms_logger = comms_logger
        self.rag_service = rag_service
        self.logger = logging.getLogger(constants.APP_NAME)

        self._adapters: Dict[str, LLMAdapterInterface] = {}
        self._active_chat_llm_provider_name: Optional[str] = None
        self._active_chat_llm_model_id: Optional[str] = None
        self._active_coding_llm_provider_name: Optional[str] = None
        self._active_coding_llm_model_id: Optional[str] = None

        self._chat_llm_temperature: float = self.settings.get("chat_llm_temperature", 0.7)
        self._coding_llm_temperature: float = self.settings.get("coding_llm_temperature", 0.2)

        self._initialize_adapters()

    def _initialize_adapters(self) -> None:
        self.logger.info("LLMManager initializing adapters...")

        ollama_settings = self.settings.get_llm_provider_settings(constants.LLMProvider.OLLAMA.value)
        if ollama_settings:
            self._adapters[constants.LLMProvider.OLLAMA.value] = OllamaAdapter(settings=ollama_settings)
            self._adapters[constants.LLMProvider.OLLAMA.value].set_comms_logger(self.comms_logger)

        gemini_settings = self.settings.get_llm_provider_settings(constants.LLMProvider.GEMINI.value)
        if gemini_settings:
            self._adapters[constants.LLMProvider.GEMINI.value] = GeminiAdapter(settings=gemini_settings)
            self._adapters[constants.LLMProvider.GEMINI.value].set_comms_logger(self.comms_logger)

        openai_settings = self.settings.get_llm_provider_settings(constants.LLMProvider.OPENAI.value)
        if openai_settings:
            self._adapters[constants.LLMProvider.OPENAI.value] = OpenAIAdapter(settings=openai_settings)
            self._adapters[constants.LLMProvider.OPENAI.value].set_comms_logger(self.comms_logger)

        self.logger.info(f"LLMManager initialized {len(self._adapters)} adapter(s).")

    async def load_configured_models(self) -> None:
        self.logger.info("LLMManager loading initially configured models...")

        chat_provider_name = self.settings.get("active_chat_llm_provider", constants.DEFAULT_CHAT_PROVIDER.value)
        chat_provider_settings = self.settings.get_llm_provider_settings(chat_provider_name)
        if chat_provider_settings:
            chat_model_id = chat_provider_settings.get("default_chat_model")
            chat_api_key = chat_provider_settings.get("api_key")
            if chat_model_id:
                await self.set_active_chat_llm(chat_provider_name, chat_model_id, chat_api_key)

        coding_provider_name = self.settings.get("active_coding_llm_provider", constants.DEFAULT_CODING_PROVIDER.value)
        coding_provider_settings = self.settings.get_llm_provider_settings(coding_provider_name)
        if coding_provider_settings:
            coding_model_id = coding_provider_settings.get("default_coding_model")
            coding_api_key = coding_provider_settings.get("api_key")
            if coding_model_id:
                await self.set_active_coding_llm(coding_provider_name, coding_model_id, coding_api_key)

        chat_temp_setting = self.settings.get("chat_llm_temperature")
        if isinstance(chat_temp_setting, (float, int)):
            self._chat_llm_temperature = float(chat_temp_setting)
        else:
            self._chat_llm_temperature = 0.7
            self.settings.set("chat_llm_temperature", self._chat_llm_temperature)

        coding_temp_setting = self.settings.get("coding_llm_temperature")
        if isinstance(coding_temp_setting, (float, int)):
            self._coding_llm_temperature = float(coding_temp_setting)
        else:
            self._coding_llm_temperature = 0.2
            self.settings.set("coding_llm_temperature", self._coding_llm_temperature)

    def get_adapter(self, provider_name: str) -> Optional[LLMAdapterInterface]:
        return self._adapters.get(provider_name)

    async def set_active_chat_llm(self, provider_name: str, model_id: str, api_key: Optional[str] = None) -> bool:
        adapter = self.get_adapter(provider_name)
        if not adapter:
            self.logger.error(f"No adapter found for chat LLM provider: {provider_name}")
            self.llm_error_occurred.emit("Chat", f"Adapter for {provider_name} not available.")
            return False

        system_prompt = self.settings.get("custom_chat_llm_system_prompt") or constants.CHAT_LLM_CODE_INSTRUCTION_SYSTEM_PROMPT
        success, message = await adapter.configure_model(model_id, api_key, system_prompt=system_prompt)
        if success:
            self._active_chat_llm_provider_name = provider_name
            self._active_chat_llm_model_id = model_id
            self.settings.set("active_chat_llm_provider", provider_name)
            self.settings.set_llm_provider_setting(provider_name, "default_chat_model", model_id)
            if api_key and provider_name != constants.LLMProvider.OLLAMA.value:
                self.settings.set_llm_provider_setting(provider_name, "api_key", api_key)

            self.logger.info(f"Active Chat LLM (Planner) set to: {provider_name} - {model_id}")
            self.active_llms_changed.emit(provider_name, model_id, True)
            return True
        else:
            self.logger.error(f"Failed to configure Chat LLM {provider_name} - {model_id}: {message}")
            self.llm_error_occurred.emit("Chat", f"Config failed for {model_id}: {message}")
            if self._active_chat_llm_provider_name == provider_name and self._active_chat_llm_model_id == model_id:
                self._active_chat_llm_provider_name = None
                self._active_chat_llm_model_id = None
            return False

    async def set_active_coding_llm(self, provider_name: str, model_id: str, api_key: Optional[str] = None) -> bool:
        adapter = self.get_adapter(provider_name)
        if not adapter:
            self.logger.error(f"No adapter found for coding LLM provider: {provider_name}")
            self.llm_error_occurred.emit("Coding", f"Adapter for {provider_name} not available.")
            return False

        system_prompt = self.settings.get("custom_coding_llm_system_prompt") or constants.CODING_LLM_SYSTEM_PROMPT
        success, message = await adapter.configure_model(model_id, api_key, system_prompt=system_prompt)
        if success:
            self._active_coding_llm_provider_name = provider_name
            self._active_coding_llm_model_id = model_id
            self.settings.set("active_coding_llm_provider", provider_name)
            self.settings.set_llm_provider_setting(provider_name, "default_coding_model", model_id)
            if api_key and provider_name != constants.LLMProvider.OLLAMA.value:
                self.settings.set_llm_provider_setting(provider_name, "api_key", api_key)

            self.logger.info(f"Active Coding LLM set to: {provider_name} - {model_id}")
            self.active_llms_changed.emit(provider_name, model_id, False)
            return True
        else:
            self.logger.error(f"Failed to configure Coding LLM {provider_name} - {model_id}: {message}")
            self.llm_error_occurred.emit("Coding", f"Config failed for {model_id}: {message}")
            if self._active_coding_llm_provider_name == provider_name and self._active_coding_llm_model_id == model_id:
                self._active_coding_llm_provider_name = None
                self._active_coding_llm_model_id = None
            return False

    def set_chat_llm_temperature(self, temperature: float):
        if 0.0 <= temperature <= 2.0:
            self._chat_llm_temperature = temperature
            self.settings.set("chat_llm_temperature", temperature)
            self.logger.info(f"Chat LLM temperature set to {temperature}")
        else:
            self.logger.warning(f"Invalid temperature value: {temperature}. Not set.")

    def set_coding_llm_temperature(self, temperature: float):
        if 0.0 <= temperature <= 2.0:
            self._coding_llm_temperature = temperature
            self.settings.set("coding_llm_temperature", temperature)
            self.logger.info(f"Coding LLM temperature set to {temperature}")
        else:
            self.logger.warning(f"Invalid temperature value for Coding LLM: {temperature}. Not set.")

    def get_active_chat_llm_info(self) -> Dict[str, Optional[str]]:
        model_id_full = self._active_chat_llm_model_id
        model_id_short = model_id_full.split('/')[-1].split(':')[-1] if model_id_full else None
        return {
            "provider_name": self._active_chat_llm_provider_name,
            "model_id": model_id_full,
            "model_id_short": model_id_short
        }

    def get_active_coding_llm_info(self) -> Dict[str, Optional[str]]:
        model_id_full = self._active_coding_llm_model_id
        model_id_short = model_id_full.split('/')[-1].split(':')[-1] if model_id_full else None
        return {
            "provider_name": self._active_coding_llm_provider_name,
            "model_id": model_id_full,
            "model_id_short": model_id_short
        }# PyDevAI_Studio/core/llm_manager.py PART 2
    async def send_to_chat_llm(self, messages: List[ChatMessage], request_id: str = "") -> None:
        if not self._active_chat_llm_provider_name or not self._active_chat_llm_model_id:
            self.logger.error("No active Chat LLM configured to send message.")
            self.chat_llm_response_received.emit("Error: Chat LLM not configured.", True)
            return

        adapter = self.get_adapter(self._active_chat_llm_provider_name)
        if not adapter or not adapter.is_configured():
            self.logger.error(f"Chat LLM adapter for {self._active_chat_llm_provider_name} not ready.")
            self.chat_llm_response_received.emit(f"Error: Chat LLM ({self._active_chat_llm_provider_name}) not ready.", True)
            return

        self.comms_logger.log(f"Sending to ChatLLM ({self._active_chat_llm_model_id}): {messages[-1].content[:50]}...", source="LLMManager")

        is_first_chunk = True
        try:
            async for chunk, error in adapter.get_response_stream(messages, temperature=self._chat_llm_temperature):
                if error:
                    self.logger.error(f"ChatLLM stream error: {error}")
                    self.chat_llm_response_received.emit(f"Error: {error}", True)
                    return
                if chunk:
                    self.chat_llm_response_received.emit(chunk, False)
                    is_first_chunk = False

            if not is_first_chunk:
                 self.chat_llm_response_received.emit("", True)
            elif is_first_chunk:
                 self.chat_llm_response_received.emit("", True)


        except Exception as e:
            self.logger.exception(f"Exception during send_to_chat_llm stream processing:")
            self.chat_llm_response_received.emit(f"Exception: {str(e)}", True)

    async def generate_coding_instructions_from_chat(
        self,
        user_request_message: ChatMessage,
        chat_history: List[ChatMessage],
        project_id: Optional[str] = None,
        request_id: str = ""
    ) -> None:
        if not self._active_chat_llm_provider_name or not self._active_chat_llm_model_id:
            self.logger.error("No active Chat LLM (Planner) configured for instruction generation.")
            self.instruction_generation_failed.emit("Error: Chat LLM (Planner) not configured.", request_id)
            return

        adapter = self.get_adapter(self._active_chat_llm_provider_name)
        if not adapter or not adapter.is_configured():
            self.logger.error(f"Chat LLM (Planner) adapter for {self._active_chat_llm_provider_name} not ready.")
            self.instruction_generation_failed.emit(f"Error: Chat LLM (Planner) ({self._active_chat_llm_provider_name}) not ready.", request_id)
            return

        rag_context_str = ""
        if self.rag_service and project_id and user_request_message.content:
            self.comms_logger.log(f"Fetching RAG context for instruction generation query: {user_request_message.content[:50]}...", source="LLMManager-Planner")
            rag_context_str, _ = await self.rag_service.get_formatted_context(
                query=user_request_message.content,
                project_id=project_id,
                is_modification_request=True
            )
            if rag_context_str:
                self.comms_logger.log(f"RAG context found for planner (length: {len(rag_context_str)}).", source="LLMManager-Planner")

        planner_messages: List[ChatMessage] = []
        if chat_history:
            planner_messages.extend(chat_history)

        planner_request_content_parts = [user_request_message.content]
        if rag_context_str:
            planner_request_content_parts.append("\n\n--- Relevant Project Context (from RAG) ---\n")
            planner_request_content_parts.append(rag_context_str)
            planner_request_content_parts.append("\n--- End of Project Context ---\n")
        planner_request_content_parts.append("\nPlease generate the structured JSON instructions for the CodingLLM based on our discussion and the provided context.")

        final_user_request_for_planner = ChatMessage(
            role="user",
            content="".join(planner_request_content_parts),
            image_data=user_request_message.image_data
        )
        planner_messages.append(final_user_request_for_planner)

        self.comms_logger.log(f"Sending to ChatLLM (Planner - {self._active_chat_llm_model_id}) for instruction generation: {user_request_message.content[:50]}...", source="LLMManager")

        full_response, error, _ = await adapter.get_response_complete(
            planner_messages,
            temperature=self._chat_llm_temperature
        )

        if error:
            self.logger.error(f"InstructionLLM error: {error}")
            self.instruction_generation_failed.emit(f"Error from Planner AI: {error}", request_id)
            return
        if not full_response:
            self.logger.error("InstructionLLM returned an empty response.")
            self.instruction_generation_failed.emit("Planner AI returned an empty response.", request_id)
            return

        self.comms_logger.log(f"ChatLLM (Planner) Raw Response: {full_response[:300]}...", source="LLMManager")

        try:
            json_match = re.search(r"```json\s*([\s\S]*?)\s*```", full_response, re.DOTALL)
            json_str_to_parse = ""
            if json_match:
                json_str_to_parse = json_match.group(1).strip()
            else:
                json_str_to_parse = full_response.strip()

            if not json_str_to_parse:
                raise ValueError("No JSON content found in the planner's response.")

            parsed_instructions = json.loads(json_str_to_parse, strict=False)

            if not isinstance(parsed_instructions, dict) or "files" not in parsed_instructions:
                raise ValueError("Parsed JSON is not a dictionary or missing 'files' key.")

            self.comms_logger.log(f"Successfully parsed instructions JSON. Files: {len(parsed_instructions.get('files', []))}", source="LLMManager")
            self.coding_instructions_generated.emit(parsed_instructions, request_id)

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to decode JSON from InstructionLLM: {e}\nResponse was: {full_response}")
            self.instruction_generation_failed.emit(f"Planner AI response was not valid JSON: {e}", request_id)
        except ValueError as e:
            self.logger.error(f"Invalid JSON structure from InstructionLLM: {e}\nResponse was: {full_response}")
            self.instruction_generation_failed.emit(f"Planner AI response had invalid structure: {e}", request_id)
        except Exception as e:
            self.logger.exception("Unexpected error parsing InstructionLLM JSON response:")
            self.instruction_generation_failed.emit(f"Unexpected error parsing planner response: {e}", request_id)

    async def generate_code_with_coding_llm(
            self,
            instructions_for_file: str,
            target_file_path: str,
            project_id: Optional[str] = None,
            existing_code: Optional[str] = None,
            request_id: str = ""
    ) -> None:
        if not self._active_coding_llm_provider_name or not self._active_coding_llm_model_id:
            self.logger.error("No active Coding LLM configured for code generation.")
            self.coding_llm_response_received.emit(target_file_path, "Error: Coding LLM not configured.", True)
            return

        adapter = self.get_adapter(self._active_coding_llm_provider_name)
        if not adapter or not adapter.is_configured():
            self.logger.error(f"Coding LLM adapter for {self._active_coding_llm_provider_name} not ready.")
            self.coding_llm_response_received.emit(target_file_path, f"Error: Coding LLM ({self._active_coding_llm_provider_name}) not ready.", True)
            return

        rag_context_str = ""
        rag_requested_match = re.search(r"\[RAG_EXAMPLES_REQUESTED_FOR_THIS_FILE:\s*(.*?)\]", instructions_for_file, re.IGNORECASE)
        if rag_requested_match and self.rag_service and project_id:
            rag_query_focus_path = rag_requested_match.group(1).strip()
            if not rag_query_focus_path or rag_query_focus_path.lower() == "true":
                rag_query_focus_path = target_file_path

            self.comms_logger.log(f"Coder needs RAG context for {rag_query_focus_path} in project {project_id}...", source="LLMManager-Coder")
            rag_query = f"Relevant code examples for implementing: {target_file_path}. Details: {instructions_for_file[:200]}"
            rag_context_str, _ = await self.rag_service.get_formatted_context(
                query=rag_query,
                project_id=project_id,
                focus_paths=[rag_query_focus_path],
                is_modification_request=True
            )
            if rag_context_str:
                self.comms_logger.log(f"RAG context found for coder (length: {len(rag_context_str)}).", source="LLMManager-Coder")
                instructions_for_file = re.sub(r"\[RAG_EXAMPLES_REQUESTED_FOR_THIS_FILE:.*?\]", "", instructions_for_file, flags=re.IGNORECASE).strip()

        prompt_parts = [instructions_for_file]
        if rag_context_str:
            prompt_parts.append("\n\nRelevant context from the project (use this to inform your code generation):\n---\n")
            prompt_parts.append(rag_context_str)
            prompt_parts.append("\n---\n")

        if existing_code:
            prompt_parts.append(f"\nThe file '{target_file_path}' exists. Its current content is:\n```python\n{existing_code}\n```\n")
            prompt_parts.append("You MUST use this original content as the foundation and apply the necessary modifications based on the instructions.")
        else:
            prompt_parts.append(f"\nThe file '{target_file_path}' is new. Create it from scratch based on the instructions.")

        prompt_parts.append(f"\nRemember to output ONLY the raw Python code for '{target_file_path}'.")
        final_prompt_for_coder = "".join(prompt_parts)

        coding_messages = [ChatMessage(role="user", content=final_prompt_for_coder)]

        self.comms_logger.log(f"Sending to CodingLLM ({self._active_coding_llm_model_id}) for '{target_file_path}': {instructions_for_file[:70]}...", source="LLMManager")

        full_code_response = ""
        try:
            async for chunk, error in adapter.get_response_stream(coding_messages, temperature=self._coding_llm_temperature):
                if error:
                    self.logger.error(f"CodingLLM stream error for '{target_file_path}': {error}")
                    self.coding_llm_response_received.emit(target_file_path, f"Error: {error}", True)
                    return
                if chunk:
                    full_code_response += chunk
            self.comms_logger.log(f"CodingLLM response for '{target_file_path}' (length: {len(full_code_response)}): {full_code_response[:100]}...", source="LLMManager")
            self.coding_llm_response_received.emit(target_file_path, full_code_response, False)

        except Exception as e:
            self.logger.exception(f"Exception during generate_code_with_coding_llm for '{target_file_path}':")
            self.coding_llm_response_received.emit(target_file_path, f"Exception: {str(e)}", True)

    async def get_available_models_for_provider(self, provider_name: str, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        adapter = self.get_adapter(provider_name)
        if not adapter:
            self.logger.warning(f"Cannot list models: No adapter for provider {provider_name}")
            return []

        models_info, error = await adapter.list_available_models(api_key=api_key)
        if error:
            self.logger.error(f"Error listing models for {provider_name}: {error}")
            self.llm_error_occurred.emit(provider_name, f"Failed to list models: {error}")
            return []
        return models_info