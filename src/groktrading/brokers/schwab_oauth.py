"""Schwab OAuth helper — auth scaffolding only. No order or quote HTTP.

Operator flow
-------------
1. Create a Schwab developer app: **Trader API**, **Individual** product.
2. Set the callback URL exactly ``https://127.0.0.1:8182`` (no trailing slash).
3. Wait until app status is **Ready For Use**. Submitted is not enough.
4. Copy App Key / App Secret into a secret store (never git / never this repo).
5. Export ``SCHWAB_APP_KEY``, ``SCHWAB_APP_SECRET``, and optionally
   ``SCHWAB_TOKEN_PATH``. Default token path is
   ``~/.config/groktrading/schwab_token.json`` (outside the repo).
6. Run ``python -m groktrading.brokers.schwab_oauth`` (or
   ``groktrading-schwab-oauth``). Browser login persists a refresh token.
7. Access tokens last ~30 minutes; refresh tokens last ~7 days. Re-run the
   login flow weekly. WebSocket events must never place orders.

Dry-run / missing credentials
-----------------------------
If App Key or App Secret is unset, the helper prints which env vars are
required and exits. It does not start a browser, bind port 8182, or write a
token file. This module never invents tokens.

Optional dependency
-------------------
The real ``client_from_login_flow`` / token-refresh path is a thin wrapper
around ``schwab-py`` when installed (``pip install 'groktrading[schwab]'``
or ``pip install schwab-py``). Without that extra, login/refresh raise
``SchwabAuthNotReady`` with an install hint. No live Schwab network call
that requires real credentials is made unless keys are present *and*
``schwab-py`` is invoked by the operator.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from groktrading.errors import SchwabAuthNotReady

# Desk-hard callback. Must match the Schwab developer portal exactly.
CALLBACK_URL = "https://127.0.0.1:8182"

ENV_APP_KEY = "SCHWAB_APP_KEY"
ENV_APP_SECRET = "SCHWAB_APP_SECRET"
ENV_TOKEN_PATH = "SCHWAB_TOKEN_PATH"

ACCESS_TOKEN_TTL = "~30 minutes"
REFRESH_TOKEN_TTL = "~7 days"

_DEFAULT_TOKEN_RELATIVE = Path(".config") / "groktrading" / "schwab_token.json"

_SCHWAB_PY_HINT = (
    "schwab-py is not installed. Install the optional extra: "
    "pip install 'groktrading[schwab]'  or  pip install schwab-py"
)

_LOGIN_HINT = "python -m groktrading.brokers.schwab_oauth"


def default_token_path() -> Path:
    """Local token path outside the repo. Never commit this file."""
    return Path.home() / _DEFAULT_TOKEN_RELATIVE


def resolve_token_path(
    environ: Mapping[str, str] | None = None,
    token_path: Path | str | None = None,
) -> Path:
    if token_path is not None:
        return Path(token_path).expanduser()
    raw = _env(environ).get(ENV_TOKEN_PATH, "").strip()
    if raw:
        return Path(raw).expanduser()
    return default_token_path()


def missing_credential_names(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    env = _env(environ)
    missing: list[str] = []
    if not str(env.get(ENV_APP_KEY, "")).strip():
        missing.append(ENV_APP_KEY)
    if not str(env.get(ENV_APP_SECRET, "")).strip():
        missing.append(ENV_APP_SECRET)
    return tuple(missing)


def credentials_present(environ: Mapping[str, str] | None = None) -> bool:
    return not missing_credential_names(environ)


def read_app_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Return (app_key, app_secret) or raise. Values are never logged here."""
    env = _env(environ)
    missing = missing_credential_names(env)
    if missing:
        raise SchwabAuthNotReady(stub_message(environ=env))
    return env[ENV_APP_KEY].strip(), env[ENV_APP_SECRET].strip()


def token_file_present(
    environ: Mapping[str, str] | None = None,
    token_path: Path | str | None = None,
) -> bool:
    return resolve_token_path(environ, token_path).is_file()


def repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "groktrading").is_dir():
            return parent
    return None


def assert_token_path_outside_repo(path: Path) -> None:
    """Refuse to persist tokens inside the git tree."""
    root = repo_root()
    if root is None:
        return
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return
    raise SchwabAuthNotReady(
        f"{ENV_TOKEN_PATH} must not be inside the git repo ({root}). "
        f"Default is {default_token_path()}."
    )


def require_credentials(environ: Mapping[str, str] | None = None) -> tuple[str, str]:
    return read_app_credentials(environ)


def require_token_file(
    environ: Mapping[str, str] | None = None,
    token_path: Path | str | None = None,
) -> Path:
    """Existing token path, or raise with a 7-day re-auth reminder.

    Does not create or invent a token file.
    """
    path = resolve_token_path(environ, token_path)
    assert_token_path_outside_repo(path)
    if not path.is_file():
        raise SchwabAuthNotReady(
            f"No Schwab token file at {path}. Refresh tokens last {REFRESH_TOKEN_TTL}; "
            f"access tokens last {ACCESS_TOKEN_TTL}. Re-run {_LOGIN_HINT} after "
            f"Ready For Use and {ENV_APP_KEY}/{ENV_APP_SECRET}."
        )
    return path


