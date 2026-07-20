# VNN-COMP

The **VNN-COMP** variant of [comp-eval-platform](https://github.com/TUMcps/core-eval-platform): the `vnn_comp` plugin
app plus its deploy config, depending on the core engine. All the heavy lifting lives in core;
this repo is the VNN-specific seams, step handlers, and node scripts.

## Requirements

- Docker + Docker Compose (Docker Desktop on macOS/Windows). The backend mounts the host Docker
  socket to run worker containers.
- Git.

## Getting started

The core engine is vendored as a git submodule at [`./core`](https://github.com/TUMcps/core-eval-platform),
pinned to a specific commit — one recursive clone brings everything:

```bash
git clone --recurse-submodules https://github.com/VNN-COMP/vnn-eval-platform.git
cd vnn-eval-platform && docker compose up --build
```

(Already have a checkout without `./core`? Run `git submodule update --init`.)

- Frontend: <http://localhost:5173>
- Public URL (optional): `docker compose logs cloudflared | grep trycloudflare`

The backend installs core + this plugin, migrates, seeds settings, and serves. The **first
account you sign up becomes the admin**; later signups start disabled until an admin enables them.

### Updating the pinned core

`./core` is held at one commit for reproducible dev and deploy. Move the pin with the helper,
then commit the change:

```bash
core/scripts/bump-core.sh          # latest core main
core/scripts/bump-core.sh dev      # ...or a branch, tag, or commit
git commit -m "chore: bump core"   # records the new pin
```

## Tests

```bash
docker run --rm -v "$PWD/core:/core" -v "$PWD:/vnn" -w /vnn python:3.11-slim \
  sh -c "pip install -q -e '/core[dev]' -e /vnn && pytest"
```
