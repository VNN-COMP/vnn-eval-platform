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

## Local dev

```bash
pip install -e ../comp-eval-platform -e .
python deploy/manage.py makemigrations && python deploy/manage.py migrate
DJANGO_SETTINGS_MODULE=deploy.settings python deploy/manage.py runserver
```

Configure via env: `DATABASE_URL`, `EXECUTION_BACKEND` (aws|local_docker),
`MAX_PARALLEL_NODES`, `SCHEDULER_AUTOSTART`, `ROOT_URL`.
