import asyncio
import json
import os
import sys
from codetreebuilder import CodeTreeBuilder
from codetreesummarizer import CodeTreeSummarizer
from codeindexrouter import CodeIndexRouter
from codeindexrouter import RouterNavigationError, RouterAnswerError

async def main():
    target_project = "." 
    index_file = "code_index.json"
    local_llm_url = "http://localhost:8080/v1/chat/completions"

    # 1. Prüfen, ob sich der Code verändert hat
    current_hash = CodeTreeSummarizer.get_project_hash(target_project)
    requires_indexing = True

    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            try:
                existing_data = json.load(f)
                if existing_data.get("meta", {}).get("project_hash") == current_hash:
                    print("✅ Code unverändert. Überspringe Indexierung und lade Cache...")
                    requires_indexing = False
                else:
                    print("⚠️ Code-Änderung erkannt! Starte Re-Indexing...")
            except json.JSONDecodeError:
                print("🚨 Index-Datei korrupt. Erstelle neu...")

    if requires_indexing:
        print("📁 Scanne Projektstruktur (AST)...")
        builder = CodeTreeBuilder(target_project)
        raw_tree = builder.build_tree()

        print("🚀 Generiere logische Summaries parallel...")
        summarizer = CodeTreeSummarizer(api_url=local_llm_url, max_concurrent_requests=10)
        enriched_tree = await summarizer.enrich_tree(raw_tree)

        final_index = {"meta": {"project_hash": current_hash}, "tree": enriched_tree}
        
        # Atomic Write to prevent corruption
        temp_file = f"{index_file}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(final_index, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, index_file)
        
        print("💾 CodeIndex aktualisiert und gespeichert!")

    # 2. Router & Chat-Interface initialisieren
    print("\n" + "="*50)
    print(" 🤖 code-index CLI-Interface aktiv ")
    print(" (Schreibe 'exit' oder 'q' zum Beenden)")
    print("="*50 + "\n")

    router = CodeIndexRouter(index_file_path=index_file)

    try:
        while True:
            try:
                query = input("\n🧠 Deine Frage zum Code > ").strip()
                if not query:
                    continue
                if query.lower() in ["exit", "q"]:
                    print("👋 Bis zum nächsten Mal!")
                    break

                print("🔍 Analysiere Struktur und generiere Antwort...")
                result = await router.search(query)
                
                print(f"\n🎯 {colors.BOLD}{colors.GREEN}Ergebnis:{colors.END}")
                print(f"   {colors.CYAN}Datei:{colors.END}   {result['target_file']}")
                print(f"   {colors.CYAN}Node:{colors.END}    {result['target_node']}")
                print(f"\n📝 {colors.BOLD}Antwort:{colors.END}\n{result['answer']}")

            except RouterNavigationError as e:
                print(f"\n🧭 {colors.YELLOW}Navigation fehlgeschlagen:{colors.END} {e}")
            except RouterAnswerError as e:
                print(f"\n💥 {colors.RED}Antwort-Generierung fehlgeschlagen:{colors.END} {e}")
            except KeyboardInterrupt:
                print("\n👋 Bis zum nächsten Mal!")
                break
            except Exception as e:
                print(f"\n🚨 Unerwarteter Fehler: {e}")
    finally:
        await router.close()

# Hilfsklasse für saubere Terminal-Farben
class colors:
    GREEN = '\033[92m'
    CYAN = '\033[96m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'

if __name__ == "__main__":
    # Fix für Windows-Event-Loop (falls nötig, schadet auf Linux nicht)
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
