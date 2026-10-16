# Publishing (maintainers)

## Container image on ghcr.io

`.github/workflows/image.yml` builds the image natively for `linux/amd64` (on
`ubuntu-latest`) and `linux/arm64` (on `ubuntu-24.04-arm`), starts each one and checks
that it serves the UI, runs as the `modbus` user and can write `/data`. With `publish`
it pushes both by digest and joins them into one multi-arch image.

| Called by | When | Tags |
|---|---|---|
| `ci.yml` | every push to `main` that passes all CI jobs | `edge`, `sha-<commit>` |
| `release.yml` | a `v*` tag, after the PyPI upload (see below) | `0.1.0`, `0.1`, `latest` |

Pull requests build and test the image but push nothing. The workflows authenticate
with `GITHUB_TOKEN` (`packages: write`): no secret to set up. The repository's
*Settings → Actions → General → Workflow permissions* must allow it.

### Making the package public

A package pushed for the first time is private. `electrolabopen` is a personal
account, so its packages are under the profile, not under an organization:

1. Open <https://github.com/electrolabopen?tab=packages> and click **modbus-studio**
   (or go straight to
   <https://github.com/users/electrolabopen/packages/container/modbus-studio/settings>).
2. **Package settings** → *Danger Zone* → **Change visibility** → **Public**, and confirm
   with the package name.

The `org.opencontainers.image.source` label in `docker/Dockerfile` links the package to
the repository, so it is listed on the repository page as well.

Pushes that fail between the per-platform push and the merge leave untagged images
behind. They are harmless; delete them from the package page if you like.

## Python package on PyPI

`.github/workflows/package.yml` builds the sdist and the wheel. Both carry the compiled
UI (`npm run build` writes it into `backend/src/modbus_studio/static`) and the license
(`backend/LICENSE`, a copy of `LICENSE`; the build fails if they differ). The wheel is
then installed on Linux, Windows and macOS with Python 3.10 and 3.13, and
[`.github/scripts/package_smoke.py`](../.github/scripts/package_smoke.py) checks that
`modbus-studio --version` works, the server serves the UI and polls the bundled
simulator. CI runs it on every push and pull request.

The PyPI page is [`backend/README.md`](../backend/README.md): links and images there
must be absolute URLs.

Publishing uses PyPI's trusted publishing: no API token is stored anywhere. PyPI trusts
the workflow `release.yml` of `electrolabopen/modbus-studio` running in the GitHub
environment `pypi`. That environment requires the maintainer's approval and only
accepts `v*` tags.

## Releasing a version

1. On `main`, set the version in
   [`backend/src/modbus_studio/__init__.py`](../backend/src/modbus_studio/__init__.py)
   (the only place it is written; `pyproject.toml` reads it), e.g. `0.1.0`.
2. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [0.1.0] - YYYY-MM-DD` and start a
   new empty `## [Unreleased]` above it.
3. Commit, push, and wait for CI to be green on that commit.
4. Tag that commit and push the tag:

   ```bash
   git tag -a v0.1.0 -m "modbus-studio 0.1.0"
   git push origin v0.1.0
   ```

5. `release.yml` checks the tag matches the version and has a CHANGELOG section, builds
   and tests the package, then waits: approve the **pypi** deployment in the run's page
   (*Actions → Release → Review deployments*).
6. After approval it publishes to PyPI, tags the image `0.1.0`, `0.1` and `latest`, and
   creates the GitHub release with the CHANGELOG section and the files.
7. Set the version on `main` to the next development one (e.g. `0.2.0.dev0`).

A PyPI version cannot be uploaded twice, even after deleting it. If something fails
after the PyPI step, fix it and release the next patch version rather than reusing the
tag.
