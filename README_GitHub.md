<div align="center">

# 🔍 MAXXKI CodeIndex

**Local-first, offline Code Intelligence — powered by llama.cpp**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-40%2F40%20passing-brightgreen.svg)]()
[![Architecture](https://img.shields.io/badge/architecture-3--stage%20RAG-orange.svg)]()

*Ask natural-language questions about your codebase. No API keys. No cloud. Runs on a consumer PC.*

</div>

---

## 🚀 What is CodeIndex?

MAXXKI CodeIndex is a **fully local, offline code Q&A system** that understands your Python codebase through AST analysis and routes questions to the right file, class, and method — using only local LLMs via [llama.cpp](https://github.com/ggerganov/llama.cpp).

```
Your Question
     │
     ▼
┌─────────────────────────┐
│  🧭 Router LLM (1.5B)   │  ← Picks the right file + method
│     Schema-constrained   │     (JSON enum, zero hallucination)
└─────────────────────────┘
     │
     ▼
┌─────────────────────────┐
│  ✂️  AST Slicer         │  ← Extracts exact code snippet
│     No regex. No guess.  │     (AST node.body, not text search)
└─────────────────────────┘
     │
     ▼
┌─────────────────────────┐
│  🧠 Answer LLM (3B+)    │  ← Explains the snippet
│     Context-aware        │     (never sees the whole repo)
└─────────────────────────┘
     │
     ▼
  💡 Precise Answer
```

**Three-stage pipeline** keeps token usage minimal:
- The **router** never sees full source code
- The **answer model** never sees the whole repo
- Only the **relevant snippet** enters the context window

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔒 **100% Offline** | No API keys, no telemetry, no cloud dependency |
| 🧠 **AST-Powered** | Parses Python via `ast` module — understands classes, methods, nested functions |
| ⚡ **Async-Aware** | Full support for `async def` / `await` (Python 3.5+) |
| 🎯 **Ghost-Match Free** | `node.body` iteration prevents false matches from nested classes/functions |
| 🛡️ **Security-Hardened** | `realpath()` symlink resolution, prompt injection sanitization, path traversal protection |
| 💾 **Smart Caching** | SHA-256 hash invalidation — re-indexes only when code changes |
| 🔄 **Parallel Summaries** | Async LLM calls with semaphore-controlled concurrency |
| 📦 **Atomic Writes** | Index corruption impossible (`temp` → `os.replace`) |

---

## 🖥️ Demo

```bash
$ ./start_codeindex.sh

  ╔══════════════════════════════════════════╗
  ║     MAXXKI CodeIndex Stack Launcher      ║
  ╚══════════════════════════════════════════╝

Starting router server on port 8080...
Starting answer server on port 8081...

──────────────────────────────────────────

Your code question > Where is the SHA-256 hash for cache invalidation calculated?

Analyzing structure and generating answer...

Result:
   File:   codetreesummarizer.py
   Node:   Method: CodeTreeSummarizer.get_project_hash

Answer:
The hash is computed in get_project_hash() via hashlib.sha256 over all
.py files in the project directory. It serves as a cache invalidator:
when the hash changes, the index is automatically rebuilt.
```

---

## 📋 Requirements

- **OS:** Linux / macOS (Windows via WSL)
- **Python:** 3.11+
- **llama.cpp:** Built from source
- **RAM:** ~2 GB for default model combo (1.5B + 3B Q4_K_M)
- **Models:** Two GGUF files (router + answer)

---

## ⚡ Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/yourname/codeindex.git
cd codeindex
pip install -r requirements.txt
```

### 2. Build llama.cpp

```bash
git clone https://github.com/ggerganov/llama.cpp ../llama.cpp
cd ../llama.cpp
cmake -B build -DGGML_NATIVE=ON
cmake --build build --config Release -j$(nproc)
```

### 3. Download Models

**Recommended combo (~2 GB total, tested):**

```bash
# Router — fast, instruction-following (Port 8080)
./build/bin/llama-cli \
  --hf-repo Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF \
  --hf-file qwen2.5-coder-1.5b-instruct-q4_k_m.gguf \
  -o models/

# Answer — smarter, larger context (Port 8081)
./build/bin/llama-cli \
  --hf-repo Qwen/Qwen2.5-Coder-3B-Instruct-GGUF \
  --hf-file qwen2.5-coder-3b-instruct-iq4_xs.gguf \
  -o models/
```

**Alternative combos:**

| Router | Answer | RAM |
|--------|--------|-----|
| Qwen2.5-Coder-1.5B-Q4_K_M | Qwen2.5-Coder-3B-IQ4_XS | ~2 GB |
| SmolLM2-1.7B-Q4_K_M | Qwen2.5-Coder-7B-Q4_K_M | ~5 GB |
| DeepSeek-Coder-1.3B-Q4_K_M | DeepSeek-Coder-6.7B-Q4_K_M | ~5 GB |

### 4. Configure (optional)

```bash
cp .env.example .env
# Edit .env with your paths
```

### 5. Launch

```bash
./start_codeindex.sh
```

Or with custom paths:
```bash
LLAMA_BIN=/path/to/llama-server \
MODELS_DIR=/path/to/models \
MODEL_ROUTER=qwen2.5-coder-1.5b-instruct-q4_k_m.gguf \
MODEL_ANSWER=qwen2.5-coder-3b-instruct-iq4_xs.gguf \
./start_codeindex.sh
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                               │
│  • Hash check → Index build → CLI loop                       │
│  • Atomic file writes • Graceful shutdown                    │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐  │
│  │ codetreebuilder │  │codetreesummarizer│  │codeindexrouter│ │
│  │ • AST parser    │  │ • LLM summaries  │  │ • 3-stage   │  │
│  │ • Class/method  │  │ • Parallel async │  │   routing   │  │
│  │ • Nested func   │  │ • Semaphore ctrl │  │ • Schema    │  │
│  │   metadata      │  │ • Exponential    │  │   constrain │  │
│  │                 │  │   backoff        │  │ • Security  │  │
│  └─────────────────┘  └─────────────────┘  └─────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐                    │
│  │codesnippetslicer│  │     models.py    │                    │
│  │ • AST extraction│  │ • TypedDict      │                    │
│  │ • node.body     │  │ • flatten_files  │                    │
│  │ • Indentation   │  │ • Type safety    │                    │
│  │   preservation  │  │                  │                    │
│  └─────────────────┘  └─────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

| File | Role | Lines |
|------|------|-------|
| `main.py` | Entry point — hash check, index build, CLI loop | ~100 |
| `codetreebuilder.py` | AST parser — builds file/class/method tree | ~120 |
| `codetreesummarizer.py` | LLM summarizer — enriches tree with semantic summaries | ~140 |
| `codeindexrouter.py` | Three-stage router — file → node → answer | ~350 |
| `codesnippetslicer.py` | AST slicer — extracts exact code snippets | ~110 |
| `models.py` | TypedDict schemas for the entire pipeline | ~100 |
| `start_codeindex.sh` | Shell launcher — starts both llama-server instances | ~210 |

---

## 🧪 Testing

```bash
# Run full test suite
python3 -m pytest test_ast_logic.py test_router_security.py -v

# With coverage
pytest --cov=. --cov-report=term-missing

# Security tests only
pytest -k "traversal or sanitization"

# AST correctness only
pytest -k "nested or async or ghost"
```

**Test coverage:**
- ✅ AST extraction correctness (standalone, methods, async, nested)
- ✅ Security (path traversal, symlink resolution, prompt injection)
- ✅ Edge cases (unicode, f-strings, decorators, large files)
- ✅ Regression (known bugs from v1/v2 stay fixed)
- ✅ Integration (FastAPI-style realistic codebase)

---

## 🔧 Configuration

All settings are configurable via environment variables or `.env`:

```bash
# API endpoints
ROUTER_API_URL=http://localhost:8080/v1/chat/completions
ANSWER_API_URL=http://localhost:8081/v1/chat/completions

# Project
PROJECT_DIR=/path/to/your/project
INDEX_FILE=code_index.json

# Concurrency
MAX_CONCURRENT_REQUESTS=10
```

---

## 🛡️ Security Model

| Threat | Mitigation |
|--------|-----------|
| **Path Traversal** | `os.path.realpath()` resolves symlinks before `.startswith()` check |
| **Symlink Attack** | Symlinks to `/etc/passwd` etc. are resolved to real paths — blocked if outside `project_root` |
| **Prompt Injection** | `_sanitize_query()` doubles `{`/`}` → prevents JSON template breaking |
| **Token Exhaustion** | Query length capped at 2000 chars |
| **Index Corruption** | Atomic write (`temp` → `os.replace`) guarantees valid JSON |

---

## 🌐 Extending

### Use any OpenAI-compatible backend

```python
router = CodeIndexRouter(
    index_file_path="code_index.json",
    routing_api_url="http://localhost:11434/v1/chat/completions",  # Ollama
    answer_api_url="http://localhost:11434/v1/chat/completions",
)
```

### Index other languages

Extend `CodeTreeBuilder.parse_python_file()` with parsers for JS/TS, Go, Rust, etc. The AST-based architecture is language-agnostic — swap `ast` for `tree-sitter` and the pipeline stays identical.

---

## 📜 License

MIT — do whatever you want with it.

---

<div align="center">

Built with 🔥 by developers who believe code should understand itself.

**Stars appreciated if this saves you a debugging session!**

</div>
