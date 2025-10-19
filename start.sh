#!/bin/bash
# Quick start script for the Recap Template Backend

set -e

# Start the server
echo "✅ Starting server on http://localhost:8000"
echo "📖 API Documentation: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
