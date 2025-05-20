# services/code_analysis_service.py
import ast
import os
import logging
from typing import List, Dict, Any, Optional

from utils import constants # For APP_NAME logger

logger = logging.getLogger(constants.APP_NAME)

class CodeAnalysisService:
    """
    Provides services for analyzing source code structure,
    focusing on AST parsing for Python files.
    """

    def __init__(self):
        logger.info("CodeAnalysisService initialized.")
        # No complex state needed for now

    def parse_python_structures(self, code_content: str, file_path: str) -> List[Dict[str, Any]]:
        """
        Parses Python code using AST to extract function and class definitions.

        Args:
            code_content: The Python code as a string.
            file_path: The path to the file (used for logging and error messages).

        Returns:
            A list of dictionaries, each representing a function or class structure
            with its name, type ('function' or 'class'), start line, and end line.
            Returns an empty list if parsing fails or no structures are found.
            Example: [{"name": "my_func", "type": "function", "start_line": 10, "end_line": 25}, ...]
        """
        structures: List[Dict[str, Any]] = []
        if not code_content:
            logger.debug(f"No content to parse for AST in file: {os.path.basename(file_path)}")
            return structures

        try:
            logger.debug(f"Attempting AST parse for: {os.path.basename(file_path)}")
            # ast.parse can take 'filename' argument for better error messages
            tree = ast.parse(code_content, filename=os.path.basename(file_path))
            logger.debug(f"AST parsing successful for: {os.path.basename(file_path)}")

            class StructureVisitor(ast.NodeVisitor):
                def __init__(self, file_path_for_log: str):
                    self.structures_found: List[Dict[str, Any]] = []
                    self.file_path_for_log = file_path_for_log # Store for logging within visitor
                    super().__init__()

                def _get_end_line(self, node: ast.AST) -> Optional[int]:
                    """
                    Safely get the end line number.
                    Requires Python 3.8+ for reliable 'end_lineno'.
                    """
                    if hasattr(node, 'end_lineno') and node.end_lineno is not None:
                        return node.end_lineno
                    else:
                        # Fallback for older Python or nodes where end_lineno might be None.
                        # This is a simple heuristic: iterate over direct children to find max lineno.
                        # A more robust approach might be needed for complex cases or very old Python.
                        max_child_line = node.lineno
                        for child_node in ast.iter_child_nodes(node):
                            if hasattr(child_node, 'lineno'):
                                max_child_line = max(max_child_line, child_node.lineno)
                            # If child_node also has end_lineno, could recurse, but keep simple.
                        # If no children with line numbers, assume it ends on the start line.
                        logger.debug(
                            f"Node '{getattr(node, 'name', 'Unnamed')}' in "
                            f"{os.path.basename(self.file_path_for_log)} lacks 'end_lineno' or it's None. "
                            f"Using lineno {node.lineno} or max child line {max_child_line} as estimate."
                        )
                        return max_child_line if max_child_line > node.lineno else node.lineno


                def visit_FunctionDef(self, node: ast.FunctionDef):
                    end_line = self._get_end_line(node)
                    if end_line is not None:
                        self.structures_found.append({
                            "name": node.name,
                            "type": "function",
                            "start_line": node.lineno,
                            "end_line": end_line
                        })
                    else:
                         logger.warning(f"Could not determine end line for function '{node.name}' in {os.path.basename(self.file_path_for_log)}.")
                    self.generic_visit(node) # Continue visiting children

                def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
                    end_line = self._get_end_line(node)
                    if end_line is not None:
                        self.structures_found.append({
                            "name": node.name,
                            "type": "function", # Treat async functions as 'function' type
                            "start_line": node.lineno,
                            "end_line": end_line
                        })
                    else:
                         logger.warning(f"Could not determine end line for async function '{node.name}' in {os.path.basename(self.file_path_for_log)}.")
                    self.generic_visit(node)

                def visit_ClassDef(self, node: ast.ClassDef):
                    end_line = self._get_end_line(node)
                    if end_line is not None:
                        self.structures_found.append({
                            "name": node.name,
                            "type": "class",
                            "start_line": node.lineno,
                            "end_line": end_line
                        })
                    else:
                         logger.warning(f"Could not determine end line for class '{node.name}' in {os.path.basename(self.file_path_for_log)}.")
                    self.generic_visit(node)

            visitor = StructureVisitor(file_path)
            visitor.visit(tree)
            structures = visitor.structures_found
            if structures:
                logger.info(f"Extracted {len(structures)} function/class structures from: {os.path.basename(file_path)}")
            else:
                logger.debug(f"No top-level function/class structures found by AST visitor in: {os.path.basename(file_path)}")

        except SyntaxError as e:
            logger.warning(f"AST SyntaxError parsing {os.path.basename(file_path)} (line {e.lineno}, offset {e.offset}): {e.msg}. Skipping structure extraction for this file.")
            # Return empty list, don't stop processing other files
        except Exception as e:
            # Catch other potential AST errors (e.g., recursion depth on complex files)
            logger.error(f"Unexpected AST error parsing {os.path.basename(file_path)}: {e}", exc_info=True)
            # Return empty list

        return structures

    # --- Potential future methods for deeper code analysis ---
    # def analyze_dependencies(self, code_content: str, file_path: str) -> List[str]:
    #     """Extracts import statements."""
    #     imports = []
    #     try:
    #         tree = ast.parse(code_content, filename=os.path.basename(file_path))
    #         for node in ast.walk(tree):
    #             if isinstance(node, ast.Import):
    #                 for alias in node.names:
    #                     imports.append(alias.name)
    #             elif isinstance(node, ast.ImportFrom):
    #                 if node.module: # node.module can be None for 'from . import ...'
    #                     imports.append(node.module)
    #     except Exception as e:
    #         logger.warning(f"Could not analyze dependencies for {os.path.basename(file_path)}: {e}")
    #     return list(set(imports)) # Unique imports