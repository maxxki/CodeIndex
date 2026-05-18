import ast
import inspect
import textwrap

class CodeSnippetSlicer:
    """Extrahiert gezielt Funktions- oder Methoden-Code aus einer Datei via AST."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        with open(file_path, "r", encoding="utf-8") as f:
            self.source_lines = f.readlines()
            self.source = "".join(self.source_lines)
        try:
            self.tree = ast.parse(self.source, filename=file_path)
        except SyntaxError as e:
            raise ValueError(f"AST-Parse fehlgeschlagen für {file_path}: {e}")

    def _find_node(self, class_name: str | None, method_name: str | None):
        """Sucht den AST-Node für Klasse+Methode oder standalone Funktion."""
        for node in ast.walk(self.tree):
            # Standalone-Funktion
            if class_name is None and isinstance(node, ast.FunctionDef):
                if node.name == method_name:
                    return node
            # Methode innerhalb einer Klasse
            if class_name and isinstance(node, ast.ClassDef) and node.name == class_name:
                for child in ast.walk(node):
                    if isinstance(child, ast.FunctionDef) and child.name == method_name:
                        return child
            # Nur die Klasse selbst
            if class_name and method_name is None:
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    return node
        return None

    def extract(
        self,
        class_name: str | None = None,
        method_name: str | None = None,
        context_lines: int = 3,
        max_tokens_approx: int = 1500
    ) -> str:
        """
        Schneidet den relevanten Code-Snippet aus.
        
        - class_name=None + method_name="foo"  -> standalone Funktion foo
        - class_name="Bar" + method_name="baz" -> Methode Bar.baz
        - class_name="Bar" + method_name=None  -> gesamte Klasse Bar
        
        context_lines: Zeilen vor/nach dem Snippet als Kontext-Buffer
        max_tokens_approx: Harte Grenze (1 Token ≈ 4 Zeichen)
        """
        target_node = self._find_node(class_name, method_name)

        if target_node is None:
            raise LookupError(
                f"Node nicht gefunden: class='{class_name}', method='{method_name}'"
            )

        # AST liefert 1-basierte Zeilennummern
        start = max(0, target_node.lineno - 1 - context_lines)
        end = min(len(self.source_lines), target_node.end_lineno + context_lines)

        snippet_lines = self.source_lines[start:end]
        snippet = textwrap.dedent("".join(snippet_lines))

        # Harte Token-Grenze: lieber abschneiden als das Modell überfluten
        max_chars = max_tokens_approx * 4
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars] + "\n# ... [TRUNCATED: Snippet überschreitet Token-Limit]"

        return snippet
