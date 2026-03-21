#!/usr/bin/env bash
set -euo pipefail

# Downloads yolov8n.pt into python-cv-service/ if missing.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_PATH="$ROOT_DIR/python-cv-service/yolov8n.pt"

if [[ -f "$MODEL_PATH" ]]; then
  echo "Model already present: $MODEL_PATH"
  exit 0
fi

echo "Downloading YOLO model to $MODEL_PATH ..."
(
  cd "$ROOT_DIR/python-cv-service"
  python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
)

echo "Model download complete."
