#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ai_bench.sh -n <1..100000> [-b <base_url>] [-s <very-short|short|medium|long|very-long|mixed>] [-m <model>]

Options:
  -s  Prompt profile to send. `mixed` cycles through all five prompt lengths. (default: mixed)
  -m  Optional model override passed to /ai

Examples:
  ./scripts/ai_bench.sh -n 20
  ./scripts/ai_bench.sh -n 20 -s medium
  ./scripts/ai_bench.sh -n 20 -s very-long -m gemma3:1b
USAGE
}

BASE_URL="http://localhost:8080"
N=""
PROMPT_PROFILE="mixed"
MODEL=""
VERY_SHORT_WORDS=10
SHORT_WORDS=30
MEDIUM_WORDS=100
LONG_WORDS=400
VERY_LONG_WORDS=1000
PROFILES=("very-short" "short" "medium" "long" "very-long")

while getopts ":n:b:s:m:h" opt; do
  case "$opt" in
    n) N="$OPTARG" ;;
    b) BASE_URL="$OPTARG" ;;
    s) PROMPT_PROFILE="$OPTARG" ;;
    m) MODEL="$OPTARG" ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "$N" ]]; then
  usage
  exit 1
fi

if ! [[ "$N" =~ ^[0-9]+$ ]] || (( N < 1 || N > 100000 )); then
  echo "n must be between 1 and 100000" >&2
  exit 1
fi

case "$PROMPT_PROFILE" in
  very-short|short|medium|long|very-long|mixed)
    ;;
  *)
    echo "prompt profile must be one of: very-short, short, medium, long, very-long, mixed" >&2
    exit 1
    ;;
esac

json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

count_words() {
  wc -w <<<"$1" | tr -d '[:space:]'
}

build_prompt() {
  local profile="$1"
  local target_words="$SHORT_WORDS"
  local prefix="Summarize these todo planning notes into three concrete action items"
  local -a vocab=(
    project backlog sprint deadline meeting design review testing release
    customer outage onboarding migration cleanup priority estimate tracking
    dependency followup documentation risk qa deploy retro planning status
  )
  local prompt="$prefix"
  local word_count
  local index=0

  case "$profile" in
    very-short) target_words="$VERY_SHORT_WORDS" ;;
    short) target_words="$SHORT_WORDS" ;;
    medium) target_words="$MEDIUM_WORDS" ;;
    long) target_words="$LONG_WORDS" ;;
    very-long) target_words="$VERY_LONG_WORDS" ;;
  esac

  word_count=$(count_words "$prompt")
  while (( word_count < target_words )); do
    prompt+=" ${vocab[index]}"
    index=$(( (index + 1) % ${#vocab[@]} ))
    word_count=$((word_count + 1))
  done

  printf '%s' "$prompt"
}

extract_header() {
  local header_name="$1"
  local header_file="$2"

  grep -i "^${header_name}:" "$header_file" | tail -n 1 | cut -d':' -f2- | tr -d '\r' | sed 's/^ *//' || true
}

HEADERS_FILE=$(mktemp /tmp/easytodo_ai_headers.XXXXXX)
BODY_FILE=$(mktemp /tmp/easytodo_ai_body.XXXXXX)

cleanup() {
  rm -f "$HEADERS_FILE" "$BODY_FILE"
}
trap cleanup EXIT

for ((i=1; i<=N; i++)); do
  CURRENT_PROFILE="$PROMPT_PROFILE"
  if [[ "$PROMPT_PROFILE" == "mixed" ]]; then
    PROFILE_INDEX=$(( (i - 1) % ${#PROFILES[@]} ))
    CURRENT_PROFILE="${PROFILES[$PROFILE_INDEX]}"
  fi

  PROMPT=$(build_prompt "$CURRENT_PROFILE")
  PROMPT_WORDS=$(count_words "$PROMPT")
  PROMPT_CHARS=${#PROMPT}

  REQUEST_BODY=$(printf '{"prompt":"%s"' "$(json_escape "$PROMPT")")
  if [[ -n "$MODEL" ]]; then
    REQUEST_BODY+=$(printf ',"model":"%s"' "$(json_escape "$MODEL")")
  fi
  REQUEST_BODY+='}'

  HTTP_CODE=$(curl -sS \
    -D "$HEADERS_FILE" \
    -o "$BODY_FILE" \
    -w "%{http_code}" \
    -X POST "$BASE_URL/ai" \
    -H "Content-Type: application/json" \
    -d "$REQUEST_BODY")

  if [[ ! "$HTTP_CODE" =~ ^2 ]]; then
    echo "ai failed at iteration $i (HTTP $HTTP_CODE): $(cat "$BODY_FILE")" >&2
    exit 1
  fi

  PROMPT_TOKENS=$(extract_header "X-Prompt-Tokens" "$HEADERS_FILE")
  GENERATED_TOKENS=$(extract_header "X-Generated-Tokens" "$HEADERS_FILE")

  if [[ -z "$PROMPT_TOKENS" || -z "$GENERATED_TOKENS" ]]; then
    echo "missing token headers at iteration $i: $(cat "$HEADERS_FILE")" >&2
    exit 1
  fi

  echo "iteration=$i prompt_profile=$CURRENT_PROFILE prompt_words=$PROMPT_WORDS prompt_chars=$PROMPT_CHARS prompt_tokens=$PROMPT_TOKENS generated_tokens=$GENERATED_TOKENS"
done
