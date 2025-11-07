#!/bin/bash
# Test all Web UI endpoints to find missing ones

OUTPUT_DIR="/app/test_results/webui"
mkdir -p "$OUTPUT_DIR"

echo "=== Web UI Endpoint Tests ===" | tee "$OUTPUT_DIR/summary.txt"

# Get admin password for login
ADMIN_PASS=$(python3 -m nomarr.manage_password --show 2>/dev/null | grep -v "Current admin password:" | tr -d ' \n')
echo "Admin password: $ADMIN_PASS" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 1: Login
echo -e "\n[1] Testing login..." | tee -a "$OUTPUT_DIR/summary.txt"
LOGIN_RESPONSE=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -d "{\"password\":\"$ADMIN_PASS\"}" \
  http://localhost:8356/web/auth/login)
echo "$LOGIN_RESPONSE" | tee "$OUTPUT_DIR/01_login.json"

# Extract session token
SESSION_TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('session_token', ''))" 2>/dev/null)
echo "Session token: ${SESSION_TOKEN:0:20}..." | tee -a "$OUTPUT_DIR/summary.txt"

if [ -z "$SESSION_TOKEN" ]; then
    echo "ERROR: Failed to get session token!" | tee -a "$OUTPUT_DIR/summary.txt"
    exit 1
fi

# Test 2: Get queue/list
echo -e "\n[2] Testing /web/api/list..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s -H "Authorization: Bearer $SESSION_TOKEN" \
  http://localhost:8356/web/api/list?limit=5 2>&1 | tee "$OUTPUT_DIR/02_list.json"

# Test 3: Get analytics - tag frequencies
echo -e "\n[3] Testing /web/api/analytics/tag-frequencies..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s -H "Authorization: Bearer $SESSION_TOKEN" \
  http://localhost:8356/web/api/analytics/tag-frequencies?limit=20 2>&1 | tee "$OUTPUT_DIR/03_tag_frequencies.json"

# Test 4: Get analytics - mood distribution
echo -e "\n[4] Testing /web/api/analytics/mood-distribution..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s -H "Authorization: Bearer $SESSION_TOKEN" \
  http://localhost:8356/web/api/analytics/mood-distribution 2>&1 | tee "$OUTPUT_DIR/04_mood_distribution.json"

# Test 5: Get library stats (MISSING ENDPOINT)
echo -e "\n[5] Testing /web/api/library/stats (expected 404)..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s -H "Authorization: Bearer $SESSION_TOKEN" \
  http://localhost:8356/web/api/library/stats 2>&1 | tee "$OUTPUT_DIR/05_library_stats_MISSING.json"

# Test 6: Get library scan status
echo -e "\n[6] Testing /web/api/library/scan/status..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s -H "Authorization: Bearer $SESSION_TOKEN" \
  http://localhost:8356/web/api/library/scan/status 2>&1 | tee "$OUTPUT_DIR/06_library_scan_status.json"

# Test 7: Get info
echo -e "\n[7] Testing /web/api/info..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s -H "Authorization: Bearer $SESSION_TOKEN" \
  http://localhost:8356/web/api/info 2>&1 | tee "$OUTPUT_DIR/07_info.json"

# Test 8: Get health
echo -e "\n[8] Testing /web/api/health..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s -H "Authorization: Bearer $SESSION_TOKEN" \
  http://localhost:8356/web/api/health 2>&1 | tee "$OUTPUT_DIR/08_health.json"

# Test 9: List all available endpoints
echo -e "\n[9] Getting OpenAPI schema..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s http://localhost:8356/openapi.json 2>&1 | python3 -m json.tool | tee "$OUTPUT_DIR/09_openapi.json"

echo -e "\n=== Tests Complete ===" | tee -a "$OUTPUT_DIR/summary.txt"
echo "To copy to host: docker cp nomarr:$OUTPUT_DIR ./webui_tests" | tee -a "$OUTPUT_DIR/summary.txt"
