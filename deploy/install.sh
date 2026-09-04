#!/usr/bin/env bash
# Thin wrapper. Canonical installer: scripts/install_helsinki.sh
set -euo pipefail
exec "$(readlink -f "$(dirname "${BASH_SOURCE[0]}")/../scripts/install_helsinki.sh")" "$@"
