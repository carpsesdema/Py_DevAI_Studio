# utils/constants.py
import os
import sys
import logging
from enum import Enum

logger = logging.getLogger(__name__) # Use __name__ for module-specific logger

APP_NAME = "PyDevAI Studio"
APP_VERSION = "0.1.0-alpha"
APP_AUTHOR = "Your Name/Company" # Replace with actual author/company

def get_base_dir():
    """Determines the base directory of the application."""
    if getattr(sys, 'frozen', False):
        # If the application is run as a bundle/frozen executable (e.g., PyInstaller)
        return os.path.dirname(sys.executable)
    # If run as a normal script
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # Up two levels from utils/

APP_BASE_DIR = get_base_dir()

# --- Common Directories ---
ASSETS_DIR_NAME = "assets"
ASSETS_DIR = os.path.join(APP_BASE_DIR, ASSETS_DIR_NAME)

USER_DATA_DIR_NAME = ".pydevai_studio" # Hidden directory in user's home
USER_DATA_BASE_DIR = os.path.join(os.path.expanduser("~"), USER_DATA_DIR_NAME)

LOG_DIR_NAME = "logs"
LOG_DIR = os.path.join(USER_DATA_BASE_DIR, LOG_DIR_NAME)

RAG_COLLECTIONS_DIR_NAME = "rag_collections"
RAG_COLLECTIONS_DIR = os.path.join(USER_DATA_BASE_DIR, RAG_COLLECTIONS_DIR_NAME)

SETTINGS_FILE_NAME = "settings.json"
SETTINGS_FILE_PATH = os.path.join(USER_DATA_BASE_DIR, SETTINGS_FILE_NAME)

# --- Ensure Core Directories Exist ---
try:
    os.makedirs(USER_DATA_BASE_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(RAG_COLLECTIONS_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True) # Also ensure assets dir (though usually part of repo)
except OSError as e:
    # Use basic print for critical startup errors before logging might be fully set up
    print(f"CRITICAL ERROR: Could not create required directory: {e}", file=sys.stderr)
    # Depending on severity, might want to sys.exit() here


# --- Logging Configuration ---
LOG_LEVEL_STR = "DEBUG" # Default log level (e.g., "DEBUG", "INFO", "WARNING")
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR.upper(), logging.INFO)
LOG_FORMAT = '%(asctime)s - %(name)s - [%(levelname)s] - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s'
LOG_FILE_NAME = "pydevai_studio.log"
LOG_FILE_PATH = os.path.join(LOG_DIR, LOG_FILE_NAME)


# --- LLM Configuration ---
class LLMProvider(Enum):
    OLLAMA = "Ollama"
    GEMINI = "Google Gemini"
    OPENAI = "OpenAI" # Placeholder for future

DEFAULT_CHAT_PROVIDER = LLMProvider.OLLAMA # Example default
DEFAULT_CODING_PROVIDER = LLMProvider.OLLAMA # Example default

CHAT_LLM_CODE_INSTRUCTION_SYSTEM_PROMPT = """
You are a Planner AI. Your role is to assist the user in breaking down their Python programming tasks into clear, actionable steps for a specialized Coding LLM.
Based on the user's request and our conversation, you must generate a precise and detailed set of instructions for the Coding LLM.
The Coding LLM will only see your instructions and will output raw Python code for a single file or code block.

Consider the following when formulating instructions:
- Target file path (if applicable).
- Whether it's a new file or a modification. If modifying, clearly state what needs to change.
- Required classes, functions, methods, and their signatures (including type hints).
- Core logic and algorithms to be implemented.
- Necessary imports.
- Data structures to be used.
- Error handling requirements.
- Adherence to PEP 8 and other quality standards.
- Any relevant context from the user's project or RAG system that should be considered.

Your response MUST be a JSON object with the following structure:
{
  "project_goal": "Brief description of the overall goal.",
  "files": [
    {
      "file_path": "path/to/file.py",
      "action": "create_or_modify",
      "instructions": "Detailed instructions for this file..."
    }
    // ... more files
  ],
  "overall_notes": "General notes or next steps."
}
Ensure the instructions for each file are self-contained and very detailed.
"""

