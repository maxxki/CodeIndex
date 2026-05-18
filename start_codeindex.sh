#!/usr/bin/env bash
# =============================================================================
# start_codeindex.sh — MAXXKI CodeIndex Stack Launcher
# =============================================================================

set -euo pipefail

# .env einlesen falls vorhanden
if [[ -f ".env" ]]; then
    # shellcheck disable=SC1091
    set -o allexport
    source .env
    set +o allexport
fi

# ---------------------------------------------------------------------------
# KONFIGURATION — Defaults (werden durch .env oder ENV-Variablen überschrieben)
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
# FARBEN
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# CLEANUP
# ---------------------------------------------------------------------------
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutdown eingeleitet — beende Server...${NC}"

    if [[ -n "$PID_ROUTER" ]] && kill -0 "$PID_ROUTER" 2>/dev/null; then
        kill "$PID_ROUTER"
        echo -e "   ${CYAN}Router-Server (PID $PID_ROUTER) gestoppt${NC}"
    fi

    if [[ -n "$PID_ANSWER" ]] && kill -0 "$PID_ANSWER" 2>/dev/null; then
        kill "$PID_ANSWER"
        echo -e "   ${CYAN}Answer-Server (PID $PID_ANSWER) gestoppt${NC}"
    fi

    echo -e "${GREEN}Cleanup abgeschlossen.${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM ERR

# ---------------------------------------------------------------------------
# HILFSFUNKTIONEN
# ---------------------------------------------------------------------------

check_binary() {
    # Unterstützt sowohl PATH-Binaries als auch absolute Pfade
    if ! command -v "$LLAMA_BIN" &>/dev/null && ! [[ -x "$LLAMA_BIN" ]]; then
        echo -e "${RED}'$LLAMA_BIN' nicht gefunden oder nicht ausführbar.${NC}"
        echo "    Setze LLAMA_BIN=/pfad/zu/llama-server (in .env oder als ENV-Variable)."
        exit 1
    fi
}

check_model() {
    local model_path="$1"
    local label="$2"
    if [[ ! -f "$model_path" ]]; then
        echo -e "${RED}$label nicht gefunden:${NC}"
        echo "    $model_path"
        echo "    Setze MODELS_DIR und MODEL_ROUTER/MODEL_ANSWER in .env."
        exit 1
    fi
}

wait_for_server() {
    local port="$1"
    local label="$2"
    local elapsed=0

    echo -ne "   ${CYAN}Warte auf $label (Port $port)${NC}"

    until curl -sf "http://localhost:${port}/health" | grep -q '"status":"ok"' 2>/dev/null; do
        if (( elapsed >= READY_TIMEOUT )); then
            echo ""
            echo -e "${RED}Timeout: $label antwortet nicht nach ${READY_TIMEOUT}s.${NC}"
            echo "    Log: ${LOG_DIR}/${label,,}.log"
            cleanup
        fi
        echo -n "."
        sleep 2
        (( elapsed += 2 ))
    done

    echo -e " ${GREEN}bereit! (${elapsed}s)${NC}"
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
# MAIN
# ---------------------------------------------------------------------------
print_banner

echo -e "${BOLD}Prüfe Voraussetzungen...${NC}"
check_binary
check_model "${MODELS_DIR}/${MODEL_ROUTER}" "Router-Modell (${MODEL_ROUTER})"
check_model "${MODELS_DIR}/${MODEL_ANSWER}" "Answer-Modell (${MODEL_ANSWER})"
echo -e "   ${GREEN}Alles vorhanden.${NC}"
echo ""

# ---------------------------------------------------------------------------
# SERVER A — Router
# ---------------------------------------------------------------------------
echo -e "${BOLD}Starte Router-Server auf Port ${PORT_ROUTER}...${NC}"
echo "    Modell  : $MODEL_ROUTER"
echo "    Context : ${CTX_ROUTER} Token | Slots: ${SLOTS_ROUTER} | Threads: ${THREADS}"

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
# SERVER B — Answer
# ---------------------------------------------------------------------------
echo -e "${BOLD}Starte Answer-Server auf Port ${PORT_ANSWER}...${NC}"
echo "    Modell  : $MODEL_ANSWER"
echo "    Context : ${CTX_ANSWER} Token | Slots: ${SLOTS_ANSWER} | Threads: ${THREADS}"

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
# STATUS
# ---------------------------------------------------------------------------
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Beide Server laufen — Stack bereit!  ${NC}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo -e "  Router  → ${CYAN}http://localhost:${PORT_ROUTER}${NC}  (${MODEL_ROUTER})"
echo -e "  Answer  → ${CYAN}http://localhost:${PORT_ANSWER}${NC}  (${MODEL_ANSWER})"
echo ""
echo -e "  Logs    → ${LOG_DIR}/"
echo -e "  Stop    → ${YELLOW}Strg+C${NC}"
echo ""

# ---------------------------------------------------------------------------
# MAIN.PY
# ---------------------------------------------------------------------------
echo -e "${BOLD}Starte main.py in: ${PROJECT_DIR}${NC}"
echo "──────────────────────────────────────────"
echo ""

cd "$PROJECT_DIR"
python3 main.py

echo ""
echo -e "${GREEN}main.py beendet.${NC}"
cleanup
