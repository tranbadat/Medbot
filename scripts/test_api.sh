#!/usr/bin/env bash
# Quick smoke-test for MedBot API endpoints.
# Usage (from host):  bash scripts/test_api.sh [BASE_URL]
# Default BASE_URL: http://localhost:8000

set -euo pipefail
BASE="${1:-http://localhost:8000}"
PASS=0; FAIL=0

_ok()  { echo "  ✅  $1"; ((PASS++)); }
_fail(){ echo "  ❌  $1 — $2"; ((FAIL++)); }

check() {
  local label="$1" expected="$2"
  shift 2
  local status
  status=$(curl -s -o /tmp/_resp.json -w "%{http_code}" "$@")
  if [ "$status" = "$expected" ]; then
    _ok "$label (HTTP $status)"
  else
    _fail "$label" "expected $expected, got $status — $(cat /tmp/_resp.json)"
  fi
}

echo ""
echo "=== MedBot API Smoke Tests ==="
echo "    Target: $BASE"
echo ""

# ── Health ─────────────────────────────────────────────────────────────────
echo "── Health ──"
check "GET /health" 200 "$BASE/health"

# ── Admin login ────────────────────────────────────────────────────────────
echo ""
echo "── Admin Auth ──"
ADMIN_TOKEN=$(curl -s -X POST "$BASE/api/admin/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")

if [ -n "$ADMIN_TOKEN" ]; then
  _ok "POST /api/admin/login → token received"
  ((PASS++))
else
  _fail "POST /api/admin/login" "no token in response"
  ((FAIL++))
  echo "Aborting — cannot proceed without admin token."; exit 1
fi

AUTH_ADMIN="-H \"Authorization: Bearer $ADMIN_TOKEN\""

check "GET /api/admin/stats"        200 "$BASE/api/admin/stats"        -H "Authorization: Bearer $ADMIN_TOKEN"
check "GET /api/admin/staff"        200 "$BASE/api/admin/staff"        -H "Authorization: Bearer $ADMIN_TOKEN"
check "GET /api/admin/shifts"       200 "$BASE/api/admin/shifts"       -H "Authorization: Bearer $ADMIN_TOKEN"
check "GET /api/admin/appointments" 200 "$BASE/api/admin/appointments" -H "Authorization: Bearer $ADMIN_TOKEN"
check "GET /api/admin/sessions"     200 "$BASE/api/admin/sessions"     -H "Authorization: Bearer $ADMIN_TOKEN"
check "GET /api/admin/patients"     200 "$BASE/api/admin/patients"     -H "Authorization: Bearer $ADMIN_TOKEN"

# ── Admin: add staff ───────────────────────────────────────────────────────
echo ""
echo "── Admin: Staff CRUD ──"
NEW_STAFF=$(curl -s -X POST "$BASE/api/admin/staff" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"BS. Test","specialty":"Test","username":"test_doc_'$$'","password":"test123","role":"doctor"}')
NEW_ID=$(echo "$NEW_STAFF" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
if [ -n "$NEW_ID" ]; then
  _ok "POST /api/admin/staff → id=$NEW_ID"
  ((PASS++))
  # Update
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/api/admin/staff/$NEW_ID" \
    -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
    -d '{"working_hours":"9:00-18:00"}')
  [ "$STATUS" = "200" ] && { _ok "PUT /api/admin/staff/$NEW_ID"; ((PASS++)); } || { _fail "PUT /api/admin/staff" "HTTP $STATUS"; ((FAIL++)); }
  # Deactivate
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/api/admin/staff/$NEW_ID" \
    -H "Authorization: Bearer $ADMIN_TOKEN")
  [ "$STATUS" = "200" ] && { _ok "DELETE /api/admin/staff/$NEW_ID"; ((PASS++)); } || { _fail "DELETE /api/admin/staff" "HTTP $STATUS"; ((FAIL++)); }
else
  _fail "POST /api/admin/staff" "$NEW_STAFF"
  ((FAIL++))
fi

# ── Doctor login ───────────────────────────────────────────────────────────
echo ""
echo "── Doctor Auth ──"
DOCTOR_RESP=$(curl -s -X POST "$BASE/api/doctor/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"doctor1","password":"doctor123"}')
DOCTOR_TOKEN=$(echo "$DOCTOR_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || true)
if [ -n "$DOCTOR_TOKEN" ]; then
  _ok "POST /api/doctor/login → token received"
  ((PASS++))
  check "GET /api/doctor/cases"        200 "$BASE/api/doctor/cases"        -H "Authorization: Bearer $DOCTOR_TOKEN"
  check "GET /api/doctor/appointments" 200 "$BASE/api/doctor/appointments" -H "Authorization: Bearer $DOCTOR_TOKEN"
else
  _fail "POST /api/doctor/login" "no token — is demo doctor seeded? ($DOCTOR_RESP)"
  ((FAIL++))
fi

# ── Chat (AI) ─────────────────────────────────────────────────────────────
echo ""
echo "── Chat endpoint ──"
CHAT_RESP=$(curl -s -X POST "$BASE/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"telegram_chat_id":999999,"user_id":"tg_999999","message":"Xin chào"}')
CHAT_TYPE=$(echo "$CHAT_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('type',''))" 2>/dev/null || true)
if [[ "$CHAT_TYPE" == "ai_reply" || "$CHAT_TYPE" == "request_doctor" ]]; then
  _ok "POST /api/chat → type=$CHAT_TYPE"
  ((PASS++))
else
  _fail "POST /api/chat" "unexpected type: $CHAT_TYPE — $CHAT_RESP"
  ((FAIL++))
fi

# ── Online doctors ─────────────────────────────────────────────────────────
echo ""
echo "── Doctors online ──"
check "GET /api/doctors/online" 200 "$BASE/api/doctors/online"

# ── Admin bad auth ─────────────────────────────────────────────────────────
echo ""
echo "── Auth guards ──"
check "GET /api/admin/stats (no token → 401)" 401 "$BASE/api/admin/stats"
check "POST /api/admin/login (wrong pw → 401)" 401 "$BASE/api/admin/login" \
  -X POST -H "Content-Type: application/json" -d '{"username":"admin","password":"wrong"}'
check "GET /api/doctor/cases (no token → 401)" 401 "$BASE/api/doctor/cases"

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo "============================="
echo "  PASSED: $PASS  |  FAILED: $FAIL"
echo "============================="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
