#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: clickthrough_bench.sh -n <1..100000> -u <username> -p <password> [-b <base_url>] [-t <text_length>] [-f <file_size_bytes>] [-s <very-short|short|medium|long|very-long>] [-g <num_predict>] [-r <seed>] [-T <temperature>]

Description:
  Repeats a full click-through path instead of benchmarking one endpoint in isolation.
  Each iteration performs:
    1. POST /login
    2. POST /deleteAllToDos
    3. POST /createToDo
    4. GET  /getToDos
    5. POST /done
    6. GET  /getToDos
    7. optional POST /ai
    8. POST /logout

Options:
  -t  Text length for the created ToDo body (default: 100)
  -f  File size in bytes for the uploaded attachment (default: 0 = no file)
  -s  Optional AI prompt profile to include once per iteration
  -g  Max generated tokens for the optional AI call (default: 128)
  -r  Random seed for the optional AI call (default: 7)
  -T  Temperature for the optional AI call (default: 0)

Examples:
  ./scripts/clickthrough_bench.sh -n 100 -u testuser -p testuser
  ./scripts/clickthrough_bench.sh -n 100 -u testuser -p testuser -t 10000 -f 102400
  ./scripts/clickthrough_bench.sh -n 20 -u testuser -p testuser -s medium -g 128 -r 7 -T 0
USAGE
}

BASE_URL="http://localhost:8080"
N=""
USERNAME=""
PASSWORD=""
TEXT_LENGTH=100
FILE_SIZE=0
AI_PROFILE=""
NUM_PREDICT=128
SEED=7
TEMPERATURE=0
VERY_SHORT_WORDS=10
SHORT_WORDS=30
MEDIUM_WORDS=100
LONG_WORDS=400
VERY_LONG_WORDS=1000

while getopts ":n:u:p:b:t:f:s:g:r:T:h" opt; do
  case "$opt" in
    n) N="$OPTARG" ;;
    u) USERNAME="$OPTARG" ;;
    p) PASSWORD="$OPTARG" ;;
    b) BASE_URL="$OPTARG" ;;
    t) TEXT_LENGTH="$OPTARG" ;;
    f) FILE_SIZE="$OPTARG" ;;
    s) AI_PROFILE="$OPTARG" ;;
    g) NUM_PREDICT="$OPTARG" ;;
    r) SEED="$OPTARG" ;;
    T) TEMPERATURE="$OPTARG" ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "$N" || -z "$USERNAME" || -z "$PASSWORD" ]]; then
  usage
  exit 1
fi

if ! [[ "$N" =~ ^[0-9]+$ ]] || (( N < 1 || N > 100000 )); then
  echo "n must be between 1 and 100000" >&2
  exit 1
fi

if ! [[ "$TEXT_LENGTH" =~ ^[0-9]+$ ]] || (( TEXT_LENGTH < 0 )); then
  echo "text length must be >= 0" >&2
  exit 1
fi

if ! [[ "$FILE_SIZE" =~ ^[0-9]+$ ]] || (( FILE_SIZE < 0 )); then
  echo "file size must be >= 0" >&2
  exit 1
fi

if ! [[ "$NUM_PREDICT" =~ ^[0-9]+$ ]] || (( NUM_PREDICT < 1 )); then
  echo "num_predict must be >= 1" >&2
  exit 1
fi

if ! [[ "$SEED" =~ ^-?[0-9]+$ ]]; then
  echo "seed must be an integer" >&2
  exit 1
fi

if ! [[ "$TEMPERATURE" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "temperature must be a non-negative number" >&2
  exit 1
fi

if [[ -n "$AI_PROFILE" ]]; then
  case "$AI_PROFILE" in
    very-short|short|medium|long|very-long)
      ;;
    *)
      echo "AI profile must be one of: very-short, short, medium, long, very-long" >&2
      exit 1
      ;;
  esac
fi

COOKIE_JAR="/tmp/easytodo_clickthrough_cookies.txt"
UPLOAD_PATH="/tmp/easytodo_clickthrough_upload.bin"
BODY_FILE=$(mktemp /tmp/easytodo_clickthrough_body.XXXXXX)
HEADERS_FILE=$(mktemp /tmp/easytodo_clickthrough_headers.XXXXXX)
TEXT=""
LAST_HTTP_CODE=""
LAST_BODY=""

cleanup() {
  rm -f "$COOKIE_JAR" "$BODY_FILE" "$HEADERS_FILE"
  if (( FILE_SIZE > 0 )); then
    rm -f "$UPLOAD_PATH"
  fi
}
trap cleanup EXIT

json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

count_words() {
  wc -w <<<"$1" | tr -d '[:space:]'
}

