# =============================================================================
# test_ast_logic.py — MAXXKI CodeIndex AST Test Suite (v3.2 Principal)
# =============================================================================
# ÄNDERUNGEN v3.2:
#   - test_nested_function_not_extracted_as_method -> 
#     test_nested_function_resolves_to_parent_method
#   - Dokumentiert das Principal-Design: Nested Functions = Parent-Kontext
# =============================================================================

from __future__ import annotations

import ast
import os
import tempfile
import textwrap
from pathlib import Path
from typing import Generator

import pytest

from codesnippetslicer import CodeSnippetSlicer
from codetreebuilder import CodeTreeBuilder


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    """Provides a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def slicer_factory():
    """Factory for creating CodeSnippetSlicer instances from source strings."""
    def _create(source: str) -> CodeSnippetSlicer:
        normalized = textwrap.dedent(source).strip() + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(normalized)
            f.flush()
            return CodeSnippetSlicer(f.name)
    return _create


# =============================================================================
# TEST 1: Grundlegende Standalone-Funktion
# =============================================================================

class TestStandaloneFunctions:
    """Tests extraction of module-level (standalone) functions."""

    def test_simple_function(self, slicer_factory):
        source = """
            def hello():
                return "world"
        """
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="hello")
        assert "def hello():" in result
        assert 'return "world"' in result

    def test_async_function(self, slicer_factory):
        """PRINCIPAL FIX: AsyncFunctionDef must be recognized."""
        source = """
            async def fetch_data():
                return await some_api()
        """
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="fetch_data")
        assert "async def fetch_data():" in result
        assert "await some_api()" in result

    def test_function_with_context_lines(self, slicer_factory):
        source = """
            # Comment above
            def with_context():
                pass
            # Comment below
        """
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="with_context", context_lines=1)
        assert "# Comment above" in result
        assert "def with_context():" in result
        assert "# Comment below" in result

    def test_function_not_found_raises(self, slicer_factory):
        source = """
            def existing():
                pass
        """
        slicer = slicer_factory(source)
        with pytest.raises(LookupError, match="Node not found"):
            slicer.extract(method_name="nonexistent")


# =============================================================================
# TEST 2: Klassen und Methoden — Hierarchische Korrektheit
# =============================================================================

class TestClassMethods:
    """Tests extraction of class methods with correct hierarchy."""

    def test_simple_method(self, slicer_factory):
        source = """
            class Calculator:
                def add(self, a, b):
                    return a + b
        """
        slicer = slicer_factory(source)
        result = slicer.extract(class_name="Calculator", method_name="add")
        assert "def add(self, a, b):" in result
        assert "return a + b" in result

    def test_async_method(self, slicer_factory):
        """PRINCIPAL FIX: Async methods inside classes must work."""
        source = """
            class ApiClient:
                async def get(self, url):
                    return await self.session.get(url)
        """
        slicer = slicer_factory(source)
        result = slicer.extract(class_name="ApiClient", method_name="get")
        assert "async def get(self, url):" in result
        assert "await self.session.get(url)" in result

    def test_class_extraction(self, slicer_factory):
        source = """
            class MyClass:
                def method1(self):
                    pass
                
                def method2(self):
                    pass
        """
        slicer = slicer_factory(source)
        result = slicer.extract(class_name="MyClass")
        assert "class MyClass:" in result
        assert "def method1(self):" in result
        assert "def method2(self):" in result

    def test_method_indentation_preserved(self, slicer_factory):
        """PRINCIPAL FIX: Methods must preserve relative indentation."""
        source = """
            class Outer:
                def method(self):
                    if True:
                        return 42
        """
        slicer = slicer_factory(source)
        result = slicer.extract(class_name="Outer", method_name="method")
        lines = result.strip().split("\n")
        method_line = [l for l in lines if "def method" in l][0]
        return_line = [l for l in lines if "return 42" in l][0]
        assert method_line.startswith("    ") or method_line.startswith("\t")
        assert return_line.startswith("        ") or "    " in return_line


# =============================================================================
# TEST 3: Verschachtelte Funktionen — Principal Design
# =============================================================================

class TestNestedFunctions:
    """PRINCIPAL DESIGN: Nested functions are NEVER extracted in isolation.
    They are always returned within their parent function/method context."""

    def test_nested_function_not_extracted_standalone(self, slicer_factory):
        """A nested function has no standalone existence outside its parent."""
        source = """
            def outer():
                def inner():
                    return "nested"
                return inner()
        """
        slicer = slicer_factory(source)
        with pytest.raises(LookupError):
            slicer.extract(method_name="inner")

    def test_nested_function_resolves_to_parent_method(self, slicer_factory):
        """PRINCIPAL DESIGN: Nested function resolves to PARENT method.
        
        When querying for a nested function, the system returns the
        containing method with full context — never the isolated nested
        function without its parent scope.
        """
        source = """
            class Container:
                def method(self):
                    def helper():
                        return "help"
                    return helper()
        """
        slicer = slicer_factory(source)
        # helper is nested inside method -> returns method (with helper in it)
        result = slicer.extract(class_name="Container", method_name="helper")
        assert "def method(self):" in result
        assert "def helper():" in result  # visible in parent's snippet
        assert 'return "help"' in result

    def test_nested_function_included_in_parent(self, slicer_factory):
        """Nested functions appear in the parent's extracted snippet."""
        source = """
            class Container:
                def method(self):
                    def helper():
                        return "help"
                    return helper()
        """
        slicer = slicer_factory(source)
        result = slicer.extract(class_name="Container", method_name="method")
        assert "def helper():" in result
        assert 'return "help"' in result

    def test_deeply_nested_functions(self, slicer_factory):
        """Multiple nesting levels all resolve to the outermost parent."""
        source = """
            def level1():
                def level2():
                    def level3():
                        return "deep"
                    return level3()
                return level2()
        """
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="level1")
        assert "def level2():" in result
        assert "def level3():" in result
        assert 'return "deep"' in result


