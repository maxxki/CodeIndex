# =============================================================================
# codetreesummarizer.py — MAXXKI CodeIndex Summarizer (v3 Principal)
# =============================================================================
# ÄNDERUNGEN v3:
#   - Shared httpx.AsyncClient (statt pro Request neu)
#   - Type Hints
#   - Robustes Error Handling mit Exponential Backoff
#   - Keine Datenstruktur-Mutation: Builder produziert direkt dict-Format
#   - Englische Docstrings
# =============================================================================

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any

import httpx

from codetreebuilder import CodeTreeBuilder


class CodeTreeSummarizer:
    def __init__(
        self,
        api_url: str = "http://localhost:8080/v1/chat/completions",
        max_concurrent_requests: int = 5,
        timeout: float = 15.0,
    ) -> None:
        self.api_url = api_url
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.system_prompt = (
            "You are a Senior Software Architect. Reply with exactly ONE short, "
            "precise sentence in German explaining the main purpose of the given "
            "code artifact. Do not introduce your answer. No boilerplate."
        )
        # PRINCIPAL FIX: Shared client for connection pooling
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy initialization of shared HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Closes the shared HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _get_summary(
        self,
        context_type: str,
        name: str,
        details: str = "",
        retries: int = 2,
    ) -> str:
        """Requests a concise summary from the local LLM with retry logic."""
        prompt = f"Analyze this {context_type} named '{name}'. Details: {details}"
        payload = {
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 50,
        }

        client = await self._get_client()

        async with self.semaphore:
            for attempt in range(retries + 1):
                try:
                    response = await client.post(self.api_url, json=payload)
                    response.raise_for_status()
                    result = response.json()
                    return result["choices"][0]["message"]["content"].strip()
                except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                    if attempt == retries:
                        return f"Summary generation failed: {str(e)}"
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
            return "No summary available."

    async def enrich_tree(self, node: dict[str, Any]) -> dict[str, Any]:
        """Traverses the tree and collects tasks for parallel execution."""
        tasks: list[asyncio.Task[Any]] = []

        def collect_tasks(current_node: dict[str, Any]) -> None:
            if not isinstance(current_node, dict):
                return

            if current_node.get("type") == "directory" and "children" in current_node:
                for child_node in current_node["children"].values():
                    collect_tasks(child_node)

            elif current_node.get("type") == "file":
                # Standalone functions: already dict from builder v3
                funcs = current_node.get("standalone_functions", {})
                if isinstance(funcs, list):
                    # Backward compatibility: convert list to dict
                    current_node["standalone_functions"] = {}
                    for func_name in funcs:
                        async def wrap_func(
                            f_name: str = func_name,
                            target: dict[str, Any] = current_node,
                        ) -> None:
                            sum_text = await self._get_summary("function", f_name)
                            target["standalone_functions"][f_name] = {
                                "type": "function",
                                "summary": sum_text,
                            }
                        tasks.append(asyncio.create_task(wrap_func()))

                # Classes
                classes = current_node.get("classes", {})
                for class_name, class_data in classes.items():
                    async def wrap_class(
                        c_name: str = class_name,
                        c_data: dict[str, Any] = class_data,
                    ) -> None:
                        c_data["summary"] = await self._get_summary("class", c_name)
                    tasks.append(asyncio.create_task(wrap_class()))

                    methods = class_data.get("methods", {})
                    if isinstance(methods, list):
                        class_data["methods"] = {}
                        for method_name in methods:
                            async def wrap_method(
                                m_name: str = method_name,
                                c_n: str = class_name,
                                c_d: dict[str, Any] = class_data,
                            ) -> None:
                                sum_text = await self._get_summary(
                                    "method", f"{c_n}.{m_name}"
                                )
                                c_d["methods"][m_name] = {
                                    "type": "method",
                                    "summary": sum_text,
                                }
                            tasks.append(asyncio.create_task(wrap_method()))

        collect_tasks(node)

        if tasks:
            print(f"Sending {len(tasks)} requests to local LLM...")
            await asyncio.gather(*tasks, return_exceptions=True)

        return node

    @staticmethod
    def get_project_hash(root_dir: str) -> str:
        """Generates a SHA-256 hash over all Python files for cache invalidation."""
        hasher = hashlib.sha256()
        ignored_dirs = {".git", "__pycache__", "node_modules", "venv", ".pytest_cache"}

        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in sorted(files):
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    with open(file_path, "rb") as f:
                        while chunk := f.read(8192):
                            hasher.update(chunk)
        return hasher.hexdigest()
