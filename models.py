# =============================================================================
# models.py — MAXXKI CodeIndex Datenmodelle (v3 Principal)
# =============================================================================
# ÄNDERUNGEN v3:
#   - NestedFunctionData für verschachtelte Funktionen (Metadaten-Only)
#   - FileNode erweitert um has_nested_functions Flag
#   - Alle TypedDicts mit total=False für optionale Felder
# =============================================================================

from __future__ import annotations
from typing import Literal, TypedDict, Union, NotRequired


# ---------------------------------------------------------------------------
# Basis-Nodes
# ---------------------------------------------------------------------------

class MethodData(TypedDict):
    type: Literal["method"]
    summary: str
    has_nested: NotRequired[bool]  # NEU: Flag für verschachtelte Funktionen


class FunctionData(TypedDict):
    type: Literal["function"]
    summary: str


class NestedFunctionData(TypedDict, total=False):
    """Metadaten für verschachtelte Funktionen - NICHT als eigener Index-Node."""
    parent: str
    nested_count: int
    names: list[str]


class ClassData(TypedDict):
    type: Literal["class"]
    summary: str
    methods: dict[str, MethodData]


# ---------------------------------------------------------------------------
# Datei-Node
# ---------------------------------------------------------------------------

class FileNode(TypedDict):
    type: Literal["file"]
    classes: dict[str, ClassData]
    standalone_functions: dict[str, FunctionData]
    has_nested_functions: NotRequired[bool]  # NEU: Router-Hinweis
    nested_metadata: NotRequired[list[NestedFunctionData]]  # NEU: Nur Anzeige


# ---------------------------------------------------------------------------
# Verzeichnis-Node (rekursiv via Forward-Reference)
# ---------------------------------------------------------------------------

class DirectoryNode(TypedDict):
    type: Literal["directory"]
    children: dict[str, Union[FileNode, "DirectoryNode"]]


# ---------------------------------------------------------------------------
# Top-Level Index
# ---------------------------------------------------------------------------

class IndexMeta(TypedDict):
    project_hash: str


class CodeIndex(TypedDict):
    meta: IndexMeta
    tree: dict[str, Union[FileNode, DirectoryNode]]


# ---------------------------------------------------------------------------
# Router-Ergebnis
# ---------------------------------------------------------------------------

class RouterResult(TypedDict):
    target_file: str
    target_node: str
    snippet: str
    answer: str


# ---------------------------------------------------------------------------
# Hilfsfunktion: alle FileNodes aus beliebig tiefem Baum flach extrahieren
# ---------------------------------------------------------------------------

def flatten_files(
    tree: dict[str, Union[FileNode, DirectoryNode]],
    prefix: str = "",
) -> dict[str, FileNode]:
    """
    Traversiert rekursiv den gesamten Baum und gibt ein flaches Dict zurück:
        { "relative/path/to/file.py": FileNode, ... }
    """
    result: dict[str, FileNode] = {}

    for name, node in tree.items():
        full_path = f"{prefix}/{name}" if prefix else name

        if node.get("type") == "file":
            result[full_path] = node  # type: ignore[arg-type]

        elif node.get("type") == "directory":
            children = node.get("children", {})  # type: ignore[union-attr]
            result.update(flatten_files(children, prefix=full_path))

    return result