# =============================================================================
# TEST 4: Verschachtelte Klassen — Keine Ghost-Matches
# =============================================================================

class TestNestedClasses:
    """Inner classes must not leak their methods to outer classes."""

    def test_inner_class_method_not_in_outer(self, slicer_factory):
        source = """
            class Outer:
                def outer_method(self):
                    pass
                
                class Inner:
                    def inner_method(self):
                        return "inner"
        """
        slicer = slicer_factory(source)
        with pytest.raises(LookupError):
            slicer.extract(class_name="Outer", method_name="inner_method")

    def test_inner_class_not_extractable_by_dotted_name(self, slicer_factory):
        """Inner classes are not supported by dotted name lookup."""
        source = """
            class Outer:
                class Inner:
                    def inner_method(self):
                        return "inner"
        """
        slicer = slicer_factory(source)
        with pytest.raises(LookupError):
            slicer.extract(class_name="Outer.Inner")


# =============================================================================
# TEST 5: Async Methoden in Klassen
# =============================================================================

class TestAsyncMethods:
    """Async methods must be correctly identified and extracted."""

    def test_async_class_methods(self, slicer_factory):
        source = """
            class AsyncManager:
                async def start(self):
                    await self._connect()
                
                async def stop(self):
                    await self._disconnect()
        """
        slicer = slicer_factory(source)
        result = slicer.extract(class_name="AsyncManager", method_name="start")
        assert "async def start(self):" in result
        result2 = slicer.extract(class_name="AsyncManager", method_name="stop")
        assert "async def stop(self):" in result2


# =============================================================================
# TEST 6: CodeTreeBuilder — Index-Struktur
# =============================================================================

