#!/bin/bash
# Quick diagnostic - check if API is running and get container startup logs

echo "=== Container Status ===" | tee test_results/container_status.txt
docker ps | grep nomarr | tee -a test_results/container_status.txt
echo "" | tee -a test_results/container_status.txt

echo "=== Last 100 lines of container logs ===" | tee test_results/container_logs.txt
docker logs --tail 100 nomarr 2>&1 | tee -a test_results/container_logs.txt
echo "" | tee -a test_results/container_logs.txt

echo "=== Check if API is responding ===" | tee -a test_results/container_status.txt
curl -s http://localhost:8356/api/v1/info | python3 -m json.tool 2>&1 | tee -a test_results/container_status.txt
echo "" | tee -a test_results/container_status.txt

echo "=== Database diagnostics ===" | tee test_results/db_diagnostics.txt
docker exec nomarr bash /app/scripts/diagnose_db.sh 2>&1 | tee -a test_results/db_diagnostics.txt

echo ""
echo "Results saved to test_results/"
echo "Run: tar -czf diagnostics.tar.gz test_results/"
