"""Schwab OAuth helper: fail-closed without creds; never invent tokens."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from groktrading.brokers.schwab_oauth import (
    CALLBACK_URL,
    ENV_APP_KEY,
    ENV_APP_SECRET,
    client_from_login_flow,
    credentials_present,
    main,
    missing_credential_names,
    refresh_client,
    repo_root,
    require_auth_ready,
    require_token_file,
    resolve_token_path,
    stub_message,
    token_file_present,
)
from groktrading.errors import SchwabAuthNotReady


@pytest.fixture
def clean_schwab_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv(ENV_APP_KEY, raising=False)
    monkeypatch.delenv(ENV_APP_SECRET, raising=False)
    token = tmp_path / "schwab_token.json"
    monkeypatch.setenv("SCHWAB_TOKEN_PATH", str(token))
    return tmp_path


def test_callback_url_is_exact_loopback() -> None:
    assert CALLBACK_URL == "https://127.0.0.1:8182"
    assert not CALLBACK_URL.endswith("/")


def test_missing_creds_fail_closed(clean_schwab_env: Path) -> None:
    assert missing_credential_names() == (ENV_APP_KEY, ENV_APP_SECRET)
    assert credentials_present() is False
    text = stub_message()
    assert ENV_APP_KEY in text
    assert ENV_APP_SECRET in text
    assert "Ready For Use" in text
    assert CALLBACK_URL in text
    assert "No browser will be opened" in text
    with pytest.raises(SchwabAuthNotReady, match="Missing env"):
        client_from_login_flow()
    assert not (clean_schwab_env / "schwab_token.json").exists()


def test_refuse_inventing_tokens_on_refresh(clean_schwab_env: Path) -> None:
    token = clean_schwab_env / "schwab_token.json"
    assert token_file_present() is False
    with pytest.raises(SchwabAuthNotReady, match="7 days") as missing:
        require_token_file()
    assert "Re-run" in str(missing.value)
    assert not token.exists()
    with pytest.raises(SchwabAuthNotReady, match="Missing env"):
        refresh_client()
    assert not token.exists()


def test_cli_without_env_is_actionable_stub(
    clean_schwab_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([]) == 2
    err = capsys.readouterr().err
    assert "dry-run / not ready" in err
    assert ENV_APP_KEY in err
    assert CALLBACK_URL in err
    assert not (clean_schwab_env / "schwab_token.json").exists()
    assert main(["--dry-run"]) == 2


def test_login_flow_with_placeholders_does_not_invent_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token = tmp_path / "schwab_token.json"
    monkeypatch.setenv(ENV_APP_KEY, "placeholder-app-key")
    monkeypatch.setenv(ENV_APP_SECRET, "placeholder-app-secret")
    monkeypatch.setenv("SCHWAB_TOKEN_PATH", str(token))

    def _missing_schwab() -> Any:
        raise SchwabAuthNotReady("schwab-py is not installed. test seam")

    monkeypatch.setattr(
        "groktrading.brokers.schwab_oauth._load_schwab_auth", _missing_schwab
    )
    with pytest.raises(SchwabAuthNotReady, match="schwab-py is not installed"):
        client_from_login_flow()
    assert not token.exists()

    recorded: dict[str, Any] = {}

    class FakeAuth:
        def client_from_login_flow(
            self,
            api_key: str,
            app_secret: str,
            callback_url: str,
            token_path: str,
        ) -> str:
            recorded["callback"] = callback_url
            recorded["token_path"] = token_path
            recorded["key_len"] = len(api_key)
            recorded["secret_len"] = len(app_secret)
            return "fake-client"

    assert client_from_login_flow(auth_module=FakeAuth()) == "fake-client"
    assert recorded["callback"] == CALLBACK_URL
    assert recorded["token_path"] == str(token)
    # Fake auth did not write a token; helper must not invent one either.
    assert not token.exists()


def test_refresh_with_empty_marker_file_uses_token_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token = tmp_path / "schwab_token.json"
    token.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv(ENV_APP_KEY, "placeholder-app-key")
    monkeypatch.setenv(ENV_APP_SECRET, "placeholder-app-secret")
    monkeypatch.setenv("SCHWAB_TOKEN_PATH", str(token))
    assert require_auth_ready() == token

    class FakeAuth:
        def client_from_token_file(
            self, token_path: str, api_key: str, app_secret: str
        ) -> str:
            assert token_path == str(token)
            return "refreshed-client"

    assert refresh_client(auth_module=FakeAuth()) == "refreshed-client"
    assert token.read_text(encoding="utf-8") == "{}\n"


def test_token_path_inside_repo_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo_root()
    assert root is not None
    inside = root / "schwab_token.json"
    monkeypatch.setenv(ENV_APP_KEY, "placeholder-app-key")
    monkeypatch.setenv(ENV_APP_SECRET, "placeholder-app-secret")
    monkeypatch.setenv("SCHWAB_TOKEN_PATH", str(inside))
    with pytest.raises(SchwabAuthNotReady, match="must not be inside the git repo"):
        client_from_login_flow(
            auth_module=type(
                "Auth",
                (),
                {"client_from_login_flow": staticmethod(lambda *a, **k: None)},
            )()
        )
    assert not inside.exists()


def test_resolve_default_token_path_is_outside_repo() -> None:
    path = resolve_token_path(environ={})
    root = repo_root()
    assert root is not None
    with pytest.raises(ValueError):
        path.resolve().relative_to(root.resolve())


def test_cli_refresh_without_token_is_seven_day_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ENV_APP_KEY, "placeholder-app-key")
    monkeypatch.setenv(ENV_APP_SECRET, "placeholder-app-secret")
    monkeypatch.setenv("SCHWAB_TOKEN_PATH", str(tmp_path / "schwab_token.json"))
    assert main(["--refresh"]) == 2
    err = capsys.readouterr().err
    assert "7 days" in err
    assert not (tmp_path / "schwab_token.json").exists()


def test_script_wrapper_matches_module() -> None:
    from scripts_loader import load

    script = load("schwab_oauth_stub", "scripts/schwab_oauth_stub.py")
    assert script.main is main