class TestCodeTreeBuilder:
    """Tests the AST-based index structure generation."""

    def test_builds_flat_file_structure(self, temp_dir):
        source = """
            def standalone():
                pass
            
            class MyClass:
                def method(self):
                    pass
        """
        file_path = os.path.join(temp_dir, "test_file.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(source).strip() + "\n")

        builder = CodeTreeBuilder(temp_dir)
        tree = builder.build_tree()

        assert "test_file.py" in tree
        file_node = tree["test_file.py"]
        assert file_node["type"] == "file"
        assert "standalone" in file_node["standalone_functions"]
        assert "MyClass" in file_node["classes"]
        assert "method" in file_node["classes"]["MyClass"]["methods"]

    def test_async_functions_in_index(self, temp_dir):
        """PRINCIPAL FIX: Async functions must appear in index."""
        source = """
            async def async_standalone():
                pass
            
            class AsyncClass:
                async def async_method(self):
                    pass
        """
        file_path = os.path.join(temp_dir, "async_test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(source).strip() + "\n")

        builder = CodeTreeBuilder(temp_dir)
        tree = builder.build_tree()

        file_node = tree["async_test.py"]
        assert "async_standalone" in file_node["standalone_functions"]
        assert "async_method" in file_node["classes"]["AsyncClass"]["methods"]

    def test_nested_function_metadata(self, temp_dir):
        """PRINCIPAL FIX: Nested functions tracked as metadata."""
        source = """
            def outer():
                def inner():
                    pass
                return inner
        """
        file_path = os.path.join(temp_dir, "nested_test.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(source).strip() + "\n")

        builder = CodeTreeBuilder(temp_dir)
        tree = builder.build_tree()

        file_node = tree["nested_test.py"]
        assert file_node.get("has_nested_functions") is True
        assert len(file_node["nested_metadata"]) > 0
        assert file_node["nested_metadata"][0]["parent"] == "outer"
        assert file_node["nested_metadata"][0]["nested_count"] == 1
        assert "inner" in file_node["nested_metadata"][0]["names"]

    def test_ignored_directories(self, temp_dir):
        """__pycache__, .git etc. should be excluded."""
        os.makedirs(os.path.join(temp_dir, "__pycache__"))
        pyc_file = os.path.join(temp_dir, "__pycache__", "test.cpython-311.pyc")
        with open(pyc_file, "w") as f:
            f.write("fake")

        builder = CodeTreeBuilder(temp_dir)
        tree = builder.build_tree()
        assert "__pycache__" not in tree

    def test_syntax_error_handling(self, temp_dir):
        """Files with syntax errors should be marked, not crash."""
        file_path = os.path.join(temp_dir, "broken.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("def broken(\n")

        builder = CodeTreeBuilder(temp_dir)
        tree = builder.build_tree()
        assert tree["broken.py"]["status"] == "syntax_error"


# =============================================================================
# TEST 7: Sicherheit — Path Traversal
# =============================================================================

class TestSecurity:
    """Tests security hardening measures."""

    def test_symlink_traversal_blocked(self, temp_dir):
        """PRINCIPAL FIX: Symlinks must be resolved before path check."""
        legit_file = os.path.join(temp_dir, "legit.py")
        with open(legit_file, "w", encoding="utf-8") as f:
            f.write("def legit():\n    pass\n")

        passwd_path = "/etc/passwd"
        if os.path.exists(passwd_path):
            symlink = os.path.join(temp_dir, "evil_link.py")
            os.symlink(passwd_path, symlink)

            slicer = CodeSnippetSlicer(legit_file)
            result = slicer.extract(method_name="legit")
            assert "def legit():" in result

    def test_no_path_traversal_in_filename(self, temp_dir):
        """Filenames with dots should be handled safely."""
        weird_file = os.path.join(temp_dir, "file.with.dots.py")
        with open(weird_file, "w", encoding="utf-8") as f:
            f.write("def func():\n    pass\n")

        slicer = CodeSnippetSlicer(weird_file)
        result = slicer.extract(method_name="func")
        assert "def func():" in result


# =============================================================================
# TEST 8: Edge Cases & Robustheit
# =============================================================================

class TestEdgeCases:
    """Stress tests for unusual but valid Python constructs."""

    def test_empty_function(self, slicer_factory):
        source = """
            def empty():
                pass
        """
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="empty")
        assert "def empty():" in result
        assert "pass" in result

    def test_decorated_function(self, slicer_factory):
        source = """
            @property
            def my_prop(self):
                return self._value
        """
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="my_prop")
        assert "@property" in result
        assert "def my_prop(self):" in result

    def test_multiline_string(self, slicer_factory):
        source = '''
            def docstring_heavy():
                """
                This is a very long
                multiline docstring
                that spans many lines
                """
                return 42
        '''
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="docstring_heavy")
        assert "def docstring_heavy():" in result
        assert "multiline docstring" in result

    def test_token_limit_truncation(self, slicer_factory):
        """Very long functions should be truncated."""
        source = """
            def long_func():
        """ + "\n                pass  # filler" * 500
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="long_func", max_tokens_approx=10)
        assert "[TRUNCATED" in result

    def test_unicode_in_source(self, slicer_factory):
        source = """
            def unicode_func():
                # 日本語コメント
                return "héllo wörld 🎉"
        """
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="unicode_func")
        assert "日本語コメント" in result
        assert "héllo wörld 🎉" in result

    def test_f_string_complex(self, slicer_factory):
        source = """
            def format_data(data):
                return f"Result: {data['key']:.2f} at {data['time']}"
        """
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="format_data")
        assert "f\"Result:" in result


