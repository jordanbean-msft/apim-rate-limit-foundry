#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"
mkdir -p stream/wheels
rm -f stream/wheels/apim_rate_limit_foundry-*.whl
uv build --wheel --out-dir stream/wheels
uv export --quiet --no-emit-project --frozen --no-dev --no-editable --no-hashes \
  --format requirements-txt --output-file stream/requirements.txt
for wheel in stream/wheels/*.whl; do
  printf './wheels/%s\n' "$(basename "$wheel")" >> stream/requirements.txt
done
test -f stream/host.json
echo "Stream host wheel and runtime dependencies are ready."
