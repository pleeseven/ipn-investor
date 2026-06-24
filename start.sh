#!/bin/bash
cd "$(dirname "$0")"
exec python3 -m uvicorn app.main:app --port "${PORT:-8000}"
