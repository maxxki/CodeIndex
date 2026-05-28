# =============================================================================
# codeindexrouter.py — MAXXKI CodeIndex Router (v3.1 Principal)
# =============================================================================
# ÄNDERUNGEN v3.1:
#   - AsyncClassDef ENTFERNT (existiert nicht in Python AST)
#   - _sanitize_query: Nur einzelne {/} escapen, nicht doppelte
# =============================================================================

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Optional

import httpx

from models import FileNode, RouterResult, flatten_files
from codesnippetslicer import CodeSnippetSlicer


class RouterNavigationError(Exception):
    """LLM selected a node that does not exist in the index."""

class RouterAnswerError(Exception):
    """Final answer step produced no usable output."""


class CodeIndexRouter:
    def __init__(
        self,
        index_file_path: str,
        routing_api_url: str | None = None,
        answer_api_url: str | None = None,
    ) -> None:
        self.routing_api_url = routing_api_url or os.getenv(
            "ROUTER_API_URL", "http://localhost:8080/v1/chat/completions"
        )
        self.answer_api_url = answer_api_url or os.getenv(
            "ANSWER_API_URL", "http://localhost:8081/v1/chat/completions"
        )

        # SECURITY FIX: realpath resolves symlinks for traversal protection
        self.project_root = os.path.realpath(
            os.path.dirname(os.path.abspath(index_file_path))
        )

        with open(index_file_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        tree = raw.get("tree", raw)
        self.flat_files: dict[str, FileNode] = flatten_files(tree)
        self._cache: dict[str, RouterResult] = {}

        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Closes the shared HTTP client."""
        await self.client.aclose()

    @staticmethod
    def _cache_key(query: str) -> str:
        return hashlib.sha256(query.strip().lower().encode()).hexdigest()

    def clear_cache(self) -> None:
        """Manually clears the cache, e.g., after re-indexing."""
        self._cache.clear()
        print("Query cache cleared.")

    @staticmethod
    def _sanitize_query(query: str) -> str:
        """Sanitizes user input to prevent prompt injection attacks.
        
        Escapes curly braces by doubling them (Jinja2-style), preventing
        template injection into JSON schema prompts.
        """
        # Double each single brace — but avoid quadrupling already-doubled ones
        # First, use a placeholder to protect existing doubles
        sanitized = query.replace("{{", "\x00DBL_OPEN\x00").replace("}}", "\x00DBL_CLOSE\x00")
        # Now double single braces
        sanitized = sanitized.replace("{", "{{").replace("}", "}}")
        # Restore original doubles
        sanitized = sanitized.replace("\x00DBL_OPEN\x00", "{{").replace("\x00DBL_CLOSE\x00", "}}")
        # Limit length to prevent token exhaustion attacks
        max_len = 2000
        if len(sanitized) > max_len:
            sanitized = sanitized[:max_len] + "... [truncated]"
        return sanitized

    async def _call_constrained_llm(self, prompt: str, schema: dict, key: str) -> str:
        """Wraps the HTTP call and enforces schema compliance via llama-server."""
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise technical router. Respond ONLY with the requested JSON object.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object", "schema": schema},
            "max_tokens": 32,
        }

        try:
            response = await self.client.post(self.routing_api_url, json=payload)
            response.raise_for_status()
            content_str = response.json()["choices"][0]["message"]["content"]
            data = json.loads(content_str)
            return str(data[key])
        except json.JSONDecodeError as e:
            raise RouterNavigationError(f"LLM returned invalid JSON: {e}") from e
        except KeyError as e:
            raise RouterNavigationError(f"LLM response missing key '{key}'") from e
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            raise RouterNavigationError(f"Routing API error: {e}") from e

    async def _route_file_with_schema(self, query: str) -> str:
        """Forces the LLM via JSON schema to select exactly one file path from the index."""
        file_list = list(self.flat_files.keys())

        schema = {
            "type": "object",
            "properties": {
                "selected_file": {"type": "string", "enum": file_list}
            },
            "required": ["selected_file"],
            "additionalProperties": False,
        }

        safe_query = self._sanitize_query(query)
        prompt = (
            f"You are the file selector for this project.\n"
            f"User question: {safe_query}\n\n"
            f"Select the file most likely to contain the answer.\n"
            f"Respond ONLY with the requested JSON object."
        )

        return await self._call_constrained_llm(prompt, schema, "selected_file")

    async def _route_node_hierarchical(self, target_file: str, query: str) -> dict:
        """Two-stage hierarchical routing. Minimizes enum size for the local LLM."""
        file_node = self.flat_files[target_file]
        available_classes = list(file_node.get("classes", {}).keys())
        raw_funcs = file_node.get("standalone_functions", [])
        available_functions = (
            list(raw_funcs.keys()) if isinstance(raw_funcs, dict) else list(raw_funcs)
        )

        # STAGE 1: Determine high-level scope
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
            "additionalProperties": False,
        }

        safe_query = self._sanitize_query(query)
        scope_prompt = (
            f"Analyze the context of the question for file '{target_file}'.\n"
            f"User question: {safe_query}\n\n"
            f"Is the answer in a specific class, in global functions, or in module scope?"
        )

        selected_scope = await self._call_constrained_llm(
            scope_prompt, scope_schema, "selected_scope"
        )

        # STAGE 2: Deep-dive target
        if selected_scope == "global":
            return {
                "type": "global",
                "class_name": None,
                "method_name": None,
                "display": "Global module code",
            }

        if selected_scope == "scope:standalone_functions":
            func_schema = {
                "type": "object",
                "properties": {
                    "selected_node": {"type": "string", "enum": available_functions}
                },
                "required": ["selected_node"],
                "additionalProperties": False,
            }
            func_prompt = f"Select the exact function from the list for the question: {safe_query}"
            target_func = await self._call_constrained_llm(
                func_prompt, func_schema, "selected_node"
            )
            return {
                "type": "function",
                "class_name": None,
                "method_name": target_func,
                "display": f"Function: {target_func}",
            }

        if selected_scope.startswith("class:"):
            target_class = selected_scope.split(":", 1)[1]
            raw_methods = file_node["classes"][target_class].get("methods", [])
            methods = (
                list(raw_methods.keys()) if isinstance(raw_methods, dict) else list(raw_methods)
            )

            if not methods:
                return {
                    "type": "class",
                    "class_name": target_class,
                    "method_name": None,
                    "display": f"Class: {target_class}",
                }

            method_choices = ["self"] + methods
            method_schema = {
                "type": "object",
                "properties": {
                    "selected_node": {"type": "string", "enum": method_choices}
                },
                "required": ["selected_node"],
                "additionalProperties": False,
            }
            method_prompt = (
                f"In class '{target_class}': Which method answers the question: {safe_query}\n"
                f"Select 'self' for the general class structure."
            )

            target_method = await self._call_constrained_llm(
                method_prompt, method_schema, "selected_node"
            )

            if target_method == "self":
                return {
                    "type": "class",
                    "class_name": target_class,
                    "method_name": None,
                    "display": f"Class: {target_class}",
                }
            return {
                "type": "method",
                "class_name": target_class,
                "method_name": target_method,
                "display": f"Method: {target_class}.{target_method}",
            }

        raise RouterNavigationError("Unexpected routing path in hierarchical tree.")

    async def _ask_answer(self, system_prompt: str, user_prompt: str) -> str:
        """Final answer — larger model, slightly creative (temp=0.1)."""
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }
        try:
            response = await self.client.post(self.answer_api_url, json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            raise RouterAnswerError(f"Answer API error: {e}") from e
        except (json.JSONDecodeError, KeyError) as e:
            raise RouterAnswerError(f"Invalid answer response: {e}") from e

    def _extract_snippet(self, target_file: str, meta: dict) -> str:
        """Cuts the snippet based on guaranteed schema metadata.
        
        SECURITY: Uses os.path.realpath() to resolve symlinks before
        path traversal validation.
        """
        if not os.path.isabs(target_file):
            target_file = os.path.join(self.project_root, target_file)

        # PRINCIPAL FIX: realpath resolves symlinks
        abs_target = os.path.realpath(target_file)
        real_project_root = os.path.realpath(self.project_root)

        if not abs_target.startswith(real_project_root):
            raise RouterNavigationError(
                f"Security violation: Access denied for {target_file}"
            )

        if meta["type"] == "global":
            try:
                with open(abs_target, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError as e:
                raise RouterNavigationError(
                    f"File '{target_file}' could not be read: {e}"
                ) from e

        try:
            slicer = CodeSnippetSlicer(abs_target)
            return slicer.extract(
                class_name=meta["class_name"],
                method_name=meta["method_name"],
            )
        except (LookupError, ValueError) as e:
            print(f"  ⚠️  Slicer fallback (unexpected): {e}")
            try:
                with open(abs_target, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                raise RouterNavigationError(f"Fatal error reading {target_file}")

    async def search(self, user_query: str) -> RouterResult:
        print(f"\nQuery: '{user_query}'")

        cache_key = self._cache_key(user_query)
        if cache_key in self._cache:
            print("Cache hit — skipping LLM routing.")
            return self._cache[cache_key]

        # LEVEL 1 — File selection (schema constraint)
        target_file = await self._route_file_with_schema(user_query)
        print(f"Level 1 → File: {target_file}")

        # LEVEL 2 — Node selection (hierarchical schema constraint)
        meta = await self._route_node_hierarchical(target_file, user_query)
        print(f"Level 2 → Node: {meta['display']}")

        # LEVEL 3 — Snippet + final answer
        snippet = self._extract_snippet(target_file, meta)
        print(f"Snippet: {len(snippet)} chars (~{len(snippet) // 4} tokens)")

        safe_query = self._sanitize_query(user_query)
        answer = await self._ask_answer(
            system_prompt=(
                "You are a Senior Software Architect. "
                "Answer the question precisely based on the code snippet. "
                "Short, direct, technical. Do not repeat the question."
            ),
            user_prompt=(
                f"Question: {safe_query}\n\n"
                f"Code snippet from {target_file} [{meta['display']}]:\n"
                f"```python\n{snippet}\n```"
            ),
        )

        result = RouterResult(
            target_file=target_file,
            target_node=meta["display"],
            snippet=snippet,
            answer=answer,
        )

        self._cache[cache_key] = result
        return result