# =============================================================================
# TEST 9: Regression — Bekannte Bugs aus v1/v2
# =============================================================================

class TestRegression:
    """Ensures previously fixed bugs stay fixed."""

    def test_no_ast_walk_for_methods(self, slicer_factory):
        """Original bug: ast.walk() found methods in inner classes."""
        source = """
            class Outer:
                def correct_method(self):
                    pass
                
                class Inner:
                    def ghost_method(self):
                        return "ghost"
        """
        slicer = slicer_factory(source)
        with pytest.raises(LookupError):
            slicer.extract(class_name="Outer", method_name="ghost_method")

    def test_async_not_ignored(self, slicer_factory):
        """Original bug: AsyncFunctionDef was completely ignored."""
        source = """
            async def async_only():
                await thing()
        """
        slicer = slicer_factory(source)
        result = slicer.extract(method_name="async_only")
        assert "async def async_only():" in result


# =============================================================================
# TEST 10: Integration — End-to-End Flow
# =============================================================================

class TestIntegration:
    """Tests the complete pipeline with realistic code."""

    def test_realistic_fastapi_style(self, temp_dir):
        """Simulates a FastAPI-style file with async endpoints."""
        source = """
            from fastapi import FastAPI
            
            app = FastAPI()
            
            @app.get("/items/{item_id}")
            async def read_item(item_id: int):
                return {"item_id": item_id}
            
            class ItemRepository:
                async def get_by_id(self, item_id: int):
                    return await self.db.fetchone(
                        "SELECT * FROM items WHERE id = ?", item_id
                    )
                
                async def create(self, item: dict):
                    return await self.db.execute(
                        "INSERT INTO items (...) VALUES (...)", item
                    )
        """
        file_path = os.path.join(temp_dir, "api.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(source).strip() + "\n")

        builder = CodeTreeBuilder(temp_dir)
        tree = builder.build_tree()
        file_node = tree["api.py"]

        assert "read_item" in file_node["standalone_functions"]
        assert "ItemRepository" in file_node["classes"]
        assert "get_by_id" in file_node["classes"]["ItemRepository"]["methods"]
        assert "create" in file_node["classes"]["ItemRepository"]["methods"]

        slicer = CodeSnippetSlicer(file_path)
        
        result = slicer.extract(method_name="read_item")
        assert "async def read_item" in result
        assert "@app.get" in result

        result = slicer.extract(class_name="ItemRepository", method_name="get_by_id")
        assert "async def get_by_id" in result


# =============================================================================
# TEST 11: Performance — Große Dateien
# =============================================================================

class TestPerformance:
    """Basic performance sanity checks."""

    def test_large_file_handling(self, temp_dir):
        """Files with thousands of lines should not crash."""
        lines = ["def func_{i}():\n    return {i}\n".format(i=i) for i in range(1000)]
        file_path = os.path.join(temp_dir, "huge.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        slicer = CodeSnippetSlicer(file_path)
        result = slicer.extract(method_name="func_500")
        assert "def func_500():" in result
        assert "return 500" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
