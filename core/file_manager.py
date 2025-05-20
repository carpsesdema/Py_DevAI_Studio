import logging
import os
import pathlib
from typing import Optional, List, Tuple, Dict

from utils import constants
from .app_settings import AppSettings
from .project_manager import ProjectManager  # Assuming ProjectManager can provide active project root

logger = logging.getLogger(constants.APP_NAME)


class FileManager:
    def __init__(self, settings: AppSettings, project_manager: ProjectManager):
        self.settings = settings
        self.project_manager = project_manager
        logger.info("FileManager initialized.")

    def _get_project_root(self) -> Optional[pathlib.Path]:
        if self.project_manager:
            active_project = self.project_manager.get_active_project()
            if active_project and active_project.path:
                return pathlib.Path(active_project.path)
        logger.warning("FileManager: Could not determine active project root.")
        return None

    def _resolve_path(self, relative_path: str, ensure_within_project: bool = True) -> Optional[pathlib.Path]:
        project_root = self._get_project_root()
        if not project_root:
            logger.error("FileManager: Cannot resolve path, no active project root.")
            return None

        try:
            # Normalize the relative path to prevent directory traversal tricks
            normalized_relative_path = pathlib.Path(os.path.normpath(relative_path))
            if normalized_relative_path.is_absolute():  # Disallow absolute paths if relative is expected
                logger.error(
                    f"FileManager: Absolute path provided ('{relative_path}') where relative was expected within project.")
                return None

            abs_path = project_root.joinpath(normalized_relative_path).resolve()

            if ensure_within_project:
                if project_root not in abs_path.parents and abs_path != project_root:
                    logger.error(
                        f"FileManager: Path '{abs_path}' is outside the project root '{project_root}'. Operation denied.")
                    return None
            return abs_path
        except Exception as e:
            logger.error(f"FileManager: Error resolving path '{relative_path}' against root '{project_root}': {e}")
            return None

    def read_file(self, relative_file_path: str) -> Tuple[Optional[str], Optional[str]]:
        absolute_path = self._resolve_path(relative_file_path)
        if not absolute_path:
            return None, f"Invalid or disallowed path: {relative_file_path}"

        try:
            if not absolute_path.is_file():
                return None, f"File not found: {absolute_path}"

            content = absolute_path.read_text(encoding='utf-8')
            logger.info(f"Successfully read file: {absolute_path}")
            return content, None
        except FileNotFoundError:
            logger.warning(f"File not found during read: {absolute_path}")
            return None, f"File not found: {relative_file_path}"
        except UnicodeDecodeError as e:
            logger.error(f"Unicode decode error reading file {absolute_path}: {e}")
            return None, f"Encoding error reading file {relative_file_path}: {e}"
        except IOError as e:
            logger.error(f"IOError reading file {absolute_path}: {e}")
            return None, f"IO error reading file {relative_file_path}: {e}"
        except Exception as e:
            logger.exception(f"Unexpected error reading file {absolute_path}:")
            return None, f"Unexpected error reading {relative_file_path}: {e}"

    def write_file(self, relative_file_path: str, content: str, overwrite: bool = True) -> Tuple[bool, Optional[str]]:
        absolute_path = self._resolve_path(relative_file_path)
        if not absolute_path:
            return False, f"Invalid or disallowed path for writing: {relative_file_path}"

        try:
            if absolute_path.exists() and not overwrite:
                logger.warning(f"File exists and overwrite is False: {absolute_path}")
                return False, f"File already exists and overwrite not permitted: {relative_file_path}"

            if absolute_path.is_dir():
                logger.error(f"Cannot write file, path is a directory: {absolute_path}")
                return False, f"Path is a directory, cannot write file: {relative_file_path}"

            absolute_path.parent.mkdir(parents=True, exist_ok=True)
            absolute_path.write_text(content, encoding='utf-8')
            logger.info(f"Successfully wrote to file: {absolute_path}")
            return True, None
        except IOError as e:
            logger.error(f"IOError writing file {absolute_path}: {e}")
            return False, f"IO error writing file {relative_file_path}: {e}"
        except Exception as e:
            logger.exception(f"Unexpected error writing file {absolute_path}:")
            return False, f"Unexpected error writing {relative_file_path}: {e}"

    def create_directory(self, relative_dir_path: str) -> Tuple[bool, Optional[str]]:
        absolute_path = self._resolve_path(relative_dir_path)
        if not absolute_path:
            return False, f"Invalid or disallowed path for directory creation: {relative_dir_path}"

        try:
            if absolute_path.is_file():
                logger.error(f"Cannot create directory, path exists as a file: {absolute_path}")
                return False, f"Path exists as a file: {relative_dir_path}"

            absolute_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Successfully ensured directory exists: {absolute_path}")
            return True, None
        except IOError as e:
            logger.error(f"IOError creating directory {absolute_path}: {e}")
            return False, f"IO error creating directory {relative_dir_path}: {e}"
        except Exception as e:
            logger.exception(f"Unexpected error creating directory {absolute_path}:")
            return False, f"Unexpected error creating directory {relative_dir_path}: {e}"

    def list_directory_contents(self, relative_dir_path: str) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
        absolute_path = self._resolve_path(relative_dir_path)
        if not absolute_path:
            return None, f"Invalid or disallowed path for listing: {relative_dir_path}"

        if not absolute_path.is_dir():
            return None, f"Path is not a directory: {relative_dir_path}"

        contents = []
        try:
            for item in absolute_path.iterdir():
                item_type = "directory" if item.is_dir() else "file"
                contents.append({"name": item.name, "type": item_type, "path": str(item)})
            logger.info(f"Listed contents for directory: {absolute_path}")
            return contents, None
        except IOError as e:
            logger.error(f"IOError listing directory {absolute_path}: {e}")
            return None, f"IO error listing directory {relative_dir_path}: {e}"
        except Exception as e:
            logger.exception(f"Unexpected error listing directory {absolute_path}:")
            return None, f"Unexpected error listing directory {relative_dir_path}: {e}"

    def file_exists(self, relative_file_path: str) -> bool:
        absolute_path = self._resolve_path(relative_file_path,
                                           ensure_within_project=False)  # Allow checking anywhere if path is absolute
        if not absolute_path:
            return False
        return absolute_path.is_file()

    def directory_exists(self, relative_dir_path: str) -> bool:
        absolute_path = self._resolve_path(relative_dir_path, ensure_within_project=False)
        if not absolute_path:
            return False
        return absolute_path.is_dir()