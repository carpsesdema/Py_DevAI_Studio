import logging
import os
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, NamedTuple, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from utils import constants
from core.app_settings import AppSettings

logger = logging.getLogger(constants.APP_NAME)


class Project(NamedTuple):
    id: str
    name: str
    path: str
    last_opened: str
    metadata: Dict[str, Any] = {}
    chat_history: List[Dict[str, Any]] = []


class ProjectManager(QObject):
    project_list_updated = pyqtSignal(dict)
    active_project_changed = pyqtSignal(str)
    active_project_history_loaded = pyqtSignal(list)

    _PROJECT_METADATA_FILE_IN_PROJECT_DIR = ".pydevai_project_meta.json"
    _PROJECT_CHAT_HISTORY_FILE_IN_PROJECT_DIR = ".pydevai_chat_history.json"

    def __init__(self, settings: AppSettings):
        super().__init__()
        self.settings = settings
        self._projects: Dict[str, Project] = {}
        self._active_project_id: Optional[str] = None

        self._load_projects_list_from_settings()
        self._set_initial_active_project()
        logger.info("ProjectManager initialized.")

    def _load_projects_list_from_settings(self) -> None:
        projects_data_from_settings = self.settings.get("managed_projects_list", [])
        if not isinstance(projects_data_from_settings, list):
            projects_data_from_settings = []

        loaded_projects_count = 0
        valid_projects_for_settings_update: List[Dict[str, Any]] = []

        for project_entry_dict in projects_data_from_settings:
            if isinstance(project_entry_dict, dict) and "id" in project_entry_dict and "path" in project_entry_dict:
                project_path_str = str(project_entry_dict["path"])
                if not os.path.isdir(project_path_str):
                    logger.warning(
                        f"Project path '{project_path_str}' for project ID '{project_entry_dict['id']}' no longer exists or is not a directory. Removing from managed list.")
                    continue

                project_id_str = str(project_entry_dict["id"])
                project_name_str = str(project_entry_dict.get("name", os.path.basename(project_path_str)))
                last_opened_str = str(project_entry_dict.get("last_opened", ""))

                metadata_from_file, chat_history_from_file = self._load_project_specific_data_from_files(
                    project_path_str)

                final_metadata = project_entry_dict.get("metadata", {})
                if metadata_from_file:  # Prioritize file if it exists
                    final_metadata.update(metadata_from_file)

                project = Project(
                    id=project_id_str,
                    name=project_name_str,
                    path=project_path_str,
                    last_opened=last_opened_str,
                    metadata=final_metadata,
                    chat_history=chat_history_from_file
                )
                self._projects[project.id] = project
                valid_projects_for_settings_update.append(project_entry_dict)
                loaded_projects_count += 1
            else:
                logger.warning(f"Skipping invalid project entry in settings: {project_entry_dict}")

        if len(valid_projects_for_settings_update) != len(projects_data_from_settings):
            self.settings.set("managed_projects_list",
                              valid_projects_for_settings_update)  # Update settings if invalid entries were removed

        if loaded_projects_count > 0:
            logger.info(f"Loaded {loaded_projects_count} projects from settings list.")
        self.project_list_updated.emit(self.get_project_name_map())

    def _save_projects_list_to_settings(self) -> None:
        projects_data_for_settings = []
        for project_obj in self._projects.values():
            projects_data_for_settings.append({
                "id": project_obj.id,
                "name": project_obj.name,
                "path": project_obj.path,
                "last_opened": project_obj.last_opened,
                "metadata": project_obj.metadata
            })
        self.settings.set("managed_projects_list", projects_data_for_settings)
        logger.info(f"Saved {len(projects_data_for_settings)} projects to settings list.")

    def _load_project_specific_data_from_files(self, project_base_path: str) -> Tuple[
        Dict[str, Any], List[Dict[str, Any]]]:
        metadata: Dict[str, Any] = {}
        chat_history: List[Dict[str, Any]] = []

        meta_file = os.path.join(project_base_path, self._PROJECT_METADATA_FILE_IN_PROJECT_DIR)
        history_file = os.path.join(project_base_path, self._PROJECT_CHAT_HISTORY_FILE_IN_PROJECT_DIR)

        if os.path.exists(meta_file):
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict): metadata = data.get("project_specific_metadata", {})
            except Exception as e:
                logger.warning(f"Could not load project metadata file '{meta_file}': {e}")

        if os.path.exists(history_file):
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list): chat_history = data
            except Exception as e:
                logger.warning(f"Could not load project chat history file '{history_file}': {e}")
        return metadata, chat_history

    def _save_project_specific_data_to_files(self, project: Project) -> None:
        meta_file = os.path.join(project.path, self._PROJECT_METADATA_FILE_IN_PROJECT_DIR)
        history_file = os.path.join(project.path, self._PROJECT_CHAT_HISTORY_FILE_IN_PROJECT_DIR)

        try:
            meta_data_to_save = {
                "project_id": project.id,
                "project_name": project.name,
                "project_path_at_save": project.path,
                "project_specific_metadata": project.metadata,
                "saved_by_app_version": f"{constants.APP_NAME} {constants.APP_VERSION}"
            }
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(meta_data_to_save, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save project metadata to '{meta_file}': {e}")

        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(project.chat_history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save project chat history to '{history_file}': {e}")

    def _set_initial_active_project(self) -> None:
        last_active_id = self.settings.get("last_active_project_id")
        if last_active_id and last_active_id in self._projects:
            self.set_active_project_id(last_active_id)
        elif self._projects:
            sorted_projects = sorted(self._projects.values(), key=lambda p: p.last_opened or "0", reverse=True)
            if sorted_projects:
                self.set_active_project_id(sorted_projects[0].id)
        else:
            logger.info("No projects available, no initial active project set.")
            self.active_project_changed.emit("")  # Signal no active project

    def create_or_add_project(self, path: str, name: Optional[str] = None) -> Optional[Project]:
        normalized_path = os.path.normpath(path)
        if not os.path.isdir(normalized_path):
            try:
                os.makedirs(normalized_path, exist_ok=True)
                logger.info(f"Created project directory during add: {normalized_path}")
            except OSError as e:
                logger.error(f"Failed to create directory for new project at {normalized_path}: {e}")
                return None

        for p_obj in self._projects.values():
            if p_obj.path == normalized_path:
                logger.info(f"Project at path '{normalized_path}' already managed. Activating.")
                self.set_active_project_id(p_obj.id)
                return p_obj

        project_name_to_use = name if name else os.path.basename(normalized_path)

        # Check for name collision if a new name is provided or derived
        for p_obj in self._projects.values():
            if p_obj.name.lower() == project_name_to_use.lower():
                logger.warning(
                    f"A project named '{project_name_to_use}' already exists. Please use a unique name or add the existing project by its path if different.")
                return None  # Or prompt user for a new name

        project_id_str = str(uuid.uuid4())
        current_timestamp = datetime.datetime.now().isoformat()

        metadata_from_file, chat_history_from_file = self._load_project_specific_data_from_files(normalized_path)

        new_project = Project(
            id=project_id_str,
            name=project_name_to_use,
            path=normalized_path,
            last_opened=current_timestamp,
            metadata=metadata_from_file,
            chat_history=chat_history_from_file
        )
        self._projects[project_id_str] = new_project
        self._save_project_specific_data_to_files(new_project)
        self._save_projects_list_to_settings()
        self.project_list_updated.emit(self.get_project_name_map())
        self.set_active_project_id(project_id_str)
        logger.info(
            f"Added/Created and activated project: {project_name_to_use} (ID: {project_id_str}) at {normalized_path}")
        return new_project

    def remove_project_from_list(self, project_id: str, delete_on_disk: bool = False) -> bool:
        if project_id not in self._projects:
            logger.warning(f"Project ID '{project_id}' not found. Cannot remove.")
            return False

        project_to_remove = self._projects.pop(project_id)
        logger.info(f"Removed project from list: {project_to_remove.name} (ID: {project_id})")
        self._save_projects_list_to_settings()
        self.project_list_updated.emit(self.get_project_name_map())

        if delete_on_disk:
            try:
                meta_file = os.path.join(project_to_remove.path, self._PROJECT_METADATA_FILE_IN_PROJECT_DIR)
                hist_file = os.path.join(project_to_remove.path, self._PROJECT_CHAT_HISTORY_FILE_IN_PROJECT_DIR)
                if os.path.exists(meta_file): os.remove(meta_file)
                if os.path.exists(hist_file): os.remove(hist_file)
                # Optionally delete RAG collection too via RAGService
                logger.info(f"Deleted on-disk metadata/history for project {project_to_remove.name}")
            except Exception as e:
                logger.error(f"Error deleting on-disk files for project {project_to_remove.name}: {e}")

        if self._active_project_id == project_id:
            self._active_project_id = None
            self._set_initial_active_project()
        return True

    def set_active_project_id(self, project_id: Optional[str]) -> None:
        if project_id and project_id in self._projects:
            if self._active_project_id != project_id:
                self._active_project_id = project_id
                self._projects[project_id] = self._projects[project_id]._replace(
                    last_opened=datetime.datetime.now().isoformat())
                self.settings.set("last_active_project_id", project_id)
                self._save_projects_list_to_settings()  # Save updated last_opened
                logger.info(f"Active project set to: {self._projects[project_id].name} (ID: {project_id})")
                self.active_project_changed.emit(project_id)
                self.active_project_history_loaded.emit(self.get_chat_history(project_id))
        elif not project_id and self._active_project_id is not None:
            self._active_project_id = None
            self.settings.set("last_active_project_id", None)
            logger.info("Active project cleared.")
            self.active_project_changed.emit("")
            self.active_project_history_loaded.emit([])
        elif project_id and project_id not in self._projects:
            logger.warning(f"Attempted to set active project to non-existent ID: {project_id}")

    def get_active_project(self) -> Optional[Project]:
        return self._projects.get(self._active_project_id) if self._active_project_id else None

    def get_active_project_id(self) -> Optional[str]:
        return self._active_project_id

    def get_project_by_id(self, project_id: str) -> Optional[Project]:
        return self._projects.get(project_id)

    def get_all_managed_projects(self) -> List[Project]:
        return sorted(list(self._projects.values()), key=lambda p: p.name.lower())

    def get_project_name_map(self) -> Dict[str, str]:
        return {pid: p.name for pid, p in self._projects.items()}

    def get_chat_history(self, project_id: Optional[str]) -> List[Dict[str, Any]]:
        target_id = project_id or self._active_project_id
        if target_id and target_id in self._projects:
            return list(self._projects[target_id].chat_history)  # Return a copy
        return []

    def add_message_to_history(self, project_id: Optional[str], message_dict: Dict[str, Any]) -> None:
        target_id = project_id or self._active_project_id
        if target_id and target_id in self._projects:
            self._projects[target_id].chat_history.append(message_dict)
            self._save_project_specific_data_to_files(self._projects[target_id])  # Save history to its file
            if target_id == self._active_project_id:
                self.active_project_history_loaded.emit(self.get_chat_history(target_id))  # Notify UI if active
        else:
            logger.warning(f"Cannot add message, project ID '{target_id}' not found or no active project.")

    def clear_chat_history(self, project_id: Optional[str]) -> None:
        target_id = project_id or self._active_project_id
        if target_id and target_id in self._projects:
            self._projects[target_id] = self._projects[target_id]._replace(chat_history=[])
            self._save_project_specific_data_to_files(self._projects[target_id])
            logger.info(f"Chat history cleared for project: {self._projects[target_id].name}")
            if target_id == self._active_project_id:
                self.active_project_history_loaded.emit([])
        else:
            logger.warning(f"Cannot clear history, project ID '{target_id}' not found or no active project.")