# VNN-COMP

The submission and evaluation platform for **VNN-COMP**, the international competition for neural
network verification. Submit a verification tool or a benchmark; the platform provisions a worker,
runs it, collects logs, and scores the results. Built on the shared
[core evaluation platform](https://github.com/TUMcps/core-eval-platform).

## Requirements

- Docker + Docker Compose (Docker Desktop on macOS/Windows).
- Git.

## Getting started

```bash
git clone --recurse-submodules https://github.com/VNN-COMP/vnn-eval-platform.git
cd vnn-eval-platform && docker compose up --build
```

- Frontend: <http://localhost:5173>
- Public URL (optional): `docker compose logs cloudflared | grep trycloudflare`

The **first account you sign up becomes the admin**; later signups start disabled until an admin
enables them.

## Contributing

Developing the platform (tests, updating the core engine, architecture) is covered in
[CONTRIBUTING.md](CONTRIBUTING.md).
