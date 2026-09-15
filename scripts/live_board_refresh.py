#!/usr/bin/env python3
"""Helsinki weekday RTH live-board refresh. Zero LLM. Never orders.

Reads host sensor files (live_tape / finnhub_tape / shortlist, optional
refuse JSONL) and writes static live.json + index.html. Deploys to the
sibling Vercel project only when /etc/trading-desk/vercel.env provides
VERCEL_TOKEN. Missing token: write local artifacts and exit 0.

sit_match stays OFF. Does not resume shortlist_opportunity. No Cursor
wakes. No Grok webhooks. Never invents prices. Never logs tokens.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from dashboard.builder import build_board, write_board
from dashboard.config import (
    FUNNEL_LAG_NOTE,
    HOST_BOOK,
    HOST_FINNHUB_TAPE,
    HOST_LIVE_BOARD_OUT,
    HOST_LIVE_TAPE,
    HOST_OPEN_ORDERS,
    HOST_REFUSE_CANDIDATES,
    HOST_SHORTLIST,
    HOST_VERCEL_ENV,
    LIVE_GATE,
    REFRESH_NOTE,
    VERCEL_PROJECT_NAME,
    DashboardError,
)

VERCEL_DEPLOY_API = "https://api.vercel.com/v13/deployments"
DEFAULT_PROJECT = VERCEL_PROJECT_NAME


def _info(message: str) -> None:
    print(f"live_board_refresh: {message}", flush=True)


def _path_or_none(value: str | None) -> Path | None:
    if value is None or not str(value).strip():
        return None
    return Path(value)


def discover_refuses(explicit: Path | None) -> Path | None:
    """First local refuse ledger wins. Missing is an honest empty funnel."""
    if explicit is not None:
        return explicit
    for raw in HOST_REFUSE_CANDIDATES:
        candidate = Path(raw)
        if candidate.is_file():
            return candidate
    return None


def load_dotenv_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Never logs values. Comments and blanks skipped."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            out[key] = value
    return out


def vercel_creds(env_file: Path | None, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Collect Vercel deploy knobs. File wins over process env for token source."""
    env = dict(environ or os.environ)
    loaded = load_dotenv_file(env_file) if env_file is not None else {}
    creds: dict[str, str] = {}
    for key in ("VERCEL_TOKEN", "VERCEL_ORG_ID", "VERCEL_PROJECT_ID", "VERCEL_PROJECT_NAME"):
        value = (loaded.get(key) or env.get(key) or "").strip()
        if value:
            creds[key] = value
    return creds


def _safe_deploy_error(exc: BaseException) -> str:
    text = str(exc)
    lowered = text.lower()
    for needle in ("bearer ", "authorization:", "vercel_token="):
        if needle in lowered:
            return "vercel_deploy_failed"
    return text[:200] if text else "vercel_deploy_failed"


def _inline_file(name: str, content: str) -> dict[str, str]:
    payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return {"file": name, "data": payload, "encoding": "base64"}


