#!/usr/bin/env bash
# Local Renovate dry-run via official Docker image (same idea as CI bot, no GitHub token).
# Use after changing renovate.json (especially customManagers / regex file patterns).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${RENOVATE_IMAGE:-renovate/renovate:latest}"
LOG="${RENOVATE_LOG:-$(mktemp -t renovate-local.XXXXXX.log)}"

echo "Repo: $ROOT"
echo "Log:  $LOG"
echo "Pull/run image: $IMAGE"

docker pull "$IMAGE" >/dev/null

docker run --rm \
  -v "$ROOT:/tmp/repo" \
  -w /tmp/repo \
  -e LOG_LEVEL="${RENOVATE_LOG_LEVEL:-debug}" \
  -e RENOVATE_DRY_RUN=lookup \
  "$IMAGE" \
  renovate --platform=local 2>&1 | tee "$LOG"

echo ""
echo "=== Quick checks (shared presets + toolkit ownership) ==="
if grep -F 'github>quokkify/project-toolkit//renovate/default' "$ROOT/renovate.json" >/dev/null; then
  echo "OK: project-toolkit Renovate preset is enabled"
else
  echo "FAIL: project-toolkit Renovate preset is missing from renovate.json"
  exit 1
fi

if grep -R -E 'quokkify/project-toolkit/[^@]+@[0-9a-f]{40} # v[0-9]+\.[0-9]+\.[0-9]+' "$ROOT/.github/workflows" >/dev/null; then
  echo "OK: toolkit workflow/action references are immutable SHAs with release comments"
else
  echo "FAIL: no immutable project-toolkit workflow/action reference found"
  exit 1
fi

echo ""
echo "Full log: $LOG"
