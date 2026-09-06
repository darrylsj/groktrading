"""Unit coverage for the public-audit secret scanner."""

from __future__ import annotations

from groktrading.redaction import REDACTED
from scripts_loader import scan_secrets as scanner


def test_placeholders_are_allowed() -> None:
    text = "FINNHUB_API_KEY=YOUR_FINNHUB_API_KEY\nGROK_WEBHOOK_SECRET=changeme\n"
    assert scanner.scan_text(text) == []


def test_example_tokens_allowed() -> None:
    text = 'token="unused-test-token"\nsecret="test-secret-not-production"\n'
    assert scanner.scan_text(text) == []


def test_redacted_and_account_placeholder_allowed() -> None:
    text = f"token={REDACTED}\nTRADIER_ACCOUNT_ID=ACCOUNT_ID_REDACTED\n"
    assert scanner.scan_text(text) == []


def test_openai_and_github_shapes_fail() -> None:
    hits = scanner.scan_text("openai sk-" + ("a" * 24) + " and ghp_" + ("b" * 24))
    names = {name for name, _ in hits}
    assert "openai-sk" in names
    assert "github-pat" in names


def test_pem_header_fails() -> None:
    header = "-----BEGIN OPENSSH " + "PRIVATE KEY-----"
    hits = scanner.scan_text(header + "\n")
    assert any(name == "openssh-private-key" for name, _ in hits)


def test_known_live_account_id_fails() -> None:
    live = "6YB" + "72238"
    hits = scanner.scan_text(f"account {live} in a doc")
    assert any(name == "forbidden-account-id" for name, _ in hits)


def test_home_box_secret_path_fails() -> None:
    path = "/home/" + "box/audit/tradier." + "token"
    hits = scanner.scan_text(f"see {path} for the pack")
    assert any(name == "home-box-secret-path" for name, _ in hits)
