#!/bin/sh
set -eu
# Service hooks run in web/. Stage only the static bundle and built-in Node server.
npm ci
npm run build
test -f server/index.mjs
test -f dist/index.html
rm -rf ../infra/.artifacts/web
mkdir -p ../infra/.artifacts/web
cp -R dist server package.json ../infra/.artifacts/web/
