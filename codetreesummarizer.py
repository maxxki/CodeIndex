import os
import hashlib
import asyncio
import httpx
import json
from codetreebuilder import CodeTreeBuilder  # Fix: Import-Name korrigiert

class CodeTreeSummarizer:
    def __init__(self, api_url="http://localhost:8080/v1/chat/completions", max_concurrent_requests=5):
        self.api_url = api_url
        # Semaphor limitiert die parallelen Requests, um das lokale LLM nicht zu crashen
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.system_prompt = (
            "You are a Senior Software Architect. Reply with exactly ONE short, "
            "precise sentence in German explaining the main purpose of the given code artifact. "
            "Do not introduce your answer. No boilerplate."
        )

    async def _get_summary(self, context_type, name, details=""):
        """Fragt das lokale Modell asynchron nach einer prägnanten Zusammenfassung."""
        prompt = f"Analyze this {context_type} named '{name}'. Details: {details}"
        payload = {
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 50
        }

        # Nutzt das Semaphor für kontrollierte Parallelität
        async with self.semaphore:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(self.api_url, json=payload)
                    if response.status_code == 200:
                        result = response.json()
                        return result["choices"][0]["message"]["content"].strip()
            except Exception as e:
                return f"Summary generation failed: {str(e)}"
            return "Keine Zusammenfassung verfügbar."

    async def enrich_tree(self, node):
        """Durchwandert den Baum und sammelt Tasks für die parallele Ausführung."""
        tasks = []
        
        # Interne Hilfsfunktion, um Tasks rekursiv zu sammeln
        def collect_tasks(current_node):
            if not isinstance(current_node, dict):
                return

            if current_node.get("type") == "directory" and "children" in current_node:
                for child_node in current_node["children"].values():
                    collect_tasks(child_node)

            elif current_node.get("type") == "file":
                # Tasks für Standalone-Funktionen queued
                if "standalone_functions" in current_node:
                    orig_funcs = current_node["standalone_functions"]
                    current_node["standalone_functions"] = {}
                    for func_name in orig_funcs:
                        async def wrap_func(f_name=func_name, target_node=current_node):
                            sum_text = await self._get_summary("function", f_name)
                            target_node["standalone_functions"][f_name] = {"type": "function", "summary": sum_text}
                        tasks.append(wrap_func())

                # Tasks für Klassen queued
                if "classes" in current_node:
                    for class_name, class_data in current_node["classes"].items():
                        async def wrap_class(c_name=class_name, c_data=class_data):
                            c_data["summary"] = await self._get_summary("class", c_name)
                        tasks.append(wrap_class())

                        if "methods" in class_data:
                            orig_methods = class_data["methods"]
                            class_data["methods"] = {}
                            for method_name in orig_methods:
                                async def wrap_method(m_name=method_name, c_n=class_name, c_d=class_data):
                                    sum_text = await self._get_summary("method", f"{c_n}.{m_name}")
                                    c_d["methods"][m_name] = {"type": "method", "summary": sum_text}
                                tasks.append(wrap_method())

        collect_tasks(node)
        
        # Hier passiert die Magie: Alle LLM-Calls ballern jetzt parallel raus!
        if tasks:
            print(f"⚡ Schicke {len(tasks)} Requests parallel ans lokale LLM...")
            await asyncio.gather(*tasks)
        
        return node

    @staticmethod
    def get_project_hash(root_dir):
        """Generiert einen SHA-256 Hash über alle Python-Dateien für die Invalidierung."""
        hasher = hashlib.sha256()
        ignored_dirs = {".git", "__pycache__", "node_modules", "venv"}
        
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in sorted(files):
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    with open(file_path, "rb") as f:
                        while chunk := f.read(8192):
                            hasher.update(chunk)
        return hasher.hexdigest()

# --- Asynchroner Runner (Fix: Crash behoben) ---
if __name__ == "__main__":
    async def main():
        target_project = "." 
        builder = CodeTreeBuilder(target_project)
        raw_tree = builder.build_tree()

        # Berechne aktuellen Datei-Hash
        current_hash = CodeTreeSummarizer.get_project_hash(target_project)
        print(f"🔒 Aktueller Projekt-Hash: {current_hash}")

        print("🚀 Starte CodeIndex-Anreicherung...")
        summarizer = CodeTreeSummarizer()
        
        # Fix: Aufruf korrigiert von 'self' auf die Instanz 'summarizer'
        enriched_tree = await summarizer.enrich_tree(raw_tree)
        
        # Meta-Daten an den Index hängen
        final_index = {
            "meta": {"project_hash": current_hash},
            "tree": enriched_tree
        }
        
        print("\n🔥 Fertiger CodeIndex (Struktur + Semantik):")
        print(json.dumps(final_index, indent=2, ensure_ascii=False))

    asyncio.run(main())