CODING_LLM_SYSTEM_PROMPT = """
You are an expert Python Code Generation AI. Your sole purpose is to generate clean, efficient, correct, and professional-grade Python code based on the instructions provided.

**Strict Guidelines for Code Generation:**

1.  **Output Raw Code Only:** Your entire response for a code generation task MUST BE ONLY the raw Python code for the requested file or code block. Do NOT include any Markdown formatting (like ```python ... ```), explanations, comments outside the code itself, or any conversational text.
2.  **PEP 8 Compliance:** All generated Python code must strictly adhere to PEP 8 style guidelines.
3.  **Type Hinting (PEP 484):** Provide type hints for all function arguments, return types, and important variables.
4.  **Docstrings (PEP 257):** Write comprehensive Google-style docstrings for all modules, classes, functions, and methods.
5.  **Clarity and Readability:** Prioritize writing code that is easy to understand and maintain.
6.  **Correctness:** Ensure the code is syntactically correct and logically implements the requirements.
7.  **Completeness:** Ensure all syntax is complete (e.g., matching parentheses, brackets, braces).

Follow the instructions meticulously. Do not add features or functionality not explicitly requested.
"""

# --- UI Appearance & Assets ---
DEFAULT_FONT_FAMILY = "Segoe UI"
DEFAULT_FONT_SIZE = 10
CODE_FONT_FAMILY = "JetBrains Mono" # Ensure this font is available or use fallback like "Consolas", "Courier New"
CODE_FONT_SIZE = 9
LOADING_GIF_FILENAME = "loading.gif"
COMPLETED_ICON_FILENAME = "loading_complete.png" # Ensure this exists in assets

# --- RAG & File Handling Constants ---
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_RAG_CHUNK_SIZE = 1000 # From AppSettings defaults
DEFAULT_RAG_CHUNK_OVERLAP = 200 # From AppSettings defaults
DEFAULT_RAG_TOP_K = 5 # Increased from AvA's 3, matches AppSettings
GLOBAL_RAG_COLLECTION_ID = "pydevai_studio_global_rag_v1"
GLOBAL_CONTEXT_DISPLAY_NAME = "PyDevAI Global Knowledge"

RAG_MAX_FILE_SIZE_MB = 50
MAX_SCAN_DEPTH = 10
ALLOWED_TEXT_EXTENSIONS = {
    '.txt', '.py', '.md', '.json', '.js', '.html', '.css', '.c', '.cpp', '.h', '.hpp',
    '.java', '.cs', '.xml', '.yaml', '.yml', '.sh', '.bat', '.ps1', '.log',
    '.csv', '.tsv', '.ini', '.cfg', '.sql', '.rb', '.php', '.go', '.rs', '.swift',
    '.kt', '.kts', '.scala', '.lua', '.pl', '.pm', '.r', '.dart', '.tex', '.toml',
    '.pdf', '.docx' # Supported by FileHandlerService
}
DEFAULT_IGNORED_DIRS = { # More comprehensive ignore list
    '.git', '__pycache__', '.venv', 'venv', '.env', 'env', 'target',
    'node_modules', 'build', 'dist', '.vscode', '.idea', '.pytest_cache',
    'site-packages', '.mypy_cache', 'lib', 'include', 'bin', 'Scripts', '.dist',
    '.history', '.vscode-test', '.idea_modules', '*.egg-info', '*.tox', '.nox',
    'docs', 'doc', 'examples', 'samples', 'nbproject', 'nbbuild', 'nbdist',
    'target', 'out', 'logs', # Common build/log output dirs
    '.DS_Store', 'Thumbs.db', # OS-specific
    '.cache', # Common cache directory name
}

# --- Project Specific Files ---
PROJECT_CONFIG_FILE_NAME = ".pydevai_project" # For project specific settings if needed

# --- UI Theme/Color Constants (Refined from AvA's style) ---
USER_BUBBLE_COLOR_HEX = "#0b93f6"
USER_TEXT_COLOR_HEX = "#FFFFFF"

ASSISTANT_BUBBLE_COLOR_HEX = "#3c3f41"
ASSISTANT_TEXT_COLOR_HEX = "#dcdcdc"

SYSTEM_BUBBLE_COLOR_HEX = "#4a4e51"
SYSTEM_TEXT_COLOR_HEX = "#aabbcc"

ERROR_BUBBLE_COLOR_HEX = "#6e3b3b"
ERROR_TEXT_COLOR_HEX = "#ffcccc"

CODE_BLOCK_BG_COLOR_HEX = "#282c34"
CODE_BLOCK_TEXT_COLOR_HEX = "#cccccc"

BUBBLE_BORDER_COLOR_HEX = "#4f5356"
TIMESTAMP_COLOR_HEX = "#888888"
CHAT_BACKGROUND_COLOR_HEX = "#2b2b2b" # Dark theme background

# --- Initial Log Message ---
logger.info(f"PyDevAI Studio v{APP_VERSION} constants loaded. Base Dir: {APP_BASE_DIR}, User Data: {USER_DATA_BASE_DIR}")