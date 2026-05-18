"""
models.py — MAXXKI CodeIndex Datenmodelle (v2)
Echte Typdiskriminierung via Literal statt rohem str.
"""

from __future__ import annotations
from typing import Literal, TypedDict, Union


# ---------------------------------------------------------------------------
# Basis-Nodes
# ---------------------------------------------------------------------------

class MethodData(TypedDict):
    type: Literal["method"]
    summary: str


class FunctionData(TypedDict):
    type: Literal["function"]
    summary: str


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

    Damit navigiert der Router auch in verschachtelten Repos korrekt,
    ohne die Baum-Struktur der DirectoryNodes manuell auseinanderzudröseln.
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
