#!/usr/bin/env bash
set -euo pipefail

# Optional Git pre-commit gate. Run from the site repository.
# The Python implementation reads the Git index, including filenames with spaces,
# and shares schema semantics with the post-edit validator. No agent framework required.
HOOK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${SEO_PYTHON:-python3}" "$HOOK_DIR/pre_commit_seo_check.py"
