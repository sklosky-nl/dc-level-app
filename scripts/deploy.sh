#!/bin/bash

# Deploy DC Level App to Production Server
# This script copies the frontend and gauge poller to xibo.space.nova-labs.org
# and makes sure the poller runs once a minute from cron.

set -e

SERVER="sklosky@xibo.space.nova-labs.org"
REMOTE_DIR="/opt/dc-level-app"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CRON_LINE='* * * * * /usr/bin/python3 /opt/dc-level-app/poller/dc_level_poller.py 2>&1 | /usr/bin/logger -t dc-level-poller'

echo "========================================"
echo "🚀 Deploying DC Level App to Production"
echo "========================================"
echo ""
echo "Server: $SERVER"
echo "Target: $REMOTE_DIR"
echo ""

if ! ssh "$SERVER" "test -w $REMOTE_DIR"; then
    echo "❌ $REMOTE_DIR is missing or not writable."
    echo "   Run the one-time setup first (see README.md)."
    exit 1
fi

echo "📦 Copying frontend files..."
echo ""
# data/ holds the live level.json written by the poller - never overwrite it
rsync -av --exclude '.DS_Store' --exclude 'data/' "$LOCAL_DIR/frontend/" "$SERVER:$REMOTE_DIR/frontend/"

echo ""
echo "📦 Copying gauge poller..."
echo ""
rsync -av --exclude '.DS_Store' --exclude '__pycache__/' "$LOCAL_DIR/poller/" "$SERVER:$REMOTE_DIR/poller/"

echo ""
echo "⏱  Installing cron job (gauge read every minute)..."
# Only the poller line is replaced, so the WATTO_TOKEN line above it survives
ssh "$SERVER" "(crontab -l 2>/dev/null | grep -v dc_level_poller.py; echo '$CRON_LINE') | crontab -"

echo ""
echo "📟 Reading gauge now (Watto post is skipped here; only cron has the token)..."
ssh "$SERVER" "/usr/bin/python3 $REMOTE_DIR/poller/dc_level_poller.py; cat $REMOTE_DIR/frontend/data/level.json"

echo ""
echo "========================================"
echo "✅ Deployment Complete!"
echo "========================================"
echo ""
echo "🌐 URL: http://xibo.space.nova-labs.org/dc-level/"
echo ""
echo "Note: Bump the ?v= cache-busting query in index.html when CSS/JS changes,"
echo "      or hard refresh (Cmd+Shift+R) in your browser."
echo "      Poller errors go to syslog: sudo journalctl -t dc-level-poller"
echo ""
