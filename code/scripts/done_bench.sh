#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: done_bench.sh -u <username> -p <password> [-n <1..100000>] [-i <todo_id>] [-b <base_url>] [-d <true|false>]

Examples:
  ./scripts/done_bench.sh -u testuser -p testuser
  ./scripts/done_bench.sh -u testuser -p testuser -n 10
  ./scripts/done_bench.sh -u testuser -p testuser -i 1 -n 1000
USAGE
}

BASE_URL="http://localhost:8080"
N="1"
USERNAME=""
PASSWORD=""
TODO_ID=""
DONE_VALUE="true"

while getopts ":n:u:p:i:b:d:h" opt; do
  case "$opt" in
    n) N="$OPTARG" ;;
    u) USERNAME="$OPTARG" ;;
    p) PASSWORD="$OPTARG" ;;
    i) TODO_ID="$OPTARG" ;;
    b) BASE_URL="$OPTARG" ;;
    d) DONE_VALUE="$OPTARG" ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "$USERNAME" || -z "$PASSWORD" ]]; then
  usage
  exit 1
fi

if ! [[ "$N" =~ ^[0-9]+$ ]] || (( N < 1 || N > 100000 )); then
  echo "n must be between 1 and 100000"
  exit 1
fi

COOKIE_JAR="/tmp/easytodo_done_cookies.txt"

# Login once to get session cookie
curl -s -o /dev/null \
  -c "$COOKIE_JAR" \
  -X POST "$BASE_URL/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}"

mark_done() {
  local todo_id="$1"
  curl -s -o /dev/null \
    -b "$COOKIE_JAR" \
    -X POST "$BASE_URL/done" \
    -H "Content-Type: application/json" \
    -d "{\"id\":$todo_id,\"done\":\"$DONE_VALUE\"}"
}

if [[ -n "$TODO_ID" ]]; then
  for ((i=1; i<=N; i++)); do
    mark_done "$TODO_ID"
  done
else
  TODOS_JSON=$(curl -s \
    -b "$COOKIE_JAR" \
    -X GET "$BASE_URL/getToDos")

  TODO_IDS=()
  if command -v jq >/dev/null 2>&1; then
    mapfile -t TODO_IDS < <(printf '%s' "$TODOS_JSON" | jq -r '.todos[]?.id')
  else
    mapfile -t TODO_IDS < <(
      printf '%s' "$TODOS_JSON" \
        | tr ',' '\n' \
        | sed -n 's/.*"id":[[:space:]]*\([0-9][0-9]*\).*/\1/p'
    )
  fi

  if (( ${#TODO_IDS[@]} == 0 )); then
    echo "no todos found for user: $USERNAME"
    rm -f "$COOKIE_JAR"
    exit 0
  fi

  for ((i=1; i<=N; i++)); do
    for todo_id in "${TODO_IDS[@]}"; do
      mark_done "$todo_id"
    done
  done
fi

rm -f "$COOKIE_JAR"
