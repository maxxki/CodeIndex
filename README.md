# MAXXKI CodeIndex

**Fully local, offline code Q&A — powered by llama.cpp.**

Ask natural-language questions about your codebase. A small router model navigates the AST index to the right file and method; a larger answer model explains it. No API key. No cloud. Runs on a consumer PC.

```
Deine Frage zum Code > Wo wird der SHA-256 Hash für Index-Invalidierung berechnet?

  Datei  : codetreesummarizer.py
  Node   : Methode: CodeTreeSummarizer.get_project_hash
  Antwort: Der Hash wird in get_project_hash() via hashlib.sha256 über alle
             .py-Dateien des Projekts berechnet und dient als Cache-Invalidator.
```

---

## How it works

```
Your question
     |
     v
[Router LLM - small & fast]
  -> picks the right file   (AST index lookup)
  -> picks the right class/method
     |
     v
[AST Slicer]
  -> cuts out only the relevant code snippet
     |
     v
[Answer LLM - larger & smarter]
  -> generates a precise answer from the snippet
```

Three-stage pipeline keeps token usage minimal: the router never sees full source code, the answer model never sees the whole repo.

---

## Requirements

- Linux / macOS (Windows via WSL)
- [llama.cpp](https://github.com/ggerganov/llama.cpp) built from source
- Python 3.11+
- Two GGUF model files (see below)

---

## Setup

### 1. Clone & install Python deps

```bash
git clone https://github.com/maxxki/CodeIndex
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

### 3. Download models

Two models are needed — one small (router), one medium (answers):

**Recommended combo (tested, ~2 GB total):**

```bash
# Router — fast, instruction-following
./build/bin/llama-cli \
  --hf-repo Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF \
  --hf-file qwen2.5-coder-1.5b-instruct-q4_k_m.gguf \
  -o models/

# Answer — smarter, larger context
./build/bin/llama-cli \
  --hf-repo Qwen/Qwen2.5-Coder-3B-Instruct-GGUF \
  --hf-file qwen2.5-coder-3b-instruct-iq4_xs.gguf \
  -o models/
```

**Alternative combos:**

| Router (Port 8080) | Answer (Port 8081) | RAM  |
|---|---|---|
| `qwen2.5-coder-1.5b-instruct-q4_k_m.gguf` | `qwen2.5-coder-3b-instruct-iq4_xs.gguf` | ~2 GB |
| `smollm2-1.7b-instruct-q4_k_m.gguf` | `qwen2.5-coder-7b-instruct-q4_k_m.gguf` | ~5 GB |
| `deepseek-coder-1.3b-instruct.Q4_K_M.gguf` | `deepseek-coder-6.7b-instruct.Q4_K_M.gguf` | ~5 GB |

Any OpenAI-compatible server works (Ollama, LM Studio, vLLM) — just point the URLs in `.env`.

### 4. Configure paths

```bash
cp .env.example .env
# Edit .env with your paths
```

### 5. Run

```bash
./start_codeindex.sh
```

Or manually with custom paths:

```bash
LLAMA_BIN=/path/to/llama-server \
MODELS_DIR=/path/to/models \
MODEL_ROUTER=qwen2.5-coder-1.5b-instruct-q4_k_m.gguf \
MODEL_ANSWER=qwen2.5-coder-3b-instruct-iq4_xs.gguf \
./start_codeindex.sh
```

---

## Point it at your own project

By default CodeIndex indexes the current directory. To index a different project:

```bash
PROJECT_DIR=/path/to/your/project ./start_codeindex.sh
```

The index is cached in `code_index.json`. On next run, a SHA-256 hash over all `.py` files detects changes and triggers a re-index automatically.

---

## Architecture

| File | Role |
|---|---|
| `main.py` | Entry point — hash check, index build, CLI loop |
| `codetreebuilder.py` | AST parser — builds file/class/method tree |
| `codetreesummarizer.py` | LLM summarizer — enriches tree with semantic summaries (async, parallel) |
| `codeindexrouter.py` | Three-stage router — file → node → answer |
| `codesnippetslicer.py` | AST slicer — extracts exact code snippets |
| `models.py` | TypedDict schemas for the whole pipeline |
| `start_codeindex.sh` | Shell launcher — starts both llama-server instances |

---

## Extending

**Use any OpenAI-compatible backend** — Ollama, LM Studio, vLLM, or a remote API:

```python
# In main.py or codeindexrouter.py:
router = CodeIndexRouter(
    index_file_path="code_index.json",
    routing_api_url="http://localhost:11434/v1/chat/completions",  # Ollama
    answer_api_url="http://localhost:11434/v1/chat/completions",
)
```

**Index other languages** — extend `CodeTreeBuilder.parse_python_file()` with parsers for JS/TS, Go, Rust etc.

---

## License

MIT — do whatever you want with it.

---

## Inspired by

Tree-of-thought routing patterns and local-first LLM tooling. Built to run on a weak i3 with 8 GB RAM.
