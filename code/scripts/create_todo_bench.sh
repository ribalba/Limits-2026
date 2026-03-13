#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: create_todo_bench.sh -n <1..100000> -u <username> -p <password> [-b <base_url>] [-t <text_length>] [-f <file_size_bytes>]

Options:
  -t  Text length for the ToDo text field (default: 100)
  -f  File size in bytes for the uploaded file (default: 0 = no file)

Examples:
  ./scripts/create_todo_bench.sh -n 100 -u testuser -p testuser
  ./scripts/create_todo_bench.sh -n 100 -u testuser -p testuser -t 5000 -f 1048576
USAGE
}

BASE_URL="http://localhost:8080"
N=""
USERNAME=""
PASSWORD=""
TEXT_LENGTH=100
FILE_SIZE=0

while getopts ":n:u:p:b:t:f:h" opt; do
  case "$opt" in
    n) N="$OPTARG" ;;
    u) USERNAME="$OPTARG" ;;
    p) PASSWORD="$OPTARG" ;;
    b) BASE_URL="$OPTARG" ;;
    t) TEXT_LENGTH="$OPTARG" ;;
    f) FILE_SIZE="$OPTARG" ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "$N" || -z "$USERNAME" || -z "$PASSWORD" ]]; then
  usage
  exit 1
fi

if ! [[ "$N" =~ ^[0-9]+$ ]] || (( N < 1 || N > 100000 )); then
  echo "n must be between 1 and 100000"
  exit 1
fi

if ! [[ "$TEXT_LENGTH" =~ ^[0-9]+$ ]] || (( TEXT_LENGTH < 0 )); then
  echo "text length must be >= 0"
  exit 1
fi

if ! [[ "$FILE_SIZE" =~ ^[0-9]+$ ]] || (( FILE_SIZE < 0 )); then
  echo "file size must be >= 0"
  exit 1
fi

COOKIE_JAR="/tmp/easytodo_create_cookies.txt"
UPLOAD_PATH="/tmp/easytodo_upload.bin"

cleanup() {
  rm -f "$COOKIE_JAR"
  if (( FILE_SIZE > 0 )); then
    rm -f "$UPLOAD_PATH"
  fi
}
trap cleanup EXIT

# Create sample file if needed
if (( FILE_SIZE > 0 )); then
  dd if=/dev/urandom of="$UPLOAD_PATH" bs=1 count="$FILE_SIZE" status=none
fi

# Generate text payload
if (( TEXT_LENGTH > 0 )); then
  # `head` closes early after enough bytes; with pipefail that can surface tr's SIGPIPE (141).
  set +o pipefail
  TEXT=$(LC_ALL=C tr -dc 'a-zA-Z0-9 ' </dev/urandom | head -c "$TEXT_LENGTH")
  set -o pipefail
else
  TEXT=""
fi

# Login once to get session cookie
LOGIN_RESPONSE=$(curl -sS \
  -c "$COOKIE_JAR" \
  -X POST "$BASE_URL/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")

if ! printf '%s' "$LOGIN_RESPONSE" | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'; then
  echo "login failed for user '$USERNAME': $LOGIN_RESPONSE" >&2
  exit 1
fi

for ((i=1; i<=N; i++)); do
  if (( FILE_SIZE > 0 )); then
    HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
      -b "$COOKIE_JAR" \
      -X POST "$BASE_URL/createToDo" \
      -F "title=Benchmark $i" \
      -F "text=$TEXT" \
      -F "file=@$UPLOAD_PATH")
  else
    HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
      -b "$COOKIE_JAR" \
      -X POST "$BASE_URL/createToDo" \
      -F "title=Benchmark $i" \
      -F "text=$TEXT")
  fi

  if [[ ! "$HTTP_CODE" =~ ^2 ]]; then
    echo "createToDo failed at iteration $i (HTTP $HTTP_CODE)" >&2
    exit 1
  fi
done
