#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: logout_bench.sh -n <1..100000> [-b <base_url>]

Examples:
  ./scripts/logout_bench.sh -n 1000
  ./scripts/logout_bench.sh -n 1000 -b http://localhost:8080
USAGE
}

BASE_URL="http://localhost:8080"
N=""

while getopts ":n:b:h" opt; do
  case "$opt" in
    n) N="$OPTARG" ;;
    b) BASE_URL="$OPTARG" ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "$N" ]]; then
  usage
  exit 1
fi

if ! [[ "$N" =~ ^[0-9]+$ ]] || (( N < 1 || N > 100000 )); then
  echo "n must be between 1 and 100000"
  exit 1
fi

for ((i=1; i<=N; i++)); do
  curl -s -o /dev/null -X POST "$BASE_URL/logout"
done
