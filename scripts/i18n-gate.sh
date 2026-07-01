#!/usr/bin/env bash
# i18n N/A declaration gate (INTERNATIONALIZATION-STANDARD §1).
# This repo is a declared i18n N/A candidate (single-user discovery/research
# tool; Streamlit output is operator-only — out-of-scope condition a). The
# standard requires the N/A decision be committed, never a silent skip: enforce
# that docs/I18N.md exists, declares `i18n status: N/A`, and gives a non-empty
# Reason. Merge-blocking, same as the standard's N/A-declaration AUTO-GATE.
set -euo pipefail

doc="docs/I18N.md"

if [ ! -f "$doc" ]; then
  echo "i18n-gate: $doc is missing — an i18n N/A repo MUST ship it (STANDARD §1)" >&2
  exit 1
fi

if ! grep -qE '^# i18n status: N/A[[:space:]]*$' "$doc"; then
  echo "i18n-gate: $doc lacks the '# i18n status: N/A' declaration (STANDARD §1)" >&2
  exit 1
fi

# Reason: must be present with non-whitespace content after the colon.
if ! grep -qE '^Reason:[[:space:]]*[^[:space:]].*$' "$doc"; then
  echo "i18n-gate: $doc has no non-empty 'Reason:' line (STANDARD §1)" >&2
  exit 1
fi

echo "i18n-gate: docs/I18N.md declares i18n status N/A with a reason — ok"
