#!/bin/bash
# Container Integration Test Script
# Run this inside the container to test all functionality and save results to files

OUTPUT_DIR="/app/test_results"
mkdir -p "$OUTPUT_DIR"

echo "=== Nomarr Container Integration Test ===" | tee "$OUTPUT_DIR/summary.txt"
echo "Test started: $(date)" | tee -a "$OUTPUT_DIR/summary.txt"
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 1: Check API is running
echo "[1/10] Testing API health..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s http://localhost:8356/web/api/health 2>&1 | tee "$OUTPUT_DIR/01_api_health.json"
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 2: Get API info (no auth needed)
echo "[2/10] Getting API info..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s http://localhost:8356/api/v1/info 2>&1 | tee "$OUTPUT_DIR/02_api_info.json"
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 3: Show API key
echo "[3/10] Retrieving API key..." | tee -a "$OUTPUT_DIR/summary.txt"
python3 -m nomarr.manage_key --show 2>&1 | tee "$OUTPUT_DIR/03_api_key.txt"
API_KEY=$(python3 -m nomarr.manage_key --show 2>/dev/null | grep -v "Current API key:" | tr -d ' \n')
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 4: Show admin password
echo "[4/10] Retrieving admin password..." | tee -a "$OUTPUT_DIR/summary.txt"
python3 -m nomarr.manage_password --show 2>&1 | tee "$OUTPUT_DIR/04_admin_password.txt"
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 5: Test authenticated endpoint
echo "[5/10] Testing authenticated /api/v1/list endpoint..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8356/api/v1/list?limit=5 2>&1 | tee "$OUTPUT_DIR/05_list_jobs.json"
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 6: Check model cache
echo "[6/10] Checking model cache status..." | tee -a "$OUTPUT_DIR/summary.txt"
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8356/admin/cache/status 2>&1 | tee "$OUTPUT_DIR/06_cache_status.json"
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 7: List available models
echo "[7/10] Listing model files..." | tee -a "$OUTPUT_DIR/summary.txt"
ls -lR /app/models/ 2>&1 | tee "$OUTPUT_DIR/07_models_list.txt"
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 8: Check config
echo "[8/10] Checking config..." | tee -a "$OUTPUT_DIR/summary.txt"
cat /app/config/config.yaml 2>&1 | tee "$OUTPUT_DIR/08_config.yaml"
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 9: Check database
echo "[9/10] Checking database..." | tee -a "$OUTPUT_DIR/summary.txt"
if [ -f /app/config/db/essentia.sqlite ]; then
    ls -lh /app/config/db/essentia.sqlite | tee -a "$OUTPUT_DIR/09_database_info.txt"
    echo "Database tables:" | tee -a "$OUTPUT_DIR/09_database_info.txt"
    sqlite3 /app/config/db/essentia.sqlite ".tables" 2>&1 | tee -a "$OUTPUT_DIR/09_database_info.txt"
    echo "Job count (queue table):" | tee -a "$OUTPUT_DIR/09_database_info.txt"
    sqlite3 /app/config/db/essentia.sqlite "SELECT COUNT(*) FROM queue;" 2>&1 | tee -a "$OUTPUT_DIR/09_database_info.txt"
    echo "Meta keys:" | tee -a "$OUTPUT_DIR/09_database_info.txt"
    sqlite3 /app/config/db/essentia.sqlite "SELECT key FROM meta;" 2>&1 | tee -a "$OUTPUT_DIR/09_database_info.txt"
else
    echo "Database file not found!" | tee -a "$OUTPUT_DIR/09_database_info.txt"
fi
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Test 10: Test web UI files
echo "[10/10] Checking web UI files..." | tee -a "$OUTPUT_DIR/summary.txt"
ls -lh /app/nomarr/interfaces/web/*.{html,js,css} 2>&1 | tee "$OUTPUT_DIR/10_webui_files.txt"
echo "" | tee -a "$OUTPUT_DIR/summary.txt"

# Summary
echo "=== Test Complete ===" | tee -a "$OUTPUT_DIR/summary.txt"
echo "Test finished: $(date)" | tee -a "$OUTPUT_DIR/summary.txt"
echo "" | tee -a "$OUTPUT_DIR/summary.txt"
echo "Output files saved to: $OUTPUT_DIR" | tee -a "$OUTPUT_DIR/summary.txt"
echo "To copy to host, run: docker cp nomarr:$OUTPUT_DIR ./container_tests" | tee -a "$OUTPUT_DIR/summary.txt"
