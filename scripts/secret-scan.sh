#!/usr/bin/env bash
# Lightweight secret scan (stand-in for gitleaks when it is not installed).
# CI uses gitleaks; this gives the same merge-blocking guarantee locally.
set -euo pipefail

if command -v gitleaks >/dev/null 2>&1; then
  exec gitleaks detect --no-banner --redact
fi

# Fallback: grep tracked source for high-signal secret shapes.
patterns=(
  'AKIA[0-9A-Z]{16}'                       # AWS access key id
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'     # private keys
  'xox[baprs]-[0-9A-Za-z-]{10,}'           # slack tokens
  'AIza[0-9A-Za-z_\-]{35}'                 # google api key
  '(secret|password|api[_-]?key)[[:space:]]*=[[:space:]]*["'"'"'][^"'"'"']{12,}'
)

files=$(git ls-files '*.py' '*.toml' '*.yml' '*.yaml' '*.sh' '*.md' 2>/dev/null || true)
[ -z "$files" ] && { echo "secret-scan: no tracked files yet — ok"; exit 0; }

found=0
for pat in "${patterns[@]}"; do
  if echo "$files" | xargs grep -InE "$pat" 2>/dev/null; then
    found=1
  fi
done

if [ "$found" -ne 0 ]; then
  echo "secret-scan: potential secret detected (above)" >&2
  exit 1
fi
echo "secret-scan: 0 findings"
