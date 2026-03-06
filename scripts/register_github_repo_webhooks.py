#!/usr/bin/env python3
"""Register or update GitHub webhooks for all repos under a user."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import requests

from github_skill_pattern_to_feishu import DEFAULT_GITHUB_USER, fetch_github_repos, github_headers


GITHUB_API_BASE = "https://api.github.com"
DEFAULT_EVENTS = ["push", "repository", "create", "delete", "public"]


def env_or_arg(name: str, value: str | None) -> str | None:
    return value or os.environ.get(name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register GitHub webhooks for repo-to-Feishu sync")
    parser.add_argument("--github-user", default=os.environ.get("GITHUB_USER", DEFAULT_GITHUB_USER))
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--delivery-url", required=True)
    parser.add_argument("--webhook-secret", default=os.environ.get("GITHUB_WEBHOOK_SECRET", ""))
    parser.add_argument("--events", nargs="*", default=DEFAULT_EVENTS)
    return parser.parse_args()


def list_repo_hooks(full_name: str, token: str) -> list[dict[str, Any]]:
    response = requests.get(
        f"{GITHUB_API_BASE}/repos/{full_name}/hooks",
        headers=github_headers(token),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def create_repo_hook(full_name: str, token: str, delivery_url: str, webhook_secret: str, events: list[str]) -> str:
    payload = {
        "name": "web",
        "active": True,
        "events": events,
        "config": {
            "url": delivery_url,
            "content_type": "json",
            "secret": webhook_secret,
            "insecure_ssl": "0",
        },
    }
    response = requests.post(
        f"{GITHUB_API_BASE}/repos/{full_name}/hooks",
        headers=github_headers(token, accept="application/vnd.github+json"),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return "created"


def update_repo_hook(
    full_name: str,
    hook_id: int,
    token: str,
    delivery_url: str,
    webhook_secret: str,
    events: list[str],
) -> str:
    payload = {
        "active": True,
        "events": events,
        "config": {
            "url": delivery_url,
            "content_type": "json",
            "secret": webhook_secret,
            "insecure_ssl": "0",
        },
    }
    response = requests.patch(
        f"{GITHUB_API_BASE}/repos/{full_name}/hooks/{hook_id}",
        headers=github_headers(token, accept="application/vnd.github+json"),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return "updated"


def main() -> int:
    args = parse_args()
    github_token = env_or_arg("GITHUB_TOKEN", args.github_token)
    if not github_token:
        raise SystemExit("Missing GITHUB_TOKEN")

    repos = fetch_github_repos(args.github_user, github_token)
    summary = {"created": [], "updated": [], "skipped": []}

    for repo in repos:
        full_name = repo["full_name"]
        hooks = list_repo_hooks(full_name, github_token)
        existing = next((hook for hook in hooks if (hook.get("config") or {}).get("url") == args.delivery_url), None)
        if existing:
            action = update_repo_hook(
                full_name,
                int(existing["id"]),
                github_token,
                args.delivery_url,
                args.webhook_secret,
                args.events,
            )
            summary[action].append(full_name)
            continue
        action = create_repo_hook(full_name, github_token, args.delivery_url, args.webhook_secret, args.events)
        summary[action].append(full_name)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
