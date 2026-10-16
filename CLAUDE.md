# Notes for Claude Code

## Never without asking first

Do not run destructive commands on Docker or the system without asking the user first.
This machine has volumes, images and containers of **other projects**. That includes:

- `docker system prune`, `docker volume prune`, `docker image prune`, `docker builder prune`
  and any other `prune`;
- `docker volume rm`, `docker rmi`, `docker rm` of anything you did not create yourself in
  this session;
- `docker compose down -v` (it deletes the `modbus-studio-data` workspace and the
  InfluxDB/Grafana/Mosquitto data);
- deleting files outside this repository (the session scratchpad is the exception).

Prefer a separate compose project (`docker compose -p mstest ...`) for tests; stopping
the user's stack is `docker compose down` **without** `-v`, and it must be started again
afterwards (`docker compose --profile influxdb --profile mqtt up -d --build --wait`).

## How work is done here

- One part at a time; the user tests it before the commit. Commit messages:
  `feat: ... (phase N, part M)` with a bulleted body.
- After pushing, check CI (no `gh` here):
  `curl https://api.github.com/repos/electrolabopen/modbus-studio/actions/runs?head_sha=<sha>`
  and `/actions/runs/<id>/jobs`.
- `electrolabopen` is a personal GitHub account, not an organization.

## Checks

```bash
# backend/ (Windows: .venv/Scripts/python -m ...)
ruff check src tests && ruff format --check src tests && mypy src && pytest -q
# frontend/
npm run lint && npm test && npm run build
# workflows
docker run --rm -v "$PWD:/repo:ro" -w /repo rhysd/actionlint:1.7.7
```
