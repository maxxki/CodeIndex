#!/usr/bin/env bash
# =============================================================================
# start_codeindex.sh — MAXXKI CodeIndex Stack Launcher (v3 Principal)
# =============================================================================
# ÄNDERUNGEN v3:
#   - Python-Versionsprüfung (3.11+)
#   - set -x Option für Debug-Modus via ENV
#   - Health-Check mit Retry-Backoff
# =============================================================================

set -euo pipefail

# Optional: Debug mode
[[ "${DEBUG:-0}" == "1" ]] && set -x

# Load .env if present
if [[ -f ".env" ]]; then
    # shellcheck disable=SC1091
    set -o allexport
    source .env
    set +o allexport
fi

# ---------------------------------------------------------------------------
# Configuration — Defaults (overridden by .env or ENV vars)
# ---------------------------------------------------------------------------
LLAMA_BIN="${LLAMA_BIN:-llama-server}"
MODELS_DIR="${MODELS_DIR:-$HOME/llama.cpp/models}"

MODEL_ROUTER="${MODEL_ROUTER:-qwen2.5-coder-1.5b-instruct-q4_k_m.gguf}"
MODEL_ANSWER="${MODEL_ANSWER:-qwen2.5-coder-3b-instruct-iq4_xs.gguf}"

PORT_ROUTER="${PORT_ROUTER:-8080}"
PORT_ANSWER="${PORT_ANSWER:-8081}"
THREADS="${THREADS:-3}"
CTX_ROUTER="${CTX_ROUTER:-4096}"
CTX_ANSWER="${CTX_ANSWER:-4096}"
SLOTS_ROUTER="${SLOTS_ROUTER:-4}"
SLOTS_ANSWER="${SLOTS_ANSWER:-1}"

READY_TIMEOUT=60
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
LOG_DIR="${PROJECT_DIR}/.logs"
mkdir -p "$LOG_DIR"

PID_ROUTER=""
PID_ANSWER=""

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutdown initiated — stopping servers...${NC}"

    if [[ -n "$PID_ROUTER" ]] && kill -0 "$PID_ROUTER" 2>/dev/null; then
        kill "$PID_ROUTER" 2>/dev/null || true
        echo -e "   ${CYAN}Router server (PID $PID_ROUTER) stopped${NC}"
    fi

    if [[ -n "$PID_ANSWER" ]] && kill -0 "$PID_ANSWER" 2>/dev/null; then
        kill "$PID_ANSWER" 2>/dev/null || true
        echo -e "   ${CYAN}Answer server (PID $PID_ANSWER) stopped${NC}"
    fi

    echo -e "${GREEN}Cleanup complete.${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM ERR

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

check_binary() {
    if ! command -v "$LLAMA_BIN" &>/dev/null && ! [[ -x "$LLAMA_BIN" ]]; then
        echo -e "${RED}'$LLAMA_BIN' not found or not executable.${NC}"
        echo "    Set LLAMA_BIN=/path/to/llama-server (in .env or as ENV variable)."
        exit 1
    fi
}

check_python() {
    if ! command -v python3 &>/dev/null; then
        echo -e "${RED}python3 not found.${NC}"
        exit 1
    fi
    local py_version
    py_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    local major minor
    major=$(echo "$py_version" | cut -d. -f1)
    minor=$(echo "$py_version" | cut -d. -f2)
    if [[ "$major" -lt 3 ]] || [[ "$major" -eq 3 && "$minor" -lt 11 ]]; then
        echo -e "${RED}Python 3.11+ required, found ${py_version}.${NC}"
        exit 1
    fi
    echo -e "   ${GREEN}Python ${py_version} OK.${NC}"
}

check_model() {
    local model_path="$1"
    local label="$2"
    if [[ ! -f "$model_path" ]]; then
        echo -e "${RED}$label not found:${NC}"
        echo "    $model_path"
        echo "    Set MODELS_DIR and MODEL_ROUTER/MODEL_ANSWER in .env."
        exit 1
    fi
}

