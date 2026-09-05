#!/usr/bin/env bash
# install_helsinki.sh — portable, secret-free host install for this repo.
#
# Rebuild-anywhere helper for an Ubuntu-like VPS or a later Helsinki rebuild.
# This script is NOT a live deployment and does NOT mean this git commit is
# running on the observed Helsinki host. See docs/DEPLOY.md and
# docs/OBSERVED_DEPLOYMENT.md.
#
# Hard rules (encoded here and in docs — do not weaken):
#   - No secrets in git. This script never prints, reads, or requires tokens.
#   - WebSocket never places orders.
#   - Finnhub ≠ option NBBO. Do not gate option limits on Finnhub ticks.
#   - ≥20% cash / max deploy 80%; overnight longs OK; 12:30 PT = new-entry cutoff only.
#   - Sandbox ≠ live fill evidence. Production NBBO is pricing truth.
#   - Default mode remains signals_only. The installer never enables live.
#   - Default = install files only. --enable and --start are explicit.
#   - Never silently overwrite live /opt/trading-desk scripts.
#   - Never replace live trading-desk-*.service unless the operator opts in.
#
# Usage (as root):
#   sudo ./scripts/install_helsinki.sh
#   sudo ./scripts/install_helsinki.sh --enable
#   sudo ./scripts/install_helsinki.sh --enable --start
#   sudo INSTALL_ROOT=/opt/groktrading ./scripts/install_helsinki.sh --dry-run
#
# Safe defaults:
#   INSTALL_ROOT=/opt/groktrading   (distinct from legacy /opt/trading-desk)
#   Package-named units only: groktrading-finnhub.service, groktrading-tape.service
#   No systemctl enable / start
#   Existing /etc/trading-desk/*.env files are never overwritten
#
set -euo pipefail

umask 022

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "${SCRIPT_PATH}")"
REPO_ROOT="$(readlink -f "${SCRIPT_DIR}/..")"

# Configurable paths. Prefer the package root — never default to the live
# Helsinki tree. /opt/trading-desk is legacy, hand-built, and not this checkout.
INSTALL_ROOT="${INSTALL_ROOT:-/opt/groktrading}"
ETC_DIR="${ETC_DIR:-/etc/trading-desk}"
STATE_DIR="${STATE_DIR:-/var/lib/trading-desk}"
SERVICE_USER="${SERVICE_USER:-tradingdesk}"
SERVICE_GROUP="${SERVICE_GROUP:-${SERVICE_USER}}"
PYTHON="${PYTHON:-python3}"

ENABLE=0
START=0
ADOPT_LEGACY_NAMES=0
FORCE_UNITS=0
ALLOW_LEGACY_ROOT=0
I_MEAN_CUTOVER=0
DRY_RUN=0

PACKAGE_FINNHUB_UNIT="groktrading-finnhub.service"
PACKAGE_TAPE_UNIT="groktrading-tape.service"
LEGACY_FINNHUB_UNIT="trading-desk-finnhub.service"
LEGACY_TAPE_UNIT="trading-desk-tape.service"

# Markers of the observed live Helsinki tree. Presence means "do not clobber".
LEGACY_MARKERS=(ws_tape.py tape_poller.py finnhub_adapter.py nightly_print_bt.py)

die() {
  printf 'install_helsinki: ERROR: %s\n' "$*" >&2
  exit 1
}

info() {
  printf 'install_helsinki: %s\n' "$*"
}

warn() {
  printf 'install_helsinki: WARNING: %s\n' "$*" >&2
}

