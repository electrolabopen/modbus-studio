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

## Tools

Only run the formatters, linters and other tools configured in the project (the ones in
"Checks" below, `package.json` scripts, `pyproject.toml`). Never run others, such as
`npx prettier`, even on a single file: they rewrite files in a style the project does not
use.

## How work is done here

- `main` is protected: never commit or push to it directly. Every change, docs included,
  goes in a branch (`feat/...`, `fix/...`, `docs/...`) and a Pull Request to `main`. The
  user reviews and merges (squash); never merge yourself. Afterwards: `git switch main`,
  `git pull`, and delete the local branch (`git branch -D`, since squash merges are not
  seen as merged; first check `git diff main <branch>` is empty).
- One part at a time; the user tests it before the commit. Commit messages:
  `feat: ... (phase N, part M)` with a bulleted body.
- Use the GitHub CLI (`gh`, logged in by the user) for Pull Requests and CI:
  `gh pr create --base main`, `gh pr checks <n> --watch`, `gh run list --commit <sha>`,
  `gh run view <id>`. Never take git's stored credential (`git credential fill`) to call
  the API; if `gh auth status` says it is not logged in, ask the user to run
  `gh auth login`.
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