wait_for_server() {
    local port="$1"
    local label="$2"
    local elapsed=0
    local backoff=1

    echo -ne "   ${CYAN}Waiting for $label (port $port)${NC}"

    until curl -sf "http://localhost:${port}/health" 2>/dev/null | grep -q '"status":"ok"' 2>/dev/null; do
        if (( elapsed >= READY_TIMEOUT )); then
            echo ""
            echo -e "${RED}Timeout: $label not responding after ${READY_TIMEOUT}s.${NC}"
            echo "    Log: ${LOG_DIR}/${label,,}.log"
            cleanup
        fi
        echo -n "."
        sleep "$backoff"
        elapsed=$((elapsed + backoff))
        backoff=$((backoff < 5 ? backoff + 1 : 5))  # Cap at 5s
    done

    echo -e " ${GREEN}ready! (${elapsed}s)${NC}"
}

print_banner() {
    echo ""
    echo -e "${BOLD}${CYAN}"
    echo "  ╔══════════════════════════════════════════╗"
    echo "  ║     MAXXKI CodeIndex Stack Launcher      ║"
    echo "  ╚══════════════════════════════════════════╝"
    echo -e "${NC}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print_banner

echo -e "${BOLD}Checking prerequisites...${NC}"
check_binary
check_python
check_model "${MODELS_DIR}/${MODEL_ROUTER}" "Router model (${MODEL_ROUTER})"
check_model "${MODELS_DIR}/${MODEL_ANSWER}" "Answer model (${MODEL_ANSWER})"
echo -e "   ${GREEN}All prerequisites met.${NC}"
echo ""

# ---------------------------------------------------------------------------
# Server A — Router
# ---------------------------------------------------------------------------
echo -e "${BOLD}Starting router server on port ${PORT_ROUTER}...${NC}"
echo "    Model  : $MODEL_ROUTER"
echo "    Context: ${CTX_ROUTER} tokens | Slots: ${SLOTS_ROUTER} | Threads: ${THREADS}"

"$LLAMA_BIN" \
    --host "127.0.0.1" \
    --model "${MODELS_DIR}/${MODEL_ROUTER}" \
    --port "$PORT_ROUTER" \
    --ctx-size "$CTX_ROUTER" \
    --parallel "$SLOTS_ROUTER" \
    --threads "$THREADS" \
    --log-disable \
    > "${LOG_DIR}/router.log" 2>&1 &

PID_ROUTER=$!
echo "    PID: $PID_ROUTER — Log: ${LOG_DIR}/router.log"
wait_for_server "$PORT_ROUTER" "Router-Server"
echo ""

# ---------------------------------------------------------------------------
# Server B — Answer
# ---------------------------------------------------------------------------
echo -e "${BOLD}Starting answer server on port ${PORT_ANSWER}...${NC}"
echo "    Model  : $MODEL_ANSWER"
echo "    Context: ${CTX_ANSWER} tokens | Slots: ${SLOTS_ANSWER} | Threads: ${THREADS}"

"$LLAMA_BIN" \
    --host "127.0.0.1" \
    --model "${MODELS_DIR}/${MODEL_ANSWER}" \
    --port "$PORT_ANSWER" \
    --ctx-size "$CTX_ANSWER" \
    --parallel "$SLOTS_ANSWER" \
    --threads "$THREADS" \
    --log-disable \
    > "${LOG_DIR}/answer.log" 2>&1 &

PID_ANSWER=$!
echo "    PID: $PID_ANSWER — Log: ${LOG_DIR}/answer.log"
wait_for_server "$PORT_ANSWER" "Answer-Server"
echo ""

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Both servers running — stack ready!  ${NC}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo -e "  Router  → ${CYAN}http://localhost:${PORT_ROUTER}${NC}  (${MODEL_ROUTER})"
echo -e "  Answer  → ${CYAN}http://localhost:${PORT_ANSWER}${NC}  (${MODEL_ANSWER})"
echo ""
echo -e "  Logs    → ${LOG_DIR}/"
echo -e "  Stop    → ${YELLOW}Ctrl+C${NC}"
echo ""

# ---------------------------------------------------------------------------
# main.py
# ---------------------------------------------------------------------------
echo -e "${BOLD}Starting main.py in: ${PROJECT_DIR}${NC}"
echo "──────────────────────────────────────────"
echo ""

cd "$PROJECT_DIR"
python3 main.py

echo ""
echo -e "${GREEN}main.py finished.${NC}"
cleanup
