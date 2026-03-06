# GitHub Event Routing

Use this reference when deciding how GitHub webhook events should trigger sync behavior.

## Endpoints

- health check: `GET /health`
- webhook receiver: `POST /github/webhook`

## Event Routing

- `push`: sync the single repository from the webhook payload
- `create`: sync the single repository from the webhook payload
- `repository`: sync the single repository from the webhook payload
- `public`: sync the single repository from the webhook payload
- `delete`: trigger a full rescan
- `member`: trigger a full rescan
- `membership`: trigger a full rescan
- `ping`: return success without running sync

## Validation Rules

- Reject webhook requests with an invalid `X-Hub-Signature-256` when `GITHUB_WEBHOOK_SECRET` is configured.
- Skip events from repositories outside the configured GitHub owner.
- Do not report realtime as complete until GitHub can reach the deployed webhook endpoint.

## Operational Notes

- Full sync is the first step; webhook sync is layered on top after the base tables are correct.
- Single-repo sync should use `--repo-full-name owner/repo`.
- If the event cannot safely map to a single repo, prefer a full rescan over partial deletion logic.
