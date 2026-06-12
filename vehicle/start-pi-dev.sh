#!/usr/bin/env bash
set -euo pipefail

PI_HOST="192.168.0.123"
PI_USER="pi"
REMOTE_DIR="/home/pi/rc"
LOCAL_DIR="./pifs"
SYNC_TO="./src"

mkdir -p "$LOCAL_DIR" "$SYNC_TO"

if mountpoint -q "$LOCAL_DIR"; then
  echo "$LOCAL_DIR already mounted"
else
  sshfs \
    -o reconnect,ServerAliveInterval=15,ServerAliveCountMax=3 \
    "$PI_USER@$PI_HOST:$REMOTE_DIR" \
    "$LOCAL_DIR"
fi

echo "Opening VS Code..."
code "$LOCAL_DIR" >/dev/null 2>&1 &

echo "Starting rsync every 1 minute from sshfs to $SYNC_TO"

while true; do
  rsync -avz --delete \
    --exclude=".git/" \
    --exclude="venv/" \
    "$LOCAL_DIR/" "$SYNC_TO/"

  sleep 60
done
