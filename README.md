# VNN-COMP

The **VNN-COMP** variant of [comp-eval-platform](https://github.com/TUMcps/core-eval-platform): the `vnn_comp` plugin
app plus its deploy config, depending on the core engine. All the heavy lifting lives in core;
this repo is the VNN-specific seams, step handlers, and node scripts.

## Requirements

- Docker + Docker Compose (Docker Desktop on macOS/Windows). The backend mounts the host Docker
  socket to run worker containers.
- Git.

## Getting started

Clone this repo and the core engine **side by side** under the same parent directory (the compose
file mounts `../comp-eval-platform`):

```bash
git clone https://github.com/TUMcps/core-eval-platform.git   comp-eval-platform
git clone https://github.com/VNN-COMP/vnn-eval-platform.git   vnn-comp-new
cd vnn-comp-new && docker compose up --build
```

- Frontend: <http://localhost:5173>
- Public URL (optional): `docker compose logs cloudflared | grep trycloudflare`

The backend installs core + this plugin, migrates, seeds settings, and serves. The **first
account you sign up becomes the admin**; later signups start disabled until an admin enables them.

## Tests

```bash
docker run --rm -v "../comp-eval-platform:/core" -v "$PWD:/vnn" -w /vnn python:3.11-slim \
  sh -c "pip install -q -e '/core[dev]' -e /vnn && pytest"
```
