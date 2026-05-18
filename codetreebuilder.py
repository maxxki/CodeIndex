import os
import ast
import json

class CodeTreeBuilder:
    def __init__(self, root_dir):
        self.root_dir = os.path.abspath(root_dir)

    def parse_python_file(self, file_path):
        """Zerlegt eine Python-Datei in Klassen und Methoden via AST."""
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                node = ast.parse(f.read(), filename=file_path)
            except SyntaxError:
                return {"type": "file", "status": "syntax_error"}

        file_structure = {
            "type": "file",
            "classes": {},
            "standalone_functions": []
        }

        for child in node.body:
            # Klassen extrahieren
            if isinstance(child, ast.ClassDef):
                methods = [m.name for m in child.body if isinstance(m, ast.FunctionDef)]
                file_structure["classes"][child.name] = {
                    "type": "class",
                    "methods": methods
                }
            # Standalone-Funktionen extrahieren
            elif isinstance(child, ast.FunctionDef):
                file_structure["standalone_functions"].append(child.name)

        return file_structure

    def build_tree(self, current_dir=None):
        """Baut die hierarchische Baumstruktur des gesamten Repositories."""
        if current_dir is None:
            current_dir = self.root_dir

        tree = {}
        
        # Ignorier-Liste für eine saubere Struktur
        ignored_dirs = {".git", "__pycache__", "node_modules", "venv", ".idea"}

        for item in os.listdir(current_dir):
            item_path = os.path.join(current_dir, item)
            
            if os.path.isdir(item_path):
                if item in ignored_dirs:
                    continue
                # Rekursiver Aufruf für Unterverzeichnisse
                subtree = self.build_tree(item_path)
                if subtree:  # Nur hinzufügen, wenn nicht leer
                    tree[item] = {
                        "type": "directory",
                        "children": subtree
                    }
            
            elif os.path.isfile(item_path) and item.endswith(".py"):
                # Hier klinken wir den AST-Parser für Python-Files ein
                tree[item] = self.parse_python_file(item_path)

        return tree

# --- Quick Test Setup ---
if __name__ == "__main__":
    # Target-Pfad definieren (z.B. ein lokales Projekt-Verzeichnis)
    target_project = "." 
    
    builder = CodeTreeBuilder(target_project)
    code_index_tree = builder.build_tree()
    
    # Schön formatiert ausgeben
    print(json.dumps(code_index_tree, indent=2))
