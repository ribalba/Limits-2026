#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: login_bench.sh -n <1..100000> -u <username> -p <password> [-b <base_url>]

Examples:
  ./scripts/login_bench.sh -n 1000 -u testuser -p testuser
  ./scripts/login_bench.sh -n 1000 -u testuser -p testuser -b http://localhost:8080
USAGE
}

BASE_URL="http://localhost:8080"
N=""
USERNAME=""
PASSWORD=""

while getopts ":n:u:p:b:h" opt; do
  case "$opt" in
    n) N="$OPTARG" ;;
    u) USERNAME="$OPTARG" ;;
    p) PASSWORD="$OPTARG" ;;
    b) BASE_URL="$OPTARG" ;;
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

COOKIE_JAR="/tmp/easytodo_login_cookies.txt"

for ((i=1; i<=N; i++)); do
  curl -s -o /dev/null \
    -c "$COOKIE_JAR" \
    -X POST "$BASE_URL/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}"
done

rm -f "$COOKIE_JAR"
