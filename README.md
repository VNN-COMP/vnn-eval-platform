# vnn-comp

The **VNN-COMP** variant of [comp-eval-platform](../comp-eval-platform). A thin
repo: the `vnn_comp` plugin app + deployment config, depending on the core engine.

The entire variant is:
- `vnn_comp/competition.py` — the six seams (submission spec, `build_steps`,
  `script_root`, `parse_results`, `score`, `presentation`).
- `vnn_comp/steps.py` — the VNN step handlers (create / install / run_benchmark /
  export / pause). Core provides `assign` and `shutdown`.
- `vnn_comp/scripts/` — the node scripts (install_tool.sh, run_benchmark.sh, …).
- `deploy/` — project settings (`ACTIVE_COMPETITION="vnn"`, `INSTALLED_APPS +=
  ["vnn_comp"]`) + `manage.py`.

No core changes: adding a competition is a new package like this one.

## Run the stack (Postgres + backend)

```bash
docker compose up          # backend on http://localhost:8001
```

The backend installs the core engine (`../comp-eval-platform`) and this plugin,
migrates, seeds settings, and serves. Admin at `/admin/`, API under `/api/`.
Configure via env (see `.env.example`).

For `EXECUTION_BACKEND=local_docker`, uncomment the docker-socket mount in
`docker-compose.yml` and vendor the node scripts into `vnn_comp/scripts/` first.

## Without Docker

```bash
pip install -e ../comp-eval-platform -e .
python deploy/manage.py migrate && python deploy/manage.py init_settings
DJANGO_SETTINGS_MODULE=deploy.settings python deploy/manage.py runserver
```

## Test

```bash
docker run --rm -v "<core>:/core" -v "$PWD:/vnn" -w /vnn python:3.11-slim \
  sh -c "pip install -q -e '/core[dev]' -e /vnn && pytest"
```
