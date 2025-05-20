# PyDevAI_Studio/core/app_settings.py
import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from utils import constants

logger = logging.getLogger(__name__)


class AppSettings:
    _default_settings: Dict[str, Any] = {
        "theme": "dark",
        "last_project_path": None,
        "llm_providers": {
            constants.LLMProvider.OLLAMA.value: {
                "host": "http://localhost:11434",
                "default_chat_model": "llama3:latest",
                "default_coding_model": "codellama:13b-instruct",
                "api_key": None,
            },
            constants.LLMProvider.GEMINI.value: {
                "api_key": None,
                "default_chat_model": "gemini-1.5-flash-latest",
                "default_coding_model": "gemini-1.5-pro-latest",
            },
            constants.LLMProvider.OPENAI.value: {
                "api_key": None,
                "default_chat_model": "gpt-4o",
                "default_coding_model": "gpt-4-turbo",
            },
        },
        "active_chat_llm_provider": constants.DEFAULT_CHAT_PROVIDER.value,
        "active_coding_llm_provider": constants.DEFAULT_CODING_PROVIDER.value,
        "chat_llm_temperature": 0.7,
        "coding_llm_temperature": 0.2,
        "custom_chat_llm_system_prompt": None,
        "custom_coding_llm_system_prompt": None,
        "ui_font_family": constants.DEFAULT_FONT_FAMILY,
        "ui_font_size": constants.DEFAULT_FONT_SIZE,
        "code_font_family": constants.CODE_FONT_FAMILY,
        "code_font_size": constants.CODE_FONT_SIZE,
        "rag_embedding_model": constants.DEFAULT_EMBEDDING_MODEL,
        "rag_top_k": constants.DEFAULT_RAG_TOP_K,
        "rag_chunk_size": constants.DEFAULT_RAG_CHUNK_SIZE,
        "rag_chunk_overlap": constants.DEFAULT_RAG_CHUNK_OVERLAP,
        "autosave_settings": True,
        "main_window_geometry": None,
        "main_window_state": None,
        "splitter_sizes_main": None,
        "splitter_sizes_code_log": None,
        "log_terminal_height": 200,
    }

    def __init__(self, settings_file_path: Optional[str] = None):
        self.settings_file_path = settings_file_path or constants.SETTINGS_FILE_PATH
        self._settings: Dict[str, Any] = {}
        self.load()

    def _ensure_nested_defaults(self, current_settings: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
        updated_settings = current_settings.copy()
        for key, default_value in defaults.items():
            if isinstance(default_value, dict):
                current_value = updated_settings.get(key)
                if isinstance(current_value, dict):
                    updated_settings[key] = self._ensure_nested_defaults(current_value, default_value)
                else:
                    updated_settings[key] = default_value.copy()
            elif key not in updated_settings:
                updated_settings[key] = default_value
        return updated_settings

    def load(self) -> None:
        try:
            if os.path.exists(self.settings_file_path):
                with open(self.settings_file_path, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                self._settings = self._ensure_nested_defaults(loaded_settings, self._default_settings)
                logger.info(f"Settings loaded from {self.settings_file_path}")
            else:
                self._settings = self._default_settings.copy()
                logger.info("Settings file not found. Loaded default settings.")
                self.save()
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.error(f"Error loading settings from {self.settings_file_path}: {e}. Using default settings.")
            self._settings = self._default_settings.copy()
        except Exception as e:
            logger.exception(f"Unexpected error loading settings: {e}. Using default settings.")
            self._settings = self._default_settings.copy()

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.settings_file_path), exist_ok=True)
            with open(self.settings_file_path, 'w', encoding='utf-8') as f:
                json.dump(self._settings, f, indent=4, ensure_ascii=False)
            logger.info(f"Settings saved to {self.settings_file_path}")
            return True
        except (IOError, OSError) as e:
            logger.error(f"Error saving settings to {self.settings_file_path}: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error saving settings: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split('.')
        value = self._settings
        try:
            for k in keys:
                if isinstance(value, dict):
                    value = value[k]
                else:
                    default_value_from_master = self._default_settings
                    for dk in keys:
                        if isinstance(default_value_from_master, dict):
                            default_value_from_master = default_value_from_master.get(dk, default)
                        else:
                            return default
                    return default_value_from_master
            return value
        except KeyError:
            default_value_from_master = self._default_settings
            for dk in keys:
                if isinstance(default_value_from_master, dict):
                    default_value_from_master = default_value_from_master.get(dk, default)
                else:
                    return default
            return default_value_from_master
        except Exception as e:
            logger.warning(f"Error getting setting '{key}': {e}. Returning default.")
            return default

    def set(self, key: str, value: Any) -> None:
        keys = key.split('.')
        s = self._settings
        for k in keys[:-1]:
            s = s.setdefault(k, {})
            if not isinstance(s, dict):
                logger.error(f"Cannot set value for '{key}': intermediate key '{k}' is not a dictionary.")
                return
        s[keys[-1]] = value
        if self.get("autosave_settings", True):
            self.save()

    def get_all_settings(self) -> Dict[str, Any]:
        return self._settings.copy()

    def get_llm_provider_settings(self, provider_name_str: str) -> Optional[Dict[str, Any]]:
        provider_key = provider_name_str
        if isinstance(provider_name_str, constants.LLMProvider):
            provider_key = provider_name_str.value

        providers = self.get("llm_providers", {})
        if isinstance(providers, dict):
            return providers.get(provider_key)
        return None

    def set_llm_provider_setting(self, provider_name_str: str, setting_key: str, value: Any) -> None:
        provider_key = provider_name_str
        if isinstance(provider_name_str, constants.LLMProvider):
            provider_key = provider_name_str.value

        current_providers = self.get("llm_providers", {})
        if not isinstance(current_providers, dict):
            current_providers = {}

        if provider_key not in current_providers or not isinstance(current_providers[provider_key], dict):
            current_providers[provider_key] = {}

        current_providers[provider_key][setting_key] = value
        self.set("llm_providers", current_providers)

    def get_active_chat_llm_config(self) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        provider_name = self.get("active_chat_llm_provider")
        if provider_name:
            provider_settings = self.get_llm_provider_settings(provider_name)
            if provider_settings and isinstance(provider_settings, dict):
                model_id = provider_settings.get("default_chat_model")
                return model_id, provider_settings
        return None, None

    def get_active_coding_llm_config(self) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        provider_name = self.get("active_coding_llm_provider")
        if provider_name:
            provider_settings = self.get_llm_provider_settings(provider_name)
            if provider_settings and isinstance(provider_settings, dict):
                model_id = provider_settings.get("default_coding_model")
                return model_id, provider_settings
        return None, None