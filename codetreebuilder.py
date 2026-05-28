# =============================================================================
# codetreebuilder.py — MAXXKI CodeIndex AST Parser (v3.1 Principal)
# =============================================================================
# ÄNDERUNGEN v3.1:
#   - AsyncClassDef ENTFERNT (existiert nicht in Python AST)
#   - AsyncFunctionDef bleibt (existiert seit Python 3.5)
# =============================================================================

from __future__ import annotations

import ast
import os
from typing import Any


class CodeTreeBuilder:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = os.path.abspath(root_dir)

    @staticmethod
    def _count_nested_functions(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[int, list[str]]:
        """Counts nested function definitions within a function/method body."""
        count = 0
        names: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not node:
                count += 1
                names.append(child.name)
        return count, names

    def parse_python_file(self, file_path: str) -> dict[str, Any]:
        """Parses a Python file into classes, methods, and standalone functions via AST."""
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read(), filename=file_path)
            except SyntaxError:
                return {"type": "file", "status": "syntax_error"}

        file_structure: dict[str, Any] = {
            "type": "file",
            "classes": {},
            "standalone_functions": [],
            "has_nested_functions": False,
            "nested_metadata": [],
        }

        for child in tree.body:
            # Classes (Python has no async classes)
            if isinstance(child, ast.ClassDef):
                methods: list[str] = []
                nested_in_class: list[dict[str, Any]] = []

                for member in child.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(member.name)
                        nested_count, nested_names = self._count_nested_functions(member)
                        if nested_count > 0:
                            file_structure["has_nested_functions"] = True
                            nested_in_class.append({
                                "parent": f"{child.name}.{member.name}",
                                "nested_count": nested_count,
                                "names": nested_names,
                            })

                file_structure["classes"][child.name] = {
                    "type": "class",
                    "methods": methods,
                }

                if nested_in_class:
                    file_structure["nested_metadata"].extend(nested_in_class)

            # Standalone functions (sync + async)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                file_structure["standalone_functions"].append(child.name)
                nested_count, nested_names = self._count_nested_functions(child)
                if nested_count > 0:
                    file_structure["has_nested_functions"] = True
                    file_structure["nested_metadata"].append({
                        "parent": child.name,
                        "nested_count": nested_count,
                        "names": nested_names,
                    })

        return file_structure

    def build_tree(self, current_dir: str | None = None) -> dict[str, Any]:
        """Builds the hierarchical tree structure of the entire repository."""
        if current_dir is None:
            current_dir = self.root_dir

        tree: dict[str, Any] = {}

        ignored_dirs = {".git", "__pycache__", "node_modules", "venv", ".idea", ".pytest_cache"}

        try:
            items = os.listdir(current_dir)
        except OSError:
            return tree

        for item in items:
            item_path = os.path.join(current_dir, item)

            if os.path.isdir(item_path):
                if item in ignored_dirs:
                    continue
                subtree = self.build_tree(item_path)
                if subtree:
                    tree[item] = {"type": "directory", "children": subtree}

            elif os.path.isfile(item_path) and item.endswith(".py"):
                tree[item] = self.parse_python_file(item_path)

        return tree
