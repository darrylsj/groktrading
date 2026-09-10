from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from groktrading.box_rotate import (
    BoxRotateError,
    assert_can_delete,
    deny_reason,
    is_denied,
    keep_hot_days,
    pack_date_from_path,
    plan_rotate,
)
from groktrading.timeutil import UTC

NOW = datetime(2026, 9, 9, 20, 0, tzinfo=UTC)  # 13:00 PT — session 2026-09-09


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("pack\n", encoding="utf-8")
    return path


def test_deny_list_blocks_env_tokens_credentials(tmp_path: Path) -> None:
    secret_env = _touch(tmp_path / ".env")
    token = _touch(tmp_path / "tradier.token")
    creds = _touch(tmp_path / "secrets" / "box-credential.json")
    pem = _touch(tmp_path / "host.pem")
    webhook = _touch(tmp_path / "grok-webhook.env")
    ok = _touch(tmp_path / "2026-09-01" / "flow.sqlite")
    assert is_denied(secret_env)
    assert deny_reason(secret_env) in {"deny_env_file", "deny_exact_name"}
    assert is_denied(token)
    assert is_denied(creds)
    assert is_denied(pem)
    assert is_denied(webhook)
    assert not is_denied(ok)
    assert deny_reason(ok) is None


def test_keep_hot_window_fail_closed() -> None:
    assert keep_hot_days(None) == 7
    assert keep_hot_days("14") == 14
    with pytest.raises(BoxRotateError):
        keep_hot_days("6")
    with pytest.raises(BoxRotateError):
        keep_hot_days("15")
    with pytest.raises(BoxRotateError):
        keep_hot_days("nope")


def test_plan_skips_open_day_and_hot_window(tmp_path: Path) -> None:
    _touch(tmp_path / "flow-2026-08-20.sqlite")
    recent = _touch(tmp_path / "flow-2026-09-08.sqlite")  # yesterday; still in 7-day hot
    today = _touch(tmp_path / "flow-2026-09-09.sqlite")
    denied = _touch(tmp_path / "2026-08-20" / ".env")
    plan = plan_rotate(tmp_path, now=NOW, keep_days=7)
    upload = {i.src.name: i for i in plan.uploadable}
    assert "flow-2026-08-20.sqlite" in upload
    assert upload["flow-2026-08-20.sqlite"].box_relpath == (
        "daily/2026-08-20/flow-2026-08-20.sqlite"
    )
    assert "flow-2026-09-08.sqlite" not in upload
    assert "flow-2026-09-09.sqlite" not in upload
    assert any(i.src.name == ".env" and i.denied for i in plan.items)
    assert denied in [i.src for i in plan.denied_items]
    assert pack_date_from_path(recent) is not None
    assert today.exists()


def test_delete_fail_closed_without_verify_or_confirm(tmp_path: Path) -> None:
    _touch(tmp_path / "flow-2026-08-01.sqlite")
    plan = plan_rotate(tmp_path, now=NOW, keep_days=7)
    assert plan.can_delete() is False
    with pytest.raises(BoxRotateError, match="confirm_delete"):
        assert_can_delete(plan)
    verified = plan_rotate(tmp_path, now=NOW, keep_days=7, verified=True)
    assert verified.can_delete() is True
    confirmed = plan_rotate(tmp_path, now=NOW, keep_days=7, confirm_delete=True)
    assert confirmed.can_delete() is True


def test_symlink_to_creds_is_denied(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    creds = _touch(outside / ".env")
    archive = tmp_path / "archive"
    archive.mkdir()
    link = archive / "flow-2026-08-01.sqlite"
    link.symlink_to(creds)
    assert deny_reason(link, root=archive) == "deny_symlink"
    plan = plan_rotate(archive, now=NOW, keep_days=7)
    assert any(i.src == link and i.denied for i in plan.items)
    assert link not in [i.src for i in plan.uploadable]


def test_resolved_path_outside_root_denied(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = _touch(outside / "flow-2026-08-01.sqlite")
    archive = tmp_path / "archive"
    archive.mkdir()
    assert deny_reason(escaped, root=archive) == "deny_outside_archive_root"
    plan = plan_rotate(archive, now=NOW, keep_days=7, paths=[escaped])
    assert plan.uploadable == []
    assert any(i.deny_reason == "deny_outside_archive_root" for i in plan.denied_items)


def test_case_tricks_and_non_export_denied(tmp_path: Path) -> None:
    env_upper = _touch(tmp_path / ".ENV")
    staging = _touch(tmp_path / ".env.STAGING")
    pem = _touch(tmp_path / "host.PEM")
    notes = _touch(tmp_path / "2026-08-01" / "notes.txt")
    ok = _touch(tmp_path / "2026-08-01" / "flow.sqlite")
    assert deny_reason(env_upper) in {"deny_env_file", "deny_exact_name"}
    assert deny_reason(staging) == "deny_env_file"
    assert deny_reason(pem) == "deny_suffix:.pem"
    assert deny_reason(notes) == "deny_not_controlled_export"
    assert deny_reason(ok) is None
    plan = plan_rotate(tmp_path, now=NOW, keep_days=7)
    names = {i.src.name for i in plan.uploadable}
    assert "flow.sqlite" in names
    assert ".ENV" not in names
    assert ".env.STAGING" not in names
    assert "notes.txt" not in names


def test_script_dry_run_deny_list(tmp_path: Path) -> None:
    from scripts_loader import box_cold_rotate_script

    main = box_cold_rotate_script.main

    _touch(tmp_path / "flow-2026-08-01.sqlite")
    _touch(tmp_path / ".env")
    out = tmp_path / "plan.json"
    rc = main(
        [
            "--src",
            str(tmp_path),
            "--keep-hot-days",
            "7",
            "--dry-run",
            "--json-out",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "flow-2026-08-01.sqlite" in text
    assert "daily/2026-08-01" in text
    assert ".env" in text
    assert "YOUR_" not in text
    assert "token=" not in text.lower()
    rc_bad = main(["--src", str(tmp_path), "--keep-hot-days", "3", "--dry-run"])
    assert rc_bad == 2
    rc_del = main(["--src", str(tmp_path), "--delete"])
    assert rc_del == 2
