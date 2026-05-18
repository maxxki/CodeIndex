"""
codeindexrouter.py — MAXXKI CodeIndex Router (v4)

Fixes gegenüber v3:
  - Ebene 1: Fuzzy-Match sucht bekannte Dateipfade im rohen LLM-Output
  - Ebene 2: Fuzzy-Match sucht bekannte Nodes im rohen LLM-Output
  - Token-Cleanup: <|im_end|> und andere Chat-Template-Artefakte werden entfernt
  - Prompts vereinfacht: kürzere, direktere Instruktionen für kleine Modelle
  - main.py KeyboardInterrupt-Fix: asyncio.run() in try/except gewrappt
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Optional

import httpx

from models import FileNode, RouterResult, flatten_files
from codesnippetslicer import CodeSnippetSlicer


# ---------------------------------------------------------------------------
# Eigene Exception-Klassen
# ---------------------------------------------------------------------------

class RouterNavigationError(Exception):
    """LLM hat einen Node gewählt, der nicht im Index existiert."""

class RouterAnswerError(Exception):
    """Final-Answer-Step hat keinen verwertbaren Output geliefert."""


# ---------------------------------------------------------------------------
# CodeIndexRouter
# ---------------------------------------------------------------------------

class CodeIndexRouter:

    def __init__(
        self,
        index_file_path: str,
        routing_api_url: str = "http://localhost:8080/v1/chat/completions",
        answer_api_url:  str = "http://localhost:8081/v1/chat/completions",
    ):
        self.routing_api_url = routing_api_url
        self.answer_api_url  = answer_api_url

        # Security: Root path for path traversal protection
        self.project_root = os.path.dirname(os.path.abspath(index_file_path))

        with open(index_file_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        tree = raw.get("tree", raw)
        self.flat_files: dict[str, FileNode] = flatten_files(tree)
        self._cache: dict[str, RouterResult] = {}
        
        # Performance: Shared client for connection pooling
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """Closes the shared HTTP client."""
        await self.client.aclose()

    # -----------------------------------------------------------------------
    # Cache-Hilfsmethoden
    # -----------------------------------------------------------------------

    @staticmethod
    def _cache_key(query: str) -> str:
        return hashlib.sha256(query.strip().lower().encode()).hexdigest()

    def clear_cache(self) -> None:
        """Cache manuell leeren, z.B. nach einem Re-Index."""
        self._cache.clear()
        print("Query-Cache geleert.")

    # -----------------------------------------------------------------------
    # Constrained LLM Logic (Schema-Based)
    # -----------------------------------------------------------------------

    async def _call_constrained_llm(self, prompt: str, schema: dict, key: str) -> str:
        """Kapselt den HTTP-Call und garantiert die Einhaltung des Schemas via llama-server."""
        payload = {
            "messages": [
                {"role": "system", "content": "You are a precise technical router. Respond ONLY with the requested JSON object."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object", "schema": schema},
            "max_tokens": 32
        }

        response = await self.client.post(self.routing_api_url, json=payload)
        response.raise_for_status()
        
        content_str = response.json()["choices"][0]["message"]["content"]
        data = json.loads(content_str)
        return data[key]

    async def _route_file_with_schema(self, query: str) -> str:
        """
        Zwingt das LLM über ein JSON-Schema, exakt einen Dateipfad aus dem Index zu wählen.
        """
        file_list = list(self.flat_files.keys())
        
        schema = {
            "type": "object",
            "properties": {
                "selected_file": {
                    "type": "string",
                    "enum": file_list
                }
            },
            "required": ["selected_file"],
            "additionalProperties": False
        }

        prompt = (
            f"Du bist der Datei-Selector für dieses Projekt.\n"
            f"Benutzerfrage: {query}\n\n"
            f"Wähle die Datei, die am wahrscheinlichsten die Antwort enthält.\n"
            f"Antworte AUSSCHLIESSLICH mit dem geforderten JSON-Objekt."
        )

        return await self._call_constrained_llm(prompt, schema, "selected_file")

    async def _route_node_hierarchical(self, target_file: str, query: str) -> dict:
        """
        Zweistufiges hierarchisches Routing. Minimiert die Enum-Größe für das 
        lokale LLM, um semantische Fehlklassifikationen und Kontext-Overhead zu verhindern.
        """
        file_node = self.flat_files[target_file]
        available_classes = list(file_node.get("classes", {}).keys())
        raw_funcs = file_node.get("standalone_functions", [])
        available_functions = list(raw_funcs.keys()) if isinstance(raw_funcs, dict) else list(raw_funcs)

        # STUFE 1: High-Level Scope bestimmen
        scope_choices = ["global"]
        for c in available_classes:
            scope_choices.append(f"class:{c}")
        if available_functions:
            scope_choices.append("scope:standalone_functions")

        scope_schema = {
            "type": "object",
            "properties": {
                "selected_scope": {"type": "string", "enum": scope_choices}
            },
            "required": ["selected_scope"],
            "additionalProperties": False
        }

        scope_prompt = (
            f"Analysiere den Kontext der Frage für die Datei '{target_file}'.\n"
            f"Benutzerfrage: {query}\n\n"
            f"Liegt die Antwort in einer bestimmten Klasse, in den globalen Funktionen oder im Modul-Scope?"
        )

        selected_scope = await self._call_constrained_llm(scope_prompt, scope_schema, "selected_scope")

        # STUFE 2: Deep-Dive Target bestimmen
        if selected_scope == "global":
            return {"type": "global", "class_name": None, "method_name": None, "display": "Globaler Modulcode"}

        if selected_scope == "scope:standalone_functions":
            func_schema = {
                "type": "object",
                "properties": {
                    "selected_node": {"type": "string", "enum": available_functions}
                },
                "required": ["selected_node"],
                "additionalProperties": False
            }
            func_prompt = f"Wähle die exakte Funktion aus der Liste für die Frage: {query}"
            target_func = await self._call_constrained_llm(func_prompt, func_schema, "selected_node")
            return {"type": "function", "class_name": None, "method_name": target_func, "display": f"Funktion: {target_func}"}

        if selected_scope.startswith("class:"):
            target_class = selected_scope.split(":", 1)[1]
            raw_methods = file_node["classes"][target_class].get("methods", [])
            methods = list(raw_methods.keys()) if isinstance(raw_methods, dict) else list(raw_methods)

            if not methods:
                return {"type": "class", "class_name": target_class, "method_name": None, "display": f"Klasse: {target_class}"}

            method_choices = ["self"] + methods
            method_schema = {
                "type": "object",
                "properties": {
                    "selected_node": {"type": "string", "enum": method_choices}
                },
                "required": ["selected_node"],
                "additionalProperties": False
            }
            method_prompt = f"In der Klasse '{target_class}': Welche Methode beantwortet die Frage: {query}\nWähle 'self' für die Struktur der Klasse allgemein."
            
            target_method = await self._call_constrained_llm(method_prompt, method_schema, "selected_node")
            
            if target_method == "self":
                return {"type": "class", "class_name": target_class, "method_name": None, "display": f"Klasse: {target_class}"}
            return {"type": "method", "class_name": target_class, "method_name": target_method, "display": f"Methode: {target_class}.{target_method}"}

        raise RouterNavigationError("Unerwarteter Routing-Pfad im hierarchischen Baum.")

    async def _ask_answer(self, system_prompt: str, user_prompt: str) -> str:
        """Final-Answer → großes Modell, etwas kreativer (temp=0.1)."""
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }
        try:
            response = await self.client.post(self.answer_api_url, json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as e:
            raise RouterAnswerError(f"HTTP {e.response.status_code} von {self.answer_api_url}") from e
        except httpx.RequestError as e:
            raise RouterAnswerError(f"Verbindungsfehler zu {self.answer_api_url}: {e}") from e

    # -----------------------------------------------------------------------
    # Snippet-Extraction
    # -----------------------------------------------------------------------

    def _extract_snippet(self, target_file: str, meta: dict) -> str:
        """
        Schneidet das Snippet basierend auf den garantierten Schema-Metadaten.
        """
        if not os.path.isabs(target_file):
            target_file = os.path.join(self.project_root, target_file)

        abs_target = os.path.abspath(target_file)
        if not abs_target.startswith(self.project_root):
            raise RouterNavigationError(f"Sicherheitsverletzung: Zugriff verweigert für {target_file}")

        if meta["type"] == "global":
            try:
                with open(abs_target, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError as e:
                raise RouterNavigationError(f"Datei '{target_file}' konnte nicht gelesen werden: {e}") from e

        try:
            slicer = CodeSnippetSlicer(abs_target)
            return slicer.extract(
                class_name=meta["class_name"], 
                method_name=meta["method_name"]
            )
        except (LookupError, ValueError) as e:
            # This should theoretically never happen with schema routing
            print(f"  ⚠️  Slicer-Fallback (Unexpected): {e}")
            try:
                with open(abs_target, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                raise RouterNavigationError(f"Fatal error reading {target_file}")

    # -----------------------------------------------------------------------
    # Haupt-Such-Pipeline
    # -----------------------------------------------------------------------

    async def search(self, user_query: str) -> RouterResult:
        print(f"\n🔍  Query: '{user_query}'")

        cache_key = self._cache_key(user_query)
        if cache_key in self._cache:
            print("⚡  Cache-Hit — überspringe LLM-Routing.")
            return self._cache[cache_key]

        # EBENE 1 — Datei-Auswahl (Schema-Zwang)
        target_file = await self._route_file_with_schema(user_query)
        print(f"📂  Ebene 1 → Datei: {target_file}")

        # EBENE 2 — Node-Auswahl (Hierarchisches Schema-Zwang)
        meta = await self._route_node_hierarchical(target_file, user_query)
        print(f"🎯  Ebene 2 → Node: {meta['display']}")

        # EBENE 3 — Snippet + Final-Answer
        snippet = self._extract_snippet(target_file, meta)
        print(f"✂️   Snippet: {len(snippet)} Zeichen (~{len(snippet) // 4} Token)")

        answer = await self._ask_answer(
            system_prompt=(
                "Du bist ein Senior Software-Architekt. "
                "Beantworte die Frage präzise auf Basis des Code-Snippets. "
                "Kurz, direkt, technisch. Keine Wiederholung der Frage."
            ),
            user_prompt=(
                f"Frage: {user_query}\n\n"
                f"Code-Snippet aus {target_file} [{meta['display']}]:\n"
                f"```python\n{snippet}\n```"
            ),
        )

        result = RouterResult(
            target_file=target_file,
            target_node=meta['display'],
            snippet=snippet,
            answer=answer,
        )

        self._cache[cache_key] = result
        return result


# ---------------------------------------------------------------------------
# Schnelltest
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio

    async def run() -> None:
        if not os.path.exists("code_index.json"):
            print("❌  code_index.json nicht gefunden — bitte zuerst main.py ausführen.")
            return

        router = CodeIndexRouter("code_index.json")
        queries = [
            "Welche Datei parst Python-Dateien via AST?",
            "Welche Datei parst Python-Dateien via AST?",  # Cache-Test
            "Wo werden SHA-256 Hashes für die Index-Invalidierung berechnet?",
        ]

        for q in queries:
            try:
                result = await router.search(q)
                print(f"\n🤖  Antwort:")
                print(f"    Datei   : {result['target_file']}")
                print(f"    Node    : {result['target_node']}")
                print(f"    Antwort : {result['answer']}")
            except RouterNavigationError as e:
                print(f"\n🧭  Navigation fehlgeschlagen: {e}")
            except RouterAnswerError as e:
                print(f"\n💥  Answer-Step fehlgeschlagen: {e}")

    asyncio.run(run())