build_ai_prompt() {
  local profile="$1"
  local target_words="$SHORT_WORDS"
  local prefix="Summarize these todo planning notes into exactly three short concrete action items. Keep the response concise."
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
    word_count=$(( word_count + 1 ))
  done

  printf '%s' "$prompt"
}

perform_request() {
  local method="$1"
  local url="$2"
  shift 2

  LAST_HTTP_CODE=$(curl -sS \
    -D "$HEADERS_FILE" \
    -o "$BODY_FILE" \
    -w "%{http_code}" \
    -X "$method" \
    "$url" \
    "$@")
  LAST_BODY=$(cat "$BODY_FILE")
}

expect_http_2xx() {
  local context="$1"
  if [[ ! "$LAST_HTTP_CODE" =~ ^2 ]]; then
    echo "$context failed (HTTP $LAST_HTTP_CODE): $LAST_BODY" >&2
    exit 1
  fi
}

expect_ok_json() {
  local context="$1"
  if ! printf '%s' "$LAST_BODY" | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'; then
    echo "$context returned an unexpected body: $LAST_BODY" >&2
    exit 1
  fi
}

extract_todo_id() {
  printf '%s' "$LAST_BODY" \
    | tr -d '\n' \
    | sed -n 's/.*"todo"[[:space:]]*:[[:space:]]*{[^}]*"id"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p'
}

if (( FILE_SIZE > 0 )); then
  dd if=/dev/urandom of="$UPLOAD_PATH" bs=1 count="$FILE_SIZE" status=none
fi

if (( TEXT_LENGTH > 0 )); then
  set +o pipefail
  TEXT=$(LC_ALL=C tr -dc 'a-zA-Z0-9 ' </dev/urandom | head -c "$TEXT_LENGTH")
  set -o pipefail
fi

for ((i=1; i<=N; i++)); do
  perform_request \
    POST \
    "$BASE_URL/login" \
    -c "$COOKIE_JAR" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}"
  expect_http_2xx "login"
  expect_ok_json "login"

  perform_request POST "$BASE_URL/deleteAllToDos" -b "$COOKIE_JAR"
  expect_http_2xx "deleteAllToDos"
  expect_ok_json "deleteAllToDos"

  if (( FILE_SIZE > 0 )); then
    perform_request \
      POST \
      "$BASE_URL/createToDo" \
      -b "$COOKIE_JAR" \
      -F "title=Clickthrough $i" \
      -F "text=$TEXT" \
      -F "file=@$UPLOAD_PATH"
  else
    perform_request \
      POST \
      "$BASE_URL/createToDo" \
      -b "$COOKIE_JAR" \
      -F "title=Clickthrough $i" \
      -F "text=$TEXT"
  fi
  expect_http_2xx "createToDo"
  expect_ok_json "createToDo"

  TODO_ID=$(extract_todo_id)
  if [[ -z "$TODO_ID" ]]; then
    echo "Unable to extract created todo id from response: $LAST_BODY" >&2
    exit 1
  fi

  perform_request GET "$BASE_URL/getToDos" -b "$COOKIE_JAR"
  expect_http_2xx "getToDos before done"
  expect_ok_json "getToDos before done"

  perform_request \
    POST \
    "$BASE_URL/done" \
    -b "$COOKIE_JAR" \
    -H "Content-Type: application/json" \
    -d "{\"id\":$TODO_ID,\"done\":true}"
  expect_http_2xx "done"
  expect_ok_json "done"

  perform_request GET "$BASE_URL/getToDos" -b "$COOKIE_JAR"
  expect_http_2xx "getToDos after done"
  expect_ok_json "getToDos after done"

  if [[ -n "$AI_PROFILE" ]]; then
    AI_PROMPT=$(build_ai_prompt "$AI_PROFILE")
    AI_REQUEST_BODY=$(printf '{"prompt":"%s","num_predict":%s,"seed":%s,"temperature":%s}' \
      "$(json_escape "$AI_PROMPT")" \
      "$NUM_PREDICT" \
      "$SEED" \
      "$TEMPERATURE")

    perform_request \
      POST \
      "$BASE_URL/ai" \
      -H "Content-Type: application/json" \
      -d "$AI_REQUEST_BODY"
    expect_http_2xx "ai"
    expect_ok_json "ai"
  fi

  perform_request POST "$BASE_URL/logout" -b "$COOKIE_JAR"
  expect_http_2xx "logout"
  expect_ok_json "logout"

  printf 'iteration=%s todo_id=%s text_length=%s file_size=%s ai_profile=%s\n' \
    "$i" \
    "$TODO_ID" \
    "$TEXT_LENGTH" \
    "$FILE_SIZE" \
    "${AI_PROFILE:-none}"
done
