#!/bin/bash
# Direct database query script to get API keys and admin password
# Run this AFTER the API has started to get the actual keys

DB_PATH="/app/config/db/essentia.sqlite"

echo "=== Nomarr Database Diagnostics ==="
echo ""

if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: Database not found at $DB_PATH"
    exit 1
fi

echo "Database file: $DB_PATH"
echo "Size: $(ls -lh $DB_PATH | awk '{print $5}')"
echo ""

echo "--- Tables ---"
sqlite3 "$DB_PATH" ".tables"
echo ""

echo "--- Meta Keys ---"
sqlite3 "$DB_PATH" "SELECT key, CASE WHEN key LIKE '%password%' THEN '<redacted>' WHEN key LIKE '%key' THEN substr(value, 1, 20) || '...' ELSE value END as value FROM meta;" 2>&1
echo ""

echo "--- Full Meta (for diagnostics) ---"
sqlite3 "$DB_PATH" "SELECT * FROM meta;" 2>&1
echo ""

echo "--- Queue Stats ---"
sqlite3 "$DB_PATH" "SELECT status, COUNT(*) as count FROM queue GROUP BY status;" 2>&1
echo ""

echo "--- Library Stats ---"
sqlite3 "$DB_PATH" "SELECT COUNT(*) as total_files FROM library_files;" 2>&1
echo ""

# Extract actual keys
echo "--- Extracted Keys (for testing) ---"
API_KEY=$(sqlite3 "$DB_PATH" "SELECT value FROM meta WHERE key='api_key';" 2>&1)
INTERNAL_KEY=$(sqlite3 "$DB_PATH" "SELECT value FROM meta WHERE key='internal_key';" 2>&1)
ADMIN_HASH=$(sqlite3 "$DB_PATH" "SELECT value FROM meta WHERE key='admin_password_hash';" 2>&1)

if [ -n "$API_KEY" ]; then
    echo "API_KEY=${API_KEY:0:20}... (length: ${#API_KEY})"
else
    echo "API_KEY=<NOT SET>"
fi

if [ -n "$INTERNAL_KEY" ]; then
    echo "INTERNAL_KEY=${INTERNAL_KEY:0:20}... (length: ${#INTERNAL_KEY})"
else
    echo "INTERNAL_KEY=<NOT SET>"
fi

if [ -n "$ADMIN_HASH" ]; then
    echo "ADMIN_PASSWORD_HASH=<SET> (length: ${#ADMIN_HASH})"
else
    echo "ADMIN_PASSWORD_HASH=<NOT SET>"
fi

echo ""
echo "=== Container Process Info ==="
ps aux | grep -E 'python|uvicorn' | grep -v grep
