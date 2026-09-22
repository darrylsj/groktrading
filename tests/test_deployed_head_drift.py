"""Local deployed-vs-HEAD helper. No network and no secret echo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts_loader import load

ROOT = Path(__file__).resolve().parents[1]
drift = load("deployed_head_drift", "scripts/deployed_head_drift.py")


def _head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def test_prints_head_and_expected_paths_without_claiming_a_match(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = drift.main(["--repo", str(ROOT)])
    captured = capsys.readouterr()
    assert code == 0
    assert f"head={_head()}" in captured.out
    package_line = (
        f"expected_package_command=git -C {drift.PACKAGE_INSTALL_ROOT} rev-parse HEAD"
    )
    assert package_line in captured.out
    assert f"expected_legacy_revision_file={drift.LEGACY_RUNNING_REVISION}" in captured.out
    assert "expected_legacy_revision_file_in_repo=false" in captured.out
    assert "comparison=skipped_no_deployed_fingerprint" in captured.out
    assert captured.err == ""


def test_match_and_drift(capsys: pytest.CaptureFixture[str]) -> None:
    head = _head()
    assert drift.main(["--repo", str(ROOT), "--deployed-sha", head]) == 0
    assert "comparison=match" in capsys.readouterr().out

    assert drift.main(["--repo", str(ROOT), "--deployed-sha", "0" * 40]) == 2
    assert "comparison=drift" in capsys.readouterr().out


def test_malformed_sha_is_not_echoed(capsys: pytest.CaptureFixture[str]) -> None:
    raw = "not-a-sha-do-not-echo"
    code = drift.main(["--repo", str(ROOT), "--deployed-sha", raw])
    captured = capsys.readouterr()
    assert code == 1
    assert "malformed_deployed_revision" in captured.err
    assert raw not in captured.err
    assert raw not in captured.out


def test_revision_file_must_be_one_sha(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "running_revision"
    extra = "second-line-do-not-echo"
    path.write_text(_head() + "\n" + extra + "\n", encoding="utf-8")
    code = drift.main(["--repo", str(ROOT), "--deployed-file", str(path)])
    captured = capsys.readouterr()
    assert code == 1
    assert extra not in captured.out
    assert extra not in captured.err

    path.write_text(_head() + "\n", encoding="utf-8")
    assert drift.main(["--repo", str(ROOT), "--deployed-file", str(path)]) == 0


def test_doc_wires_the_same_paths() -> None:
    text = (ROOT / "docs" / "DEPLOYED_HEAD_DRIFT.md").read_text(encoding="utf-8")
    assert drift.LEGACY_RUNNING_REVISION in text
    assert drift.PACKAGE_INSTALL_ROOT in text
    assert "does not SSH" in text
    assert "skipped_no_deployed_fingerprint" in text
    assert "2026-09-21" in text


def test_live_flag_provenance_is_documented() -> None:
    safety = (ROOT / "docs" / "SAFETY.md").read_text(encoding="utf-8")
    for needle in (
        "live_explicitly_enabled",
        "GateContext.live_explicitly_enabled",
        "OrderMachine.live_explicitly_enabled",
        "Executor.live_explicitly_enabled",
        "GROKTRADING_LIVE_EXPLICITLY_ENABLED",
        "WS_DIRECT_LIVE_FORBIDDEN",
        "LIVE_NOT_ENABLED",
        "evaluate_gate",
        "OrderMachine.final_gate",
        "from_websocket",
    ):
        assert needle in safety, needle
    assert "live_explicitly_enabled=True" not in (
        ROOT / "deploy" / "examples" / "env" / "groktrading.env.example"
    ).read_text(encoding="utf-8")
