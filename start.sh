#!/bin/bash
set -e

ollama serve &

until curl -s http://localhost:11434 > /dev/null; do
  echo "Waiting for Ollama..."
  sleep 1
done

echo "Ollama is up. Starting FastAPI..."
exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}