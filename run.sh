#!/bin/bash
cd "$(dirname "$0")"
pip install -r requirements.txt -q
uvicorn app.main:app --reload --port 8000