def deploy_via_api(
    out_dir: Path,
    creds: dict[str, str],
    *,
    opener: Any | None = None,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """POST static files to Vercel Deploy API. Token is never returned."""
    token = creds.get("VERCEL_TOKEN") or ""
    if not token:
        return {"ok": False, "skipped": True, "reason": "vercel_token_missing"}
    files: list[dict[str, str]] = []
    for name in ("index.html", "live.json", "board.json"):
        path = out_dir / name
        if path.is_file():
            files.append(_inline_file(name, path.read_text(encoding="utf-8")))
    if not files:
        return {"ok": False, "skipped": False, "reason": "no_artifacts"}
    project = creds.get("VERCEL_PROJECT_ID") or creds.get("VERCEL_PROJECT_NAME") or DEFAULT_PROJECT
    body = {
        "name": creds.get("VERCEL_PROJECT_NAME") or DEFAULT_PROJECT,
        "project": project,
        "target": "production",
        "files": files,
        "projectSettings": {"framework": None},
    }
    query: dict[str, str] = {"skipAutoDetectionConfirmation": "1", "forceNew": "1"}
    org = creds.get("VERCEL_ORG_ID") or ""
    if org:
        query["teamId"] = org
    url = f"{VERCEL_DEPLOY_API}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    try:
        with open_fn(request, timeout=timeout) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        status = int(exc.code)
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return {
            "ok": False,
            "skipped": False,
            "reason": "vercel_api_error",
            "detail": _safe_deploy_error(exc),
        }
    parsed: Any
    try:
        parsed = json.loads(raw.decode("utf-8", errors="replace") or "null")
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    deploy_url = parsed.get("url") or parsed.get("readyUrl")
    deploy_id = parsed.get("id") or parsed.get("deploymentId")
    ok = 200 <= status < 300 and bool(deploy_id or deploy_url)
    result: dict[str, Any] = {
        "ok": ok,
        "skipped": False,
        "method": "api",
        "status": status,
        "id": str(deploy_id) if deploy_id else None,
        "url": (
            f"https://{deploy_url}"
            if deploy_url and not str(deploy_url).startswith("http")
            else deploy_url
        ),
        "reason": None if ok else "vercel_api_rejected",
    }
    return result


def deploy_via_npx(
    out_dir: Path, creds: dict[str, str], *, timeout: float = 90.0
) -> dict[str, Any]:
    """Fallback: npx vercel deploy --prod. Token via env, never argv."""
    token = creds.get("VERCEL_TOKEN") or ""
    if not token:
        return {"ok": False, "skipped": True, "reason": "vercel_token_missing"}
    npx = shutil.which("npx")
    if not npx:
        return {"ok": False, "skipped": False, "reason": "npx_missing"}
    project_dir = out_dir / ".vercel"
    project_dir.mkdir(parents=True, exist_ok=True)
    org = creds.get("VERCEL_ORG_ID") or ""
    project = creds.get("VERCEL_PROJECT_ID") or ""
    if org and project:
        (project_dir / "project.json").write_text(
            json.dumps({"orgId": org, "projectId": project}) + "\n",
            encoding="utf-8",
        )
    env = os.environ.copy()
    env["VERCEL_TOKEN"] = token
    if org:
        env["VERCEL_ORG_ID"] = org
    if project:
        env["VERCEL_PROJECT_ID"] = project
    cmd = [npx, "--yes", "vercel@41", "deploy", "--prod", "--yes"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=out_dir,
            env=env,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "skipped": False,
            "reason": "npx_error",
            "detail": _safe_deploy_error(exc),
        }
    stdout = proc.stdout.strip() if proc.stdout else ""
    url = ""
    for line in reversed(stdout.splitlines()):
        if "https://" in line:
            url = line.strip().split()[-1]
            break
    ok = proc.returncode == 0 and bool(url)
    return {
        "ok": ok,
        "skipped": False,
        "method": "npx",
        "status": proc.returncode,
        "url": url or None,
        "reason": None if ok else "npx_deploy_failed",
    }


def maybe_deploy(out_dir: Path, creds: dict[str, str]) -> dict[str, Any]:
    if not creds.get("VERCEL_TOKEN"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "vercel_token_missing",
            "note": (
                "local artifacts written; Vercel deploy skipped "
                "(no VERCEL_TOKEN in vercel.env or environment)"
            ),
        }
    api = deploy_via_api(out_dir, creds)
    if api.get("ok"):
        return api
    npx = deploy_via_npx(out_dir, creds)
    if npx.get("ok"):
        return npx
    return {
        "ok": False,
        "skipped": False,
        "reason": api.get("reason") or npx.get("reason") or "vercel_deploy_failed",
        "api": {k: v for k, v in api.items() if k != "detail" or v != "vercel_deploy_failed"},
        "npx": {k: v for k, v in npx.items() if k != "detail" or v != "vercel_deploy_failed"},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-tape", default=os.environ.get("LIVE_TAPE_PATH", HOST_LIVE_TAPE))
    parser.add_argument(
        "--finnhub-tape",
        default=os.environ.get("FINNHUB_TAPE_PATH", HOST_FINNHUB_TAPE),
    )
    parser.add_argument("--shortlist", default=os.environ.get("SHORTLIST_PATH", HOST_SHORTLIST))
    parser.add_argument("--refuses", default=os.environ.get("REFUSES_PATH") or None)
    parser.add_argument("--book", default=os.environ.get("BOOK_PATH", HOST_BOOK))
    parser.add_argument(
        "--open-orders",
        default=os.environ.get("OPEN_ORDERS_PATH", HOST_OPEN_ORDERS),
    )
    parser.add_argument(
        "--shadow-summary",
        default=os.environ.get("SHADOW_SUMMARY_PATH") or None,
    )
    parser.add_argument("--out-dir", default=os.environ.get("LIVE_BOARD_OUT", HOST_LIVE_BOARD_OUT))
    parser.add_argument(
        "--vercel-env",
        default=os.environ.get("VERCEL_ENV_FILE", HOST_VERCEL_ENV),
    )
    parser.add_argument("--session", default=None)
    parser.add_argument("--now", default=None)
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Write local artifacts only (CI / no token).",
    )
    return parser


def _print_result(doc: dict[str, Any]) -> None:
    print(json.dumps(doc, indent=2, sort_keys=True, default=str))


def _result(
    *,
    ok: bool,
    written: dict[str, str],
    deploy: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "kind": "live_board_refresh",
        "ok": ok,
        "live_gate": LIVE_GATE,
        "places_orders": False,
        "invented": False,
        "sit_match": False,
        "opportunity_webhook_resume": False,
        "llm": False,
        "written": written,
        "deploy": deploy,
        "note": REFRESH_NOTE,
    }
    if extra:
        doc.update(extra)
    return doc


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    refuses = discover_refuses(_path_or_none(args.refuses))
    live_tape = _path_or_none(args.live_tape)
    finnhub = _path_or_none(args.finnhub_tape)
    shortlist = _path_or_none(args.shortlist)
    book = _path_or_none(args.book)
    open_orders = _path_or_none(args.open_orders)
    shadow = _path_or_none(args.shadow_summary)
    out_dir = Path(args.out_dir)
    try:
        board = build_board(
            refuses=refuses,
            shortlist=shortlist,
            shadow_summary=shadow,
            finnhub_tape=finnhub,
            live_tape=live_tape,
            book=book,
            open_orders=open_orders,
            session=args.session,
            now=args.now,
        )
        funnel = board.get("funnel") if isinstance(board.get("funnel"), dict) else {}
        if not funnel.get("present"):
            board["funnel_lag_note"] = FUNNEL_LAG_NOTE
        board["refresh"] = {
            "owner": "helsinki",
            "kind": "rth_live_board_refresh",
            "llm": False,
            "cadence": "weekday RTH every 5 minutes 09:00-15:55 ET",
            "tz": "America/New_York",
            "artifacts": ["index.html", "live.json"],
            "deploy_project": DEFAULT_PROJECT,
            "sit_match": False,
            "opportunity_webhook_resume": False,
            "places_orders": False,
            "note": REFRESH_NOTE,
        }
        written = write_board(board, out_dir=out_dir)
    except DashboardError as exc:
        doc = _result(
            ok=False,
            written={},
            deploy={"ok": False, "skipped": True, "reason": "build_failed"},
            extra={"reasons": [exc.code], "error": str(exc)},
        )
        _print_result(doc)
        return 2
    except OSError as exc:
        doc = _result(
            ok=False,
            written={},
            deploy={"ok": False, "skipped": True, "reason": "write_failed"},
            extra={"reasons": ["write_failed"], "error": str(exc.strerror or exc)},
        )
        _print_result(doc)
        return 2

    vercel_path = _path_or_none(args.vercel_env)
    if args.skip_deploy:
        deploy = {
            "ok": True,
            "skipped": True,
            "reason": "skip_deploy",
            "note": "local artifacts written; deploy not requested",
        }
        _info(f"wrote {written.get('live_json')} (deploy skipped)")
        _print_result(_result(ok=True, written=written, deploy=deploy))
        return 0

    creds = vercel_creds(vercel_path)
    deploy = maybe_deploy(out_dir, creds)
    if deploy.get("skipped"):
        _info(deploy.get("note") or "Vercel deploy skipped: VERCEL_TOKEN missing")
        _print_result(_result(ok=True, written=written, deploy=deploy))
        return 0
    if deploy.get("ok"):
        _info(f"deployed {deploy.get('url') or deploy.get('id') or 'ok'}")
        _print_result(_result(ok=True, written=written, deploy=deploy))
        return 0
    _info(f"local artifacts written; deploy failed ({deploy.get('reason')})")
    _print_result(_result(ok=False, written=written, deploy=deploy))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
