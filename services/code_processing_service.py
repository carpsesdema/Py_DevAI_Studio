# services/code_processing_service.py
import logging
import asyncio
import subprocess
import tempfile
import os
import ast
from typing import Tuple, Optional, List

from utils import constants # For APP_NAME logger

logger = logging.getLogger(constants.APP_NAME)


class CodeProcessingService:
    def __init__(self):
        logger.info("CodeProcessingService initialized.")
        self._ruff_available = False
        self._check_ruff_availability()

    def _check_ruff_availability(self):
        """Checks if the 'ruff' command-line tool is available."""
        try:
            # Attempt to run 'ruff --version'
            # Using shell=False is generally safer.
            # On Windows, if ruff is in PATH and is a .exe or .bat, it should work.
            # If ruff is installed as a Python package, `python -m ruff --version` might be more robust
            # but requires knowing the Python interpreter path if in a venv.
            # For simplicity, direct command call is common.
            process_result = subprocess.run(
                ["ruff", "--version"],
                capture_output=True,
                check=True, # Will raise CalledProcessError if ruff returns non-zero
                text=True,
                shell=False # Safer
            )
            logger.info(f"Ruff executable found. Version: {process_result.stdout.strip()}")
            self._ruff_available = True
        except subprocess.CalledProcessError as e:
            logger.warning(f"Ruff command executed but returned an error (Code: {e.returncode}): {e.stderr}")
            self._ruff_available = False
        except FileNotFoundError:
            logger.warning("Ruff executable not found in PATH. Ruff processing will be disabled. Please install Ruff: https://docs.astral.sh/ruff/installation/")
            self._ruff_available = False
        except PermissionError:
            logger.warning("Permission denied when trying to execute Ruff. Ruff processing will be disabled.")
            self._ruff_available = False
        except Exception as e_unexpected:
            logger.error(f"Unexpected error checking Ruff availability: {e_unexpected}")
            self._ruff_available = False

    async def validate_python_syntax(self, code_content: str, filename: str = "<string>") -> Tuple[bool, Optional[str]]:
        """
        Validates Python code syntax using AST parsing.

        Args:
            code_content: The Python code as a string.
            filename: The apparent filename (used for error messages).

        Returns:
            A tuple (is_valid, error_message_or_none).
        """
        if not code_content.strip():
            logger.debug(f"No content to validate syntax for '{filename}'. Considered valid.")
            return True, None # Empty code is syntactically valid
        try:
            ast.parse(code_content, filename=filename)
            logger.debug(f"AST Syntax validation successful for '{filename}'.")
            return True, None
        except SyntaxError as e_ast:
            error_message = f"Syntax Error: {e_ast.msg} (line {e_ast.lineno}, offset {e_ast.offset})"
            logger.warning(f"AST SyntaxError in '{filename}': {error_message}")
            return False, error_message
        except Exception as e_other_ast:
            error_message = f"AST Parsing Error: {e_other_ast}"
            logger.error(f"Unexpected AST parsing error in '{filename}': {error_message}", exc_info=True)
            return False, error_message

    async def format_and_lint_code(self, code_content: str, filename_hint: str = "temp_code.py") -> Tuple[str, Optional[str]]:
        """
        Formats and lints Python code using Ruff.
        Returns the processed code and any error/warning messages from Ruff.
        If Ruff is unavailable, returns the original code and an info message.
        """
        if not self._ruff_available:
            logger.info("Ruff is not available, skipping formatting and linting.")
            return code_content, "Ruff not available for processing."

        if not code_content.strip():
            logger.debug("No code content to format/lint.")
            return "", None # Return empty string for empty input

        temp_file_path = None
        original_filename_prefix = os.path.splitext(os.path.basename(filename_hint))[0]

        try:
            # Create a temporary file with a .py extension for Ruff
            with tempfile.NamedTemporaryFile(
                mode="w+",
                delete=False, # We need to pass the path to subprocess
                suffix=".py",
                encoding='utf-8',
                prefix=f"pydevai_ruff_{original_filename_prefix}_"
            ) as fp:
                temp_file_path = fp.name
                fp.write(code_content)
                fp.flush() # Ensure content is written before Ruff reads it

            logger.debug(f"CodeProcessingService: Wrote content for '{filename_hint}' to temp file: {temp_file_path}")

            processed_code = code_content # Start with original in case steps fail
            error_messages_collated: List[str] = []

            # Step 1: Format with Ruff
            # Ruff format usually modifies the file in-place.
            cmd_format = ["ruff", "format", temp_file_path]
            logger.debug(f"Running Ruff format command: {' '.join(cmd_format)}")
            try:
                process_format = await asyncio.to_thread(
                    subprocess.run, cmd_format, capture_output=True, text=True, check=False, shell=False
                )
                if process_format.returncode == 0:
                    # Read the potentially modified content back
                    with open(temp_file_path, "r", encoding='utf-8') as f_read_formatted:
                        processed_code = f_read_formatted.read()
                    logger.info(f"Ruff format successful for temp file of '{filename_hint}'.")
                    if processed_code.strip() != code_content.strip():
                         logger.info(f"Ruff applied formatting changes to '{filename_hint}'.")
                else:
                    # Format failed, log stderr. Content in temp_file_path might be unchanged or partially changed.
                    # We will use the `processed_code` which is still original or from a successful previous step.
                    err_msg = f"Ruff format command failed (Code: {process_format.returncode}). Stderr: {process_format.stderr.strip() if process_format.stderr else 'N/A'}"
                    logger.warning(f"{err_msg} for '{filename_hint}'")
                    error_messages_collated.append(f"Format command error: {process_format.stderr.strip() if process_format.stderr else 'Unknown formatting error'}")
            except Exception as e_fmt:
                err_msg = f"Exception during ruff format for '{filename_hint}': {e_fmt}"
                logger.error(err_msg, exc_info=True)
                error_messages_collated.append(f"Format Exception: {e_fmt}")
            # Ensure `processed_code` has the content to be linted (either original or formatted)
            # This requires writing it back if format modified it, before linting.
            with open(temp_file_path, "w", encoding='utf-8') as fp_write_for_lint:
                fp_write_for_lint.write(processed_code)
                fp_write_for_lint.flush()


            # Step 2: Lint and Fix with Ruff
            # Ruff check --fix also modifies in-place. --exit-zero means it won't error on lint issues.
            cmd_lint_fix = ["ruff", "check", temp_file_path, "--fix", "--exit-zero"]
            logger.debug(f"Running Ruff check --fix command: {' '.join(cmd_lint_fix)}")
            try:
                process_lint = await asyncio.to_thread(
                    subprocess.run, cmd_lint_fix, capture_output=True, text=True, check=False, shell=False
                )
                # Read the content again, as --fix might have changed it.
                with open(temp_file_path, "r", encoding='utf-8') as f_read_linted:
                    final_processed_code = f_read_linted.read()

                if final_processed_code.strip() != processed_code.strip() and not error_messages_collated: # Only log if format didn't already report issues
                    logger.info(f"Ruff applied linting fixes to '{filename_hint}'.")
                processed_code = final_processed_code # Update with linted code

                # Stderr for `check --fix --exit-zero` might contain info about fixes or unfixable errors.
                # We are interested if it *still* reports errors after attempting fixes.
                # A secondary `ruff check` without --fix would be needed for that, or parse output.
                # For now, we assume if it exits zero, major issues are fixed or it's acceptable.
                # If stderr contains "error:" it might indicate persistent issues.
                if process_lint.stderr and "error:" in process_lint.stderr.lower():
                    err_msg_lint = f"Ruff check --fix reported persistent errors or warnings. Stderr: {process_lint.stderr.strip()}"
                    logger.warning(f"{err_msg_lint} for '{filename_hint}'")
                    error_messages_collated.append(f"Linting issues: {process_lint.stderr.strip()}")
                elif not error_messages_collated: # No previous errors and lint seems okay
                     logger.info(f"Ruff check --fix completed for temp file of '{filename_hint}'.")

            except Exception as e_lint:
                err_msg = f"Exception during ruff check --fix for '{filename_hint}': {e_lint}"
                logger.error(err_msg, exc_info=True)
                error_messages_collated.append(f"Lint Fix Exception: {e_lint}")

            final_error_output = "; ".join(error_messages_collated) if error_messages_collated else None
            return processed_code, final_error_output

        except Exception as e:
            logger.exception(f"CodeProcessingService: Unexpected error processing code for {filename_hint}: {e}")
            return code_content, f"General processing error: {e}"
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    logger.debug(f"Removed temp file: {temp_file_path}")
                except Exception as e_del:
                    logger.error(f"Failed to delete temp file {temp_file_path}: {e_del}")