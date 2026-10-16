# Publishing (maintainers)

## Container image on ghcr.io

`.github/workflows/image.yml` builds the image natively for `linux/amd64` (on
`ubuntu-latest`) and `linux/arm64` (on `ubuntu-24.04-arm`), starts each one and checks
that it serves the UI, runs as the `modbus` user and can write `/data`. With `publish`
it pushes both by digest and joins them into one multi-arch image.

| Called by | When | Tags |
|---|---|---|
| `ci.yml` | every push to `main` that passes all CI jobs | `edge`, `sha-<commit>` |
| `release.yml` | a `v*` tag, after approval of the `pypi` environment | `0.1.0`, `0.1`, `latest` |

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
