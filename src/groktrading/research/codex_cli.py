"""Non-interactive Codex CLI invocation for Opening15 (ChatGPT session; no orders)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

MIN_VERSION = (0, 153, 0)
BINARY = "codex"
_SECRET_KEY = re.compile(r"(TOKEN|SECRET|PASSWORD|API_KEY|ACCESS)", re.IGNORECASE)
_KEEP_ENV = re.compile(
    r"^(PATH|HOME|USER|LOGNAME|LANG|LC_.*|SHELL|TMPDIR|TMP|TEMP|TERM|CODEX_HOME|"
    r"XDG_.*|SSL_.*|CURL_CA.*|REQUESTS_CA.*|HTTPS_PROXY|HTTP_PROXY|NO_PROXY|"
    r"https_proxy|http_proxy|no_proxy)$"
)


class CodexRun(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        input_text: str | None = None,
        timeout: float = 30,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


def parse_version(text: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        raise ValueError("could not parse Codex CLI version; require >= 0.153.0")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def format_version(value: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in value)


def subprocess_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Inherit only non-secret process env. Codex auth stays in CODEX_HOME / HOME."""
    env: dict[str, str] = {}
    for key, value in (source or os.environ).items():
        if key == "OPENAI_API_KEY" or _SECRET_KEY.search(key) or not _KEEP_ENV.match(key):
            continue
        env[key] = value
    return env


def run_codex(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout: float = 30,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=dict(env) if env is not None else subprocess_env(),
        check=False,
    )


def inspect(runner: CodexRun | None = None, binary: str = BINARY) -> dict[str, Any]:
    """Record `codex --version` and fail closed if the ChatGPT CLI session is missing."""
    runner = runner or run_codex
    try:
        version_proc = runner([binary, "--version"], timeout=30, env=subprocess_env())
    except FileNotFoundError as exc:
        raise ValueError(
            "Codex CLI not found on PATH. Install @openai/codex >= 0.153.0, then `codex login`."
        ) from exc
    version_text = (version_proc.stdout or version_proc.stderr or "").strip()
    if version_proc.returncode != 0:
        raise ValueError("codex --version failed; install Codex CLI >= 0.153.0")
    parsed = parse_version(version_text)
    if parsed < MIN_VERSION:
        raise ValueError(
            f"Codex CLI {format_version(parsed)} is too old; "
            f"require >= {format_version(MIN_VERSION)} for Astra/GPT-6"
        )
    try:
        status = runner([binary, "login", "status"], timeout=30, env=subprocess_env())
    except FileNotFoundError as exc:
        raise ValueError(
            "Codex CLI not found on PATH. Install @openai/codex >= 0.153.0, then `codex login`."
        ) from exc
    if status.returncode != 0:
        raise ValueError(
            "Codex CLI is not logged in. Run `codex login` with the ChatGPT Pro account. "
            "OPENAI_API_KEY is not used when recommend_backend=codex_cli."
        )
    return {
        "binary": binary,
        "version": version_text,
        "version_tuple": list(parsed),
        "logged_in": True,
        "auth": "chatgpt_cli_session",
    }


def exec_argv(
    *,
    model: str,
    reasoning_effort: str,
    schema_path: Path,
    message_path: Path,
    work_dir: Path,
    binary: str = BINARY,
) -> list[str]:
    """Documented non-interactive invocation (`codex exec`, prompt on stdin)."""
    return [
        binary,
        "exec",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--color",
        "never",
        "--sandbox",
        "read-only",
        "--json",
        "--model",
        model,
        "-c",
        f"model_reasoning_effort={reasoning_effort}",
        "-c",
        "approval_policy=never",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(message_path),
        "--cd",
        str(work_dir),
        "-",
    ]


def parse_events(stdout: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events: list[dict[str, Any]] = []
    usage: dict[str, Any] = {}
    model: str | None = None
    for line in stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        events.append(event)
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        if isinstance(event.get("model"), str):
            model = event["model"]
        item = event.get("item")
        if isinstance(item, dict) and isinstance(item.get("model"), str):
            model = item["model"]
    return events, {"usage": usage, "returned_model": model}


def loads_structured(text: str) -> Any:
    payload = text.strip()
    if payload.startswith("```"):
        payload = payload.split("\n", 1)[-1]
        fence = payload.rfind("```")
        if fence >= 0:
            payload = payload[:fence]
        payload = payload.strip()
        if payload.lower().startswith("json"):
            payload = payload[4:].lstrip()
    return json.loads(payload)
