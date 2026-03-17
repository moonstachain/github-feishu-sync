---
name: github-feishu-sync
description: >
  GitHub 仓库与飞书多维表的双向同步，确保代码仓库状态和飞书治理数据一致。
  当需要把 GitHub commit/test 结果同步到飞书、或从飞书数据触发 GitHub 更新时使用。
  当用户说"同步到飞书"、"GitHub 状态更新"、"双向同步"时使用。
  NOT for 单独的 GitHub 操作（用 github-usage-expert）或单独的飞书操作。
---

# GitHub Feishu Sync

Use this skill to take a GitHub account from raw repositories to a continuously updated Feishu Bitable knowledge base.

## Inputs

Collect or infer these fields before running anything:

- GitHub user or owner, default `moonstachain`
- `GITHUB_TOKEN` for live repository enumeration and private repo content scanning
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- optional `FEISHU_BASE_TOKEN`
- optional `GITHUB_WEBHOOK_SECRET`
- Feishu base or target Bitable app
- public webhook delivery URL if realtime sync is required

If `GITHUB_TOKEN` is missing, do not claim private repos can be content-scanned. Fall back to manifest mode only if the user explicitly wants an offline run or already has a manifest.

## Workflow

1. Confirm the target Feishu base and GitHub owner.
   Default to the existing `专家策略库` base unless the user names another base.

2. Run a full sync first.
   Use `scripts/github_skill_pattern_to_feishu.py` to enumerate repos, inspect repository structure, classify pattern types, and upsert rows into Feishu.

3. Validate the Feishu result before talking about realtime.
   Confirm:
   - the master table is `GitHub仓库总表`
   - the child table is `Skill Pattern子表`
   - stable keys remain `完整名称` and `来源仓库`
   - repeated runs update rows rather than append duplicates

4. Use GitHub API mode whenever possible.
   When `GITHUB_TOKEN` is present, prefer live GitHub API collection over any manifest file. This is the only mode that can scan private repos at content level.

5. Switch to single-repo sync for event-driven updates.
   Use `scripts/github_skill_pattern_to_feishu.py --repo-full-name owner/repo` for webhook-triggered refreshes.

6. Deploy realtime only after the base sync is correct.
   Use `scripts/github_feishu_realtime_sync.py` to expose:
   - `GET /health`
   - `POST /github/webhook`

7. Register GitHub webhooks in bulk only after the webhook endpoint is reachable.
   Use `scripts/register_github_repo_webhooks.py --delivery-url https://.../github/webhook`.

8. Report blockers explicitly.
   Typical blockers:
   - missing `GITHUB_TOKEN`
   - missing Feishu app credentials
   - no public webhook URL
   - insufficient GitHub permissions for repo hooks

## Guardrails

- Do not claim realtime sync is active unless the webhook service is reachable from GitHub.
- Do not claim private repo deep scanning without `GITHUB_TOKEN`.
- Do not append blindly in Feishu. Preserve upsert behavior using stable keys.
- Do not auto-delete historical Feishu rows on delete events. The default behavior is to trigger a full rescan.
- Do not broaden this skill into Notion, Feishu Wiki, or YouQuant. This skill only covers GitHub to Feishu.

## Public Interfaces

Run these entrypoints directly from the skill when executing:

- full sync:
  `python3 scripts/github_skill_pattern_to_feishu.py`
- single repo sync:
  `python3 scripts/github_skill_pattern_to_feishu.py --repo-full-name owner/repo`
- realtime webhook service:
  `python3 scripts/github_feishu_realtime_sync.py --host 0.0.0.0 --port 8787`
- bulk webhook registration:
  `python3 scripts/register_github_repo_webhooks.py --delivery-url https://.../github/webhook`

## References

- `references/feishu-bitable-schema.md`: tables, fields, stable keys, and upsert expectations
- `references/github-event-routing.md`: event-to-sync routing rules and realtime behavior
