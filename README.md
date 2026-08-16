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

To try a submission, start from the examples:

- Benchmark: <https://github.com/VNN-COMP/example_benchmark>
- Tool: <https://github.com/VNN-COMP/example_toolkit>


## Importing Benchmarks

To import all official VNN-COMP 2026 benchmarks into your local installation at once, run:

```bash
docker compose exec backend git clone https://github.com/VNN-COMP/vnncomp2026_benchmarks.git /tmp/benchmarks
docker compose exec backend python deploy/manage.py bulk_import --repo-path /tmp/benchmarks/benchmarks
```
This clones the official benchmark repository and imports all benchmarks into the database. Each benchmark's metadata is also saved as a data.json file next to its README.md, which can be drag-and-dropped into the benchmark submission form to pre-fill the fields.


## Standalone Worker Server

The platform supports running the website and the worker on separate machines — a lightweight VM serves the frontend and schedules jobs, while a heavier machine (e.g. a lab server or GPU node) runs the Docker containers that execute the submissions.

Clone the same repository on both machines, then start each with a single command:

Website server (same as the default setup above):

```bash
docker compose up --build
```

Worker server (on the dedicated worker machine):

```bash
docker compose run --rm backend python deploy/manage.py worker_service --port 9001
```

This starts the worker service on port 9001, which listens for provision and terminate requests from the website server.

Once the worker service is running, register it in one of two ways:

Platform-wide default — go to Admin → Settings, set execution_backend to remote_docker, and enter the worker machine's URL and port.
Per-user override — each user can enter their own worker server URL and port on their Account page. Submissions from that user are then routed to their private worker instead of the platform default.

## Contributing

Developing the platform (tests, updating the core engine, architecture) is covered in
[CONTRIBUTING.md](CONTRIBUTING.md).
