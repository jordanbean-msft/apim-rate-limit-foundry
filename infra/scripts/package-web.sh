#!/bin/sh
set -eu
node -e 'if (Number(process.versions.node.split(".")[0]) !== 24) { console.error("Portal packaging requires Node 24 LTS."); process.exit(1); }'
# Service hooks run in web/. Stage only the static bundle and built-in Node server.
npm ci
npm run build
test -f server/index.mjs
test -f dist/index.html
rm -rf ../infra/.artifacts/web
mkdir -p ../infra/.artifacts/web
cp -R dist server package.json ../infra/.artifacts/web/