usage() {
  cat <<'EOF'
install_helsinki.sh — secret-free GrokTrading host installer

Installs this repo's package, a venv, example systemd units, and directory
layout. Does not start live trading, place orders, copy real secrets, or
claim that Helsinki already runs this commit.

Usage:
  sudo ./scripts/install_helsinki.sh [options]

Options:
  --enable              systemctl enable the units this run manages
  --start               systemctl start those units (still signals_only)
  --adopt-legacy-names  install as trading-desk-*.service (Helsinki names)
                        Default is groktrading-*.service so live units are
                        not replaced. Enabling/starting pre-existing legacy
                        units also requires --i-mean-cutover.
  --force-units         overwrite existing unit/drop-in files at the dest
  --allow-legacy-root   allow INSTALL_ROOT=/opt/trading-desk (still never
                        deletes dest-only loose scripts such as ws_tape.py)
  --i-mean-cutover      required together with --adopt-legacy-names plus
                        --enable/--start when trading-desk-*.service already
                        exists. Cutover is an operator action, not a default.
  --dry-run             print the plan; create nothing; no root required
  -h, --help            show this help

Environment (safe defaults):
  INSTALL_ROOT=/opt/groktrading     package checkout + venv (not /opt/trading-desk)
  ETC_DIR=/etc/trading-desk         0700 dir for operator-placed 0600 env files
  STATE_DIR=/var/lib/trading-desk   tape JSON output (not /opt/trading-desk/*.json)
  SERVICE_USER=tradingdesk
  SERVICE_GROUP=tradingdesk
  PYTHON=python3                    requires Python >= 3.11

The package does not expose a CLI equivalent to legacy ws_tape.py /
tape_poller.py. groktrading-tape writes a signals-only skeleton only.
Migrating the live UW+Tradier tape is a separate operator step.

This installer never prints or requires API tokens.
EOF
}

run() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf 'dry-run: %s\n' "$*"
    return 0
  fi
  "$@"
}

require_root() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  if [[ "${EUID}" -ne 0 ]]; then
    die "root/sudo required (fail closed). Re-run with sudo, or pass --dry-run / --help."
  fi
}

legacy_root_requested() {
  local resolved
  resolved="$(readlink -f "${INSTALL_ROOT}" 2>/dev/null || printf '%s' "${INSTALL_ROOT}")"
  [[ "${resolved}" == "/opt/trading-desk" || "${INSTALL_ROOT}" == "/opt/trading-desk" ]]
}

has_legacy_markers() {
  local dest="$1"
  local name
  [[ -d "${dest}" ]] || return 1
  for name in "${LEGACY_MARKERS[@]}"; do
    if [[ -e "${dest}/${name}" ]]; then
      return 0
    fi
  done
  return 1
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --enable) ENABLE=1 ;;
      --start) START=1 ;;
      --adopt-legacy-names) ADOPT_LEGACY_NAMES=1 ;;
      --force-units) FORCE_UNITS=1 ;;
      --allow-legacy-root) ALLOW_LEGACY_ROOT=1 ;;
      --i-mean-cutover) I_MEAN_CUTOVER=1 ;;
      --dry-run) DRY_RUN=1 ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "unknown argument: $1 (try --help)"
        ;;
    esac
    shift
  done
}

check_python() {
  command -v "${PYTHON}" >/dev/null 2>&1 || die "PYTHON=${PYTHON} not found"
  local version
  version="$("${PYTHON}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  "${PYTHON}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "Python >= 3.11 required (found ${version})"
}

ensure_venv_module() {
  if "${PYTHON}" -c 'import venv' >/dev/null 2>&1; then
    return 0
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    info "dry-run: python venv module missing; would require python3-venv"
    return 0
  fi
  if command -v apt-get >/dev/null 2>&1; then
    info "installing python3-venv python3-pip (required for the host venv)"
    DEBIAN_FRONTEND=noninteractive run apt-get update -y
    DEBIAN_FRONTEND=noninteractive run apt-get install -y python3-venv python3-pip
  else
    die "Python venv module missing. Install python3-venv (Ubuntu) and re-run."
  fi
  "${PYTHON}" -c 'import venv' >/dev/null 2>&1 || die "python venv still missing after apt install"
}

finnhub_unit_name() {
  if [[ "${ADOPT_LEGACY_NAMES}" -eq 1 ]]; then
    printf '%s' "${LEGACY_FINNHUB_UNIT}"
  else
    printf '%s' "${PACKAGE_FINNHUB_UNIT}"
  fi
}

tape_unit_name() {
  if [[ "${ADOPT_LEGACY_NAMES}" -eq 1 ]]; then
    printf '%s' "${LEGACY_TAPE_UNIT}"
  else
    printf '%s' "${PACKAGE_TAPE_UNIT}"
  fi
}

unit_exists() {
  local name="$1"
  [[ -f "/etc/systemd/system/${name}" ]] || [[ -f "/lib/systemd/system/${name}" ]]
}

guard_paths() {
  if legacy_root_requested && [[ "${ALLOW_LEGACY_ROOT}" -ne 1 ]]; then
    die "INSTALL_ROOT=${INSTALL_ROOT} is the live Helsinki path. Refusing to write there without --allow-legacy-root. Default remains /opt/groktrading (parallel install)."
  fi
  if has_legacy_markers "${INSTALL_ROOT}" && [[ "${ALLOW_LEGACY_ROOT}" -ne 1 ]]; then
    die "INSTALL_ROOT=${INSTALL_ROOT} contains legacy loose scripts (${LEGACY_MARKERS[*]}). Refusing to write into that tree without --allow-legacy-root."
  fi
}

guard_cutover() {
  if [[ "${ADOPT_LEGACY_NAMES}" -ne 1 ]]; then
    return 0
  fi
  if [[ "${ENABLE}" -ne 1 && "${START}" -ne 1 ]]; then
    return 0
  fi
  if unit_exists "${LEGACY_FINNHUB_UNIT}" || unit_exists "${LEGACY_TAPE_UNIT}"; then
    if [[ "${I_MEAN_CUTOVER}" -ne 1 ]]; then
      die "--adopt-legacy-names with --enable/--start would act on existing ${LEGACY_TAPE_UNIT} / ${LEGACY_FINNHUB_UNIT}. Cutover requires --i-mean-cutover. For a parallel install, omit --adopt-legacy-names."
    fi
  fi
}

ensure_service_user() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    info "dry-run: would ensure system user ${SERVICE_USER}:${SERVICE_GROUP}"
    return 0
  fi
  if ! getent group "${SERVICE_GROUP}" >/dev/null; then
    groupadd --system "${SERVICE_GROUP}"
  fi
  if ! getent passwd "${SERVICE_USER}" >/dev/null; then
    local nologin
    nologin="$(command -v nologin || true)"
    nologin="${nologin:-/usr/sbin/nologin}"
    useradd --system --gid "${SERVICE_GROUP}" --home-dir "${STATE_DIR}" \
      --shell "${nologin}" --comment "GrokTrading service user" "${SERVICE_USER}"
    info "created system user ${SERVICE_USER}"
  fi
}

ensure_dirs() {
  run install -d -m 0755 "${INSTALL_ROOT}"
  run install -d -m 0755 "${STATE_DIR}"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    info "dry-run: would create ${ETC_DIR} mode 0700 (never overwrite *.env)"
    return 0
  fi
  if [[ ! -d "${ETC_DIR}" ]]; then
    install -d -m 0700 "${ETC_DIR}"
    info "created ${ETC_DIR} mode 0700"
  else
    chmod 0700 "${ETC_DIR}" || warn "could not chmod 0700 ${ETC_DIR} (left as-is)"
    info "reusing ${ETC_DIR} (existing *.env files will not be overwritten)"
  fi
  if [[ "${DRY_RUN}" -ne 1 ]]; then
    chown "${SERVICE_USER}:${SERVICE_GROUP}" "${STATE_DIR}"
    chmod 0750 "${STATE_DIR}"
  fi
}

sync_package_tree() {
  local src dest
  src="$(readlink -f "${REPO_ROOT}")"
  if [[ -d "${INSTALL_ROOT}" ]]; then
    dest="$(readlink -f "${INSTALL_ROOT}")"
  else
    dest="${INSTALL_ROOT}"
  fi
  if [[ "${src}" == "${dest}" ]]; then
    info "using in-place checkout ${INSTALL_ROOT}"
    return 0
  fi
  if [[ -e "${INSTALL_ROOT}" && ! -f "${INSTALL_ROOT}/pyproject.toml" && -n "$(ls -A "${INSTALL_ROOT}" 2>/dev/null || true)" ]]; then
    die "INSTALL_ROOT=${INSTALL_ROOT} exists and is not a groktrading tree (no pyproject.toml). Refusing to copy over it."
  fi
  info "copying package files ${REPO_ROOT} -> ${INSTALL_ROOT} (no --delete; dest-only files kept)"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    info "dry-run: rsync package tree without deleting dest-only files"
    return 0
  fi
  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude '.venv/' \
      --exclude '__pycache__/' \
      --exclude '.mypy_cache/' \
      --exclude '.pytest_cache/' \
      --exclude '.ruff_cache/' \
      --exclude '.git/' \
      "${REPO_ROOT}/" "${INSTALL_ROOT}/"
  else
    # No --delete equivalent: tar overwrite keeps dest-only files such as
    # legacy ws_tape.py when --allow-legacy-root is used.
    tar -C "${REPO_ROOT}" \
      --exclude='.venv' \
      --exclude='__pycache__' \
      --exclude='.mypy_cache' \
      --exclude='.pytest_cache' \
      --exclude='.ruff_cache' \
      --exclude='.git' \
      -cf - . | tar -C "${INSTALL_ROOT}" -xf -
  fi
}

ensure_venv_and_package() {
  local venv_py="${INSTALL_ROOT}/.venv/bin/python"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    info "dry-run: would create venv at ${INSTALL_ROOT}/.venv and pip install -e '.[ws]'"
    return 0
  fi
  [[ -f "${INSTALL_ROOT}/pyproject.toml" ]] || die "missing ${INSTALL_ROOT}/pyproject.toml"
  if [[ ! -x "${venv_py}" ]]; then
    info "creating venv ${INSTALL_ROOT}/.venv"
    "${PYTHON}" -m venv "${INSTALL_ROOT}/.venv"
  fi
  "${venv_py}" -m pip install --upgrade pip
  # Host install: runtime + optional websockets. Never [dev]. Never live extras.
  info "pip install -e '.[ws]' (signals_only package; no live enablement)"
  (
    cd "${INSTALL_ROOT}"
    "${venv_py}" -m pip install -e ".[ws]"
  )
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_ROOT}/.venv"
  # Checkout must stay readable by the service user; do not chown the git tree.
  chmod -R a+rX "${INSTALL_ROOT}/src" "${INSTALL_ROOT}/pyproject.toml" 2>/dev/null || true
}

rewrite_unit() {
  local src="$1"
  local install_root etc_dir state_dir user group
  install_root="$2"
  etc_dir="$3"
  state_dir="$4"
  user="$5"
  group="$6"
  # Example units are written for the safe defaults. Substitute configured paths.
  sed \
    -e "s|/opt/groktrading|${install_root}|g" \
    -e "s|/etc/trading-desk|${etc_dir}|g" \
    -e "s|/var/lib/trading-desk|${state_dir}|g" \
    -e "s|^User=tradingdesk$|User=${user}|" \
    -e "s|^Group=tradingdesk$|Group=${group}|" \
    "${src}"
}

install_unit_file() {
  local src_name="$1"
  local dest_name="$2"
  local dest="/etc/systemd/system/${dest_name}"
  local src="${REPO_ROOT}/deploy/examples/systemd/${src_name}"
  [[ -f "${src}" ]] || die "missing example unit ${src}"
  if [[ -e "${dest}" && "${FORCE_UNITS}" -ne 1 ]]; then
    info "leaving existing ${dest} in place (pass --force-units to replace)"
    return 0
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    info "dry-run: would install ${src_name} -> ${dest}"
    return 0
  fi
  local tmp
  tmp="$(mktemp)"
  rewrite_unit "${src}" "${INSTALL_ROOT}" "${ETC_DIR}" "${STATE_DIR}" \
    "${SERVICE_USER}" "${SERVICE_GROUP}" >"${tmp}"
  install -o root -g root -m 0644 "${tmp}" "${dest}"
  rm -f "${tmp}"
  info "installed ${dest}"
}

install_webhook_dropin() {
  local tape_unit dest_dir dest src
  tape_unit="$(tape_unit_name)"
  dest_dir="/etc/systemd/system/${tape_unit}.d"
  dest="${dest_dir}/webhook.conf"
  src="${REPO_ROOT}/deploy/examples/systemd/webhook.env.conf"
  [[ -f "${src}" ]] || die "missing ${src}"
  if [[ -e "${dest}" && "${FORCE_UNITS}" -ne 1 ]]; then
    info "leaving existing ${dest} in place (pass --force-units to replace)"
    return 0
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    info "dry-run: would install webhook drop-in ${dest}"
    return 0
  fi
  install -d -m 0755 "${dest_dir}"
  local tmp
  tmp="$(mktemp)"
  rewrite_unit "${src}" "${INSTALL_ROOT}" "${ETC_DIR}" "${STATE_DIR}" \
    "${SERVICE_USER}" "${SERVICE_GROUP}" >"${tmp}"
  install -o root -g root -m 0644 "${tmp}" "${dest}"
  rm -f "${tmp}"
  info "installed ${dest}"
}

maybe_daemon_reload() {
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl not found; skipped daemon-reload / enable / start"
    if [[ "${ENABLE}" -eq 1 || "${START}" -eq 1 ]]; then
      die "--enable/--start require systemctl"
    fi
    return 0
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    info "dry-run: would systemctl daemon-reload"
    return 0
  fi
  systemctl daemon-reload
  info "systemctl daemon-reload"
}

maybe_enable_start() {
  local units=()
  units+=("$(finnhub_unit_name)")
  units+=("$(tape_unit_name)")
  if [[ "${ENABLE}" -eq 1 ]]; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      info "dry-run: would systemctl enable ${units[*]}"
    else
      systemctl enable "${units[@]}"
      info "enabled ${units[*]} (not started unless --start)"
    fi
  else
    info "units not enabled (pass --enable)"
  fi
  if [[ "${START}" -eq 1 ]]; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      info "dry-run: would systemctl start ${units[*]}"
    else
      systemctl start "${units[@]}"
      info "started ${units[*]} (signals_only skeleton writers; no orders)"
    fi
  else
    info "units not started (pass --start)"
  fi
}

print_plan() {
  cat <<EOF
Plan
  repo:           ${REPO_ROOT}
  INSTALL_ROOT:   ${INSTALL_ROOT}
  ETC_DIR:        ${ETC_DIR} (0700; existing *.env never overwritten)
  STATE_DIR:      ${STATE_DIR}
  service user:   ${SERVICE_USER}:${SERVICE_GROUP}
  finnhub unit:   $(finnhub_unit_name)
  tape unit:      $(tape_unit_name)
  enable:         $([[ "${ENABLE}" -eq 1 ]] && echo yes || echo no)
  start:          $([[ "${START}" -eq 1 ]] && echo yes || echo no)
  adopt-legacy:   $([[ "${ADOPT_LEGACY_NAMES}" -eq 1 ]] && echo yes || echo no)
  force-units:    $([[ "${FORCE_UNITS}" -eq 1 ]] && echo yes || echo no)
  allow-legacy-root: $([[ "${ALLOW_LEGACY_ROOT}" -eq 1 ]] && echo yes || echo no)
  i-mean-cutover: $([[ "${I_MEAN_CUTOVER}" -eq 1 ]] && echo yes || echo no)
  dry-run:        $([[ "${DRY_RUN}" -eq 1 ]] && echo yes || echo no)
  live trading:   never enabled by this installer
  secrets:        never printed or required
EOF
}

print_next_steps() {
  local examples="${REPO_ROOT}/deploy/examples/env"
  cat <<EOF

Next steps (operator — placeholders only; never paste real tokens into git or chat)

  1. Copy env examples to ${ETC_DIR} only if the dest file does not already exist:
       test -f ${ETC_DIR}/finnhub.env || install -o root -g root -m 0600 ${examples}/finnhub.env.example ${ETC_DIR}/finnhub.env
       test -f ${ETC_DIR}/grok-webhook.env || install -o root -g root -m 0600 ${examples}/grok-webhook.env.example ${ETC_DIR}/grok-webhook.env
       test -f ${ETC_DIR}/unusual-whales.env || install -o root -g root -m 0600 ${examples}/unusual-whales.env.example ${ETC_DIR}/unusual-whales.env
       test -f ${ETC_DIR}/tradier-sandbox.env || install -o root -g root -m 0600 ${examples}/tradier-sandbox.env.example ${ETC_DIR}/tradier-sandbox.env
       test -f ${ETC_DIR}/tradier-live.env || install -o root -g root -m 0600 ${examples}/tradier-live.env.example ${ETC_DIR}/tradier-live.env
       test -f ${ETC_DIR}/groktrading.env || install -o root -g root -m 0600 ${examples}/groktrading.env.example ${ETC_DIR}/groktrading.env

  2. Edit those files in place. Replace YOUR_* placeholders. chmod 0600. Do not
     chmod 0644. Do not commit the filled files.

  3. Review units (package names unless you passed --adopt-legacy-names):
       systemctl cat $(finnhub_unit_name)
       systemctl cat $(tape_unit_name)

  4. Enable without starting:
       sudo ${SCRIPT_PATH} --enable

  5. Start only when you intend the processes to run (still signals_only):
       sudo ${SCRIPT_PATH} --start

  6. Live Helsinki cutover (stop legacy units / swap names) is a separate
     checklist in docs/DEPLOY.md. This installer does not stop
     trading-desk-*.service and does not set GROKTRADING_LIVE_EXPLICITLY_ENABLED.

Hard rules still in force
  - No secrets in git
  - WebSocket never places orders
  - Finnhub ≠ option NBBO
  - ≥20% cash / max deploy 80%; overnight longs OK; 12:30 PT = new-entry cutoff only
  - Sandbox ≠ live fill evidence
  - Default mode remains signals_only / no live enablement by installer

Merging or installing this repo is not a claim that Helsinki runs this commit.
EOF
}

preserve_env_notice() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  if [[ ! -d "${ETC_DIR}" ]]; then
    return 0
  fi
  local found=0
  local f
  for f in "${ETC_DIR}"/*.env; do
    [[ -e "${f}" ]] || continue
    found=1
    info "preserved existing env file ${f} (not overwritten, contents not printed)"
  done
  if [[ "${found}" -eq 0 ]]; then
    info "no existing ${ETC_DIR}/*.env files (operator must copy examples; see next steps)"
  fi
}

main() {
  parse_args "$@"
  require_root
  [[ -f "${REPO_ROOT}/pyproject.toml" ]] || die "repo root ${REPO_ROOT} has no pyproject.toml"
  [[ -d "${REPO_ROOT}/deploy/examples/systemd" ]] || die "missing deploy/examples/systemd"
  guard_paths
  guard_cutover
  print_plan
  check_python
  ensure_venv_module
  ensure_service_user
  ensure_dirs
  sync_package_tree
  ensure_venv_and_package
  install_unit_file "groktrading-finnhub.service" "$(finnhub_unit_name)"
  install_unit_file "groktrading-tape.service" "$(tape_unit_name)"
  install_webhook_dropin
  maybe_daemon_reload
  maybe_enable_start
  preserve_env_notice
  print_next_steps
}

main "$@"
