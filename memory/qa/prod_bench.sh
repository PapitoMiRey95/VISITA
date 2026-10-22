#!/usr/bin/env bash
# Read-only Production latency benchmark (GET only, no writes). Usage: prod_bench.sh <label>
BASE=https://visitaemr.com
LABEL=${1:-run}
OUT=/app/memory/qa/prod_bench_$LABEL.txt
: > "$OUT"
bench() {
  local name=$1 url=$2
  for i in 1 2 3 4 5; do
    t=$(curl -s -o /dev/null -w "%{http_code} %{time_total}" "$url")
    echo "$name run$i $t" >> "$OUT"
  done
}
bench api_health "$BASE/api/health"
bench clinic_public "$BASE/api/practices/dr-aguayo/profile"
bench spa_index "$BASE/"
bench portal_login_page "$BASE/login"
bench api_unauth_appointments "$BASE/api/internal/appointments"
cat "$OUT"
