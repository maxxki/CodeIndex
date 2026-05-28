# =============================================================================
# codesnippetslicer.py — MAXXKI CodeIndex AST Slicer (v3.1 Principal)
# =============================================================================
# ÄNDERUNGEN v3.1:
#   - AsyncClassDef ENTFERNT (existiert nicht in Python AST)
#   - AsyncFunctionDef bleibt (existiert seit Python 3.5)
# =============================================================================

from __future__ import annotations

import ast
from typing import cast


class CodeSnippetSlicer:
    """Extracts targeted function or method code from a file via AST."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        with open(file_path, "r", encoding="utf-8") as f:
            self.source_lines = f.readlines()
            self.source = "".join(self.source_lines)
        try:
            self.tree = ast.parse(self.source, filename=file_path)
        except SyntaxError as e:
            raise ValueError(f"AST parse failed for {file_path}: {e}")

    @staticmethod
    def _is_inside_class(node: ast.AST, tree: ast.Module) -> bool:
        """Checks if a function node is nested inside a class definition.
        
        NOTE: Python has no AsyncClassDef — classes are always sync.
        """
        for parent in ast.walk(tree):
            if isinstance(parent, ast.ClassDef):
                for child in ast.walk(parent):
                    if child is node:
                        return True
        return False

    def _find_node(
        self,
        class_name: str | None,
        method_name: str | None,
    ) -> ast.AST | None:
        """Finds the AST node for class+method or standalone function.
        
        For nested functions: returns the PARENT function (the outermost
        containing function), since nested functions are semantically part
        of their parent and should never be extracted in isolation.
        """
        # 1. Standalone function (module-level, not inside a class)
        if class_name is None and method_name:
            for node in self.tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                   and node.name == method_name:
                    # Verify it's truly standalone (not inside a class)
                    if not self._is_inside_class(node, self.tree):
                        return node
            return None

        # 2. Method inside a class — ONLY direct children, no recursive walk
        if class_name and method_name:
            for node in self.tree.body:
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    # Only direct children of the class body
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                           and child.name == method_name:
                            return child
                    # Fallback: nested function inside method? Return parent
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            for nested in ast.walk(child):
                                if isinstance(nested, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                                   and nested.name == method_name \
                                   and nested is not child:
                                    return child  # Return parent, not nested
            return None

        # 3. Class itself
        if class_name and method_name is None:
            for node in self.tree.body:
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    return node

        return None

    def extract(
        self,
        class_name: str | None = None,
        method_name: str | None = None,
        context_lines: int = 3,
        max_tokens_approx: int = 1500,
    ) -> str:
        """Extracts the relevant code snippet with proper indentation handling.
        
        BUGFIX v3.1: textwrap.dedent is ONLY applied to complete module-level
        nodes (standalone functions, classes). For methods inside classes,
        the relative indentation is preserved to maintain syntactic validity.
        """
        target_node = self._find_node(class_name, method_name)
        if target_node is None:
            raise LookupError(
                f"Node not found: class='{class_name}', method='{method_name}'"
            )

        start = max(0, target_node.lineno - 1 - context_lines)
        end = min(len(self.source_lines), target_node.end_lineno + context_lines)

        snippet_lines = self.source_lines[start:end]

        # PRINCIPAL FIX: dedent only makes sense for module-level nodes
        # For methods, we preserve indentation
        is_module_level = (
            class_name is None and method_name is not None
        ) or (class_name is not None and method_name is None)

        if is_module_level:
            snippet = "".join(snippet_lines)
            # Only dedent if the node starts at column 0 (truly module-level)
            if getattr(target_node, 'col_offset', 0) == 0:
                snippet = __import__("textwrap").dedent(snippet)
        else:
            # For methods: preserve indentation, just strip trailing whitespace
            snippet = "".join(line.rstrip() + "\n" for line in snippet_lines)
            snippet = snippet.rstrip() + "\n"

        # Hard token limit
        max_chars = max_tokens_approx * 4
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars] + "\n# ... [TRUNCATED: Snippet exceeds token limit]"

        return snippet
