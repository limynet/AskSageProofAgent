#!/usr/bin/env sh
# get_bonsai_model.sh - downloads the Bonsai-1.7B Q1_0 GGUF into models/.
# Usage:  scripts/get_bonsai_model.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/models"
TARGET="$DIR/Bonsai-1.7B-Q1_0.gguf"
EXPECTED=248302272
mkdir -p "$DIR"
if [ -f "$TARGET" ] && [ "$(wc -c < "$TARGET")" = "$EXPECTED" ]; then
    echo "Model already present and verified: $TARGET"
    exit 0
fi
URL="https://huggingface.co/prism-ml/Bonsai-1.7B-gguf/resolve/main/Bonsai-1.7B-Q1_0.gguf"
echo "Downloading Bonsai-1.7B Q1_0 (~237 MB)..."
curl -L -o "$TARGET" "$URL"
SIZE=$(wc -c < "$TARGET")
if [ "$SIZE" != "$EXPECTED" ]; then
    echo "Size mismatch: got $SIZE, expected $EXPECTED. Re-run the script." >&2
    exit 2
fi
echo "OK: $TARGET ($SIZE bytes)"