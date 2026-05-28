# =============================================================================
# main.py — MAXXKI CodeIndex Entry Point (v3 Principal)
# =============================================================================
# ÄNDERUNGEN v3:
#   - CodeTreeSummarizer.close() aufrufen für Client-Cleanup
#   - os.getenv() für konfigurierbare API-URL
#   - Englische Output-Messages
# =============================================================================

from __future__ import annotations

import asyncio
import json
import os
import sys

from codetreebuilder import CodeTreeBuilder
from codetreesummarizer import CodeTreeSummarizer
from codeindexrouter import CodeIndexRouter, RouterNavigationError, RouterAnswerError


class Colors:
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"


async def main() -> None:
    target_project = os.getenv("PROJECT_DIR", ".")
    index_file = os.getenv("INDEX_FILE", "code_index.json")
    local_llm_url = os.getenv(
        "ROUTER_API_URL", "http://localhost:8080/v1/chat/completions"
    )

    # 1. Check if code has changed
    current_hash = CodeTreeSummarizer.get_project_hash(target_project)
    requires_indexing = True

    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            try:
                existing_data = json.load(f)
                if existing_data.get("meta", {}).get("project_hash") == current_hash:
                    print("Code unchanged. Skipping indexing and loading cache...")
                    requires_indexing = False
                else:
                    print("Code change detected! Starting re-indexing...")
            except json.JSONDecodeError:
                print("Index file corrupt. Creating new...")

    summarizer: CodeTreeSummarizer | None = None

    if requires_indexing:
        print("Scanning project structure (AST)...")
        builder = CodeTreeBuilder(target_project)
        raw_tree = builder.build_tree()

        print("Generating logical summaries in parallel...")
        summarizer = CodeTreeSummarizer(
            api_url=local_llm_url, max_concurrent_requests=10
        )
        enriched_tree = await summarizer.enrich_tree(raw_tree)

        final_index = {
            "meta": {"project_hash": current_hash},
            "tree": enriched_tree,
        }

        # Atomic write to prevent corruption
        temp_file = f"{index_file}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(final_index, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, index_file)

        print("CodeIndex updated and saved!")

    # 2. Initialize router & chat interface
    print("\n" + "=" * 50)
    print(" code-index CLI interface active ")
    print(" (Type 'exit' or 'q' to quit)")
    print("=" * 50 + "\n")

    router = CodeIndexRouter(index_file_path=index_file)

    try:
        while True:
            try:
                query = input("\nYour code question > ").strip()
                if not query:
                    continue
                if query.lower() in ["exit", "q"]:
                    print("Goodbye!")
                    break

                print("Analyzing structure and generating answer...")
                result = await router.search(query)

                print(f"\n{Colors.BOLD}{Colors.GREEN}Result:{Colors.END}")
                print(f"   {Colors.CYAN}File:{Colors.END}   {result['target_file']}")
                print(f"   {Colors.CYAN}Node:{Colors.END}    {result['target_node']}")
                print(f"\n{Colors.BOLD}Answer:{Colors.END}\n{result['answer']}")

            except RouterNavigationError as e:
                print(f"\n{Colors.YELLOW}Navigation failed:{Colors.END} {e}")
            except RouterAnswerError as e:
                print(f"\n{Colors.RED}Answer generation failed:{Colors.END} {e}")
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"\nUnexpected error: {e}")
    finally:
        await router.close()
        if summarizer is not None:
            await summarizer.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
