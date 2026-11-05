#!/bin/sh
set -eu
# azd packages the root Function host, not the source package directory.
uv export --frozen --no-dev --no-editable --no-hashes --format requirements-txt --output-file requirements.txt
test -f function_app.py
test -f host.json
echo "Root Function host and exported runtime dependencies are ready."