def require_auth_ready(
    environ: Mapping[str, str] | None = None,
    token_path: Path | str | None = None,
) -> Path:
    """Credentials + existing token file. Still not a live order path."""
    require_credentials(environ)
    return require_token_file(environ, token_path)


def stub_message(
    *,
    environ: Mapping[str, str] | None = None,
    token_path: Path | str | None = None,
) -> str:
    """Actionable dry-run text. Safe to print: no secret values."""
    missing = missing_credential_names(environ)
    path = resolve_token_path(environ, token_path)
    lines = [
        "Schwab OAuth helper (dry-run / not ready).",
        "No browser will be opened. No token file will be written.",
        "",
        "Operator steps:",
        "1. Create a Schwab developer app: Trader API, Individual product.",
        f"2. Set callback URL exactly: {CALLBACK_URL}",
        "   (no trailing slash).",
        "3. Wait for app status Ready For Use (Submitted is not enough).",
        "4. Copy App Key / App Secret to a secret store (never git).",
        f"5. Export {ENV_APP_KEY}, {ENV_APP_SECRET};",
        f"   optional {ENV_TOKEN_PATH} (default {default_token_path()}).",
        f"6. Run: {_LOGIN_HINT}",
        f"7. Re-auth weekly: refresh tokens last {REFRESH_TOKEN_TTL}; "
        f"access tokens last {ACCESS_TOKEN_TTL}.",
        "8. WebSocket events must never place orders.",
        "",
    ]
    if missing:
        lines.append("Missing env: " + ", ".join(missing) + ".")
    else:
        lines.append(f"App Key/Secret are set. Token path: {path}")
        if not path.is_file():
            lines.append("No token file yet. Login flow will persist one (not in git).")
    return "\n".join(lines)


def client_from_login_flow(
    *,
    environ: Mapping[str, str] | None = None,
    token_path: Path | str | None = None,
    auth_module: Any | None = None,
) -> Any:
    """Thin wrap of ``schwab.auth.client_from_login_flow``.

    Callable only when App Key and App Secret are present. Does not invent a
    token file. ``auth_module`` is a test seam; operators leave it unset.
    """
    api_key, app_secret = require_credentials(environ)
    path = resolve_token_path(environ, token_path)
    assert_token_path_outside_repo(path)
    auth = auth_module if auth_module is not None else _load_schwab_auth()
    path.parent.mkdir(parents=True, exist_ok=True)
    return auth.client_from_login_flow(
        api_key,
        app_secret,
        CALLBACK_URL,
        str(path),
    )


def refresh_client(
    *,
    environ: Mapping[str, str] | None = None,
    token_path: Path | str | None = None,
    auth_module: Any | None = None,
) -> Any:
    """Load an existing token via ``schwab-py`` (auto-refresh on use).

    Missing token file raises with a 7-day re-auth reminder.
    Does not invent tokens.
    """
    api_key, app_secret = require_credentials(environ)
    path = require_token_file(environ, token_path)
    auth = auth_module if auth_module is not None else _load_schwab_auth()
    return auth.client_from_token_file(str(path), api_key, app_secret)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Schwab OAuth helper. Dry-run without env vars. "
            "Never places orders. Callback "
            f"{CALLBACK_URL} (no trailing slash)."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print operator steps and missing env vars. Never open a browser.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Load an existing token file (schwab-py refreshes access as needed).",
    )
    parser.add_argument(
        "--token-path",
        default=None,
        help=f"Override {ENV_TOKEN_PATH} / default {default_token_path()}.",
    )
    args = parser.parse_args(argv)
    token_path = Path(args.token_path).expanduser() if args.token_path else None

    if args.dry_run or not credentials_present():
        print(stub_message(token_path=token_path), file=sys.stderr)
        return 2 if not credentials_present() else 0

    try:
        if args.refresh:
            refresh_client(token_path=token_path)
            print(
                f"Schwab token loaded from {resolve_token_path(token_path=token_path)}. "
                f"Access ~30m / refresh {REFRESH_TOKEN_TTL}. No orders placed.",
                file=sys.stderr,
            )
            return 0
        client_from_login_flow(token_path=token_path)
        print(
            f"Schwab login flow completed. Token path "
            f"{resolve_token_path(token_path=token_path)}. No orders placed.",
            file=sys.stderr,
        )
        return 0
    except SchwabAuthNotReady as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _load_schwab_auth() -> Any:
    try:
        return importlib.import_module("schwab.auth")
    except ImportError as exc:
        raise SchwabAuthNotReady(_SCHWAB_PY_HINT) from exc


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACCESS_TOKEN_TTL",
    "CALLBACK_URL",
    "ENV_APP_KEY",
    "ENV_APP_SECRET",
    "ENV_TOKEN_PATH",
    "REFRESH_TOKEN_TTL",
    "assert_token_path_outside_repo",
    "client_from_login_flow",
    "credentials_present",
    "default_token_path",
    "main",
    "missing_credential_names",
    "read_app_credentials",
    "refresh_client",
    "repo_root",
    "require_auth_ready",
    "require_credentials",
    "require_token_file",
    "resolve_token_path",
    "stub_message",
    "token_file_present",
]
