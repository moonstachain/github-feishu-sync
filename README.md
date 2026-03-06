# GitHub Feishu Sync

## What it is
GitHub Feishu Sync is a Codex skill for scanning GitHub repositories, classifying broad skill patterns, syncing normalized results into Feishu Bitable, and wiring webhook-based realtime updates.

## Who it's for
This repo is for operators who want to maintain a GitHub-to-Feishu knowledge base, keep repository inventories structured inside 多维表, and optionally refresh records automatically after GitHub changes.

## Quick start
```bash
python3 scripts/github_skill_pattern_to_feishu.py
```

## Inputs
- GitHub owner or user, defaulting to `moonstachain`.
- `GITHUB_TOKEN` for live repository enumeration and private-repo content scanning.
- `FEISHU_APP_ID` and `FEISHU_APP_SECRET`.
- Optional `FEISHU_BASE_TOKEN`.
- Optional `GITHUB_WEBHOOK_SECRET`.
- A target Feishu base or bitable app.
- A public webhook delivery URL if realtime sync is required.

## Outputs
- Upserted GitHub repository records in Feishu Bitable.
- Classified skill-pattern rows for downstream curation.
- A realtime webhook service exposing `GET /health` and `POST /github/webhook`.
- Bulk webhook registration capability for repo-level updates.

## Constraints
- Do not claim private-repo deep scanning without `GITHUB_TOKEN`.
- Realtime sync is not active until the webhook service is publicly reachable and GitHub webhooks are registered.
- Repeated syncs must update rows by stable keys rather than append duplicates.
- Delete events should trigger a rescan path, not blind row deletion.

## Example
Run a full GitHub inventory sync into Feishu first, verify that `GitHub仓库总表` and `Skill Pattern子表` are updating correctly, and only then deploy the webhook service for single-repo refreshes on future GitHub events.

## Project structure
- `scripts/`: full sync, single-repo refresh, realtime webhook server, and webhook registration tools.
- `references/`: Feishu schema notes and GitHub event-routing rules.
- `agents/`: Codex interface metadata.

