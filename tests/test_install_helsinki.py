from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_helsinki.sh"
WRAPPER = ROOT / "deploy" / "install.sh"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def test_install_script_bash_syntax() -> None:
    proc = _run(["bash", "-n", str(SCRIPT)])
    assert proc.returncode == 0, proc.stderr


def test_wrapper_bash_syntax() -> None:
    proc = _run(["bash", "-n", str(WRAPPER)])
    assert proc.returncode == 0, proc.stderr


def test_help_lists_safe_defaults() -> None:
    proc = _run(["bash", str(SCRIPT), "--help"])
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "--enable" in out
    assert "--start" in out
    assert "--adopt-legacy-names" in out
    assert "--i-mean-cutover" in out
    assert "/opt/groktrading" in out
    assert "signals_only" in out
    assert "never prints or requires api tokens" in out.lower()


def test_dry_run_no_root_and_no_start_by_default() -> None:
    proc = _run(["bash", str(SCRIPT), "--dry-run"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    combined = proc.stdout + proc.stderr
    assert "INSTALL_ROOT:" in combined
    assert "/opt/groktrading" in combined
    assert "enable:         no" in combined
    assert "start:          no" in combined
    assert "live trading:   never enabled by this installer" in combined
    assert "AKIA" not in combined
    assert "token=" not in combined.lower()


def test_refuses_legacy_root_without_flag() -> None:
    env = os.environ.copy()
    env["INSTALL_ROOT"] = "/opt/trading-desk"
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    assert proc.returncode != 0
    assert "--allow-legacy-root" in (proc.stdout + proc.stderr)


def test_non_root_without_dry_run_fails_closed() -> None:
    if os.geteuid() == 0:
        return
    proc = _run(["bash", str(SCRIPT)])
    assert proc.returncode != 0
    assert "root/sudo required" in (proc.stdout + proc.stderr)


def test_script_encodes_hard_rules() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for needle in (
        "No secrets in git",
        "WebSocket never places orders",
        "Finnhub ≠ option NBBO",
        "≥20% cash",
        "12:30 PT = new-entry cutoff only",
        "Sandbox ≠ live fill evidence",
        "signals_only",
        "adopt-legacy-names",
        "i-mean-cutover",
        "allow-legacy-root",
        "/opt/groktrading",
        "/opt/trading-desk",
        "ws_tape.py",
        "SIT_MATCH_MAX_AGE_SEC",
        "groktrading.sit_match",
        "sensor farm",
        "FLOW_LEDGER_PATH",
        "account-events",
        "box_cold_rotate",
        "Grok Update Computer",
        "STATE_DIR/ledger",
        "flow-alerts",
        "tide_state",
        "UW_WS_URL",
        "Merge ≠ Helsinki",
        "companion units",
    ):
        assert needle in text, needle


def test_trading_desk_env_example_matches_observed_key_names() -> None:
    path = ROOT / "deploy" / "examples" / "env" / "trading-desk.env.example"
    text = path.read_text(encoding="utf-8")
    for key in (
        "TRADIER_ACCOUNT_ID",
        "TRADIER_ACCESS_TOKEN",
        "TRADIER_API_BASE",
        "UW_API_KEY",
        "TAPE_OUT",
        "FLOW_SEC",
    ):
        assert f"{key}=YOUR_" in text, key
    assert "SIT_MATCH_MAX_AGE_SEC" in text
    assert "60" in text
    assert "FLOW_LEDGER_PATH" in text
    assert "FLOW_LEDGER_KEEP_HOT_DAYS" in text
    assert "BOX_ROTATE_KEEP_HOT_DAYS" in text
    assert "BOX_ARCHIVE_PARENT" in text
    assert "ACCOUNT_EVENTS_ENABLED" in text
    assert "FLOW_ALERTS_POLL_SEC" in text
    assert "TIDE_POLL_SEC" in text
    assert "UW_WS_URL" in text
    assert "sensor farm" in text.lower()
    assert "AKIA" not in text
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            _, _, value = line.partition("=")
            assert value.startswith("YOUR_"), line


def test_rebuild_new_provider_runbook_covers_operator_path() -> None:
    text = (ROOT / "docs" / "REBUILD_NEW_PROVIDER.md").read_text(encoding="utf-8")
    for needle in (
        "Secret copy matrix",
        "/opt/trading-desk/.env",
        "/etc/trading-desk/finnhub.env",
        "/etc/trading-desk/grok-webhook.env",
        "GROK_WEBHOOK_KEY",
        "GROK_WEBHOOK_AUTH_HEADER",
        "cut -d= -f1",
        "CRON_TZ=America/Los_Angeles",
        "tape_poller.py",
        "nightly_print_bt.py",
        "poly / edgar / spx / Aria",
        "ws_tape.py",
        "signals_only",
        "Finnhub ≠ option NBBO",
        "WebSocket never places orders",
        "not a deployment",
        "SIT_MATCH_MAX_AGE_SEC",
        "trading-desk-tape",
        "sensor farm",
        "Grok Update Computer",
    ):
        assert needle in text, needle


def test_example_units_are_package_named_and_secret_free() -> None:
    systemd = ROOT / "deploy" / "examples" / "systemd"
    finnhub = (systemd / "groktrading-finnhub.service").read_text(encoding="utf-8")
    tape = (systemd / "groktrading-tape.service").read_text(encoding="utf-8")
    account = (systemd / "groktrading-account-events.service").read_text(encoding="utf-8")
    assert "groktrading-finnhub-tape" in finnhub
    assert "groktrading-tape" in tape
    assert "package_tape_skeleton.json" in tape
    assert "NOT trading-desk-tape.service" in tape
    assert "ws_tape.py" in tape
    assert "groktrading-account-events" in account
    assert "never places orders" in account.lower()
    assert "position truth" in account.lower()
    for text in (finnhub, tape, account):
        assert "YOUR_" not in text
        assert "token=" not in text.lower()
        assert "GROKTRADING_LIVE_EXPLICITLY_ENABLED=true" not in text
