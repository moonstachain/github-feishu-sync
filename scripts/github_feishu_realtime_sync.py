#!/usr/bin/env python3
"""Receive GitHub webhooks and sync repositories into Feishu Bitable."""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import threading
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from github_skill_pattern_to_feishu import DEFAULT_BASE_TOKEN, DEFAULT_GITHUB_USER, sync_repos


LOGGER = logging.getLogger("github-feishu-realtime-sync")
SYNC_LOCK = threading.Lock()


def env_or_arg(name: str, value: str | None) -> str | None:
    return value or os.environ.get(name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub webhook receiver for Feishu skill-pattern sync")
    parser.add_argument("--host", default=os.environ.get("SYNC_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SYNC_PORT", "8787")))
    parser.add_argument("--github-user", default=os.environ.get("GITHUB_USER", DEFAULT_GITHUB_USER))
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--github-webhook-secret", default=os.environ.get("GITHUB_WEBHOOK_SECRET"))
    parser.add_argument("--feishu-app-id", default=os.environ.get("FEISHU_APP_ID"))
    parser.add_argument("--feishu-app-secret", default=os.environ.get("FEISHU_APP_SECRET"))
    parser.add_argument("--feishu-base-token", default=os.environ.get("FEISHU_BASE_TOKEN", DEFAULT_BASE_TOKEN))
    parser.add_argument("--repo-manifest", help="Fallback manifest when GITHUB_TOKEN is unavailable")
    return parser.parse_args()


ARGS = parse_args()
APP = FastAPI(title="GitHub Feishu Realtime Sync", version="1.0.0")


def verify_signature(secret: str | None, body: bytes, signature: str | None) -> None:
    if not secret:
        return
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def should_sync(event_name: str, payload: dict[str, Any], github_user: str) -> tuple[bool, str | None]:
    repository = payload.get("repository") or {}
    owner = ((repository.get("owner") or {}).get("login") or "").strip()
    full_name = (repository.get("full_name") or "").strip()

    if event_name == "ping":
        return False, None
    if owner and owner != github_user:
        return False, None
    if event_name in {"push", "repository", "public", "create"} and full_name:
        return True, full_name
    if event_name in {"delete", "member", "membership"}:
        return True, None
    return False, None


def run_sync(repo_full_name: str | None) -> dict[str, Any]:
    sync_args = SimpleNamespace(
        github_user=ARGS.github_user,
        github_token=ARGS.github_token,
        repo_full_name=repo_full_name,
        output_manifest=None,
        repo_manifest=ARGS.repo_manifest,
        feishu_app_id=ARGS.feishu_app_id,
        feishu_app_secret=ARGS.feishu_app_secret,
        feishu_base_token=ARGS.feishu_base_token,
    )
    summary = sync_repos(sync_args)
    result = summary.to_dict()
    result["mode"] = "single_repo" if repo_full_name else "full_sync"
    return result


@APP.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@APP.post("/github/webhook")
async def github_webhook(request: Request) -> dict[str, Any]:
    body = await request.body()
    verify_signature(ARGS.github_webhook_secret, body, request.headers.get("X-Hub-Signature-256"))

    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    event_name = request.headers.get("X-GitHub-Event", "")
    sync_needed, repo_full_name = should_sync(event_name, payload, ARGS.github_user)
    if event_name == "ping":
        return {"ok": True, "event": "ping"}
    if not sync_needed:
        return {"ok": True, "event": event_name, "skipped": True}

    with SYNC_LOCK:
        result = run_sync(repo_full_name)
    LOGGER.info("Processed event=%s repo=%s result=%s", event_name, repo_full_name, result)
    return {"ok": True, "event": event_name, "repo_full_name": repo_full_name, "summary": result}


def main() -> int:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(APP, host=ARGS.host, port=ARGS.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
