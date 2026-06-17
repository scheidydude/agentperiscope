#!/usr/bin/env sh
set -e
cd "$(dirname "$0")/../frontend"
npm install
npm run build
echo "Frontend built → src/agentperiscope/web/"
