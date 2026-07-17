#!/bin/sh
# Validate a finished benchmark's counterexamples with the official scorer.
#
# Checks SCORING/ out of the competition's own results repo and runs
# process_results.py over the run's results.csv: a `sat` is only worth anything once
# the code the competition scores with has confirmed the witness. The scorer's verdict
# tallies (its "Overall Summary") land in this step's log, and its per-witness
# *.counterexample.check.json files are left beside the counterexamples for the export.
#
# The scorer runs in its own Python 3.12 venv, never the tool's environment: installing
# its dependencies into the tool's env could change the very thing that was measured.
#
# The measurement is already done by the time this runs, so a scorer that cannot run is
# logged and skipped rather than failing the task — losing a finished run because a venv
# broke would be worse than not having the check (the old harness did the same).
#
# Params (env, from the step handler): benchmark_ip task_id benchmark_name
# run_folder tool_name scoring_repo scoring_ref. ROOT_URL from the backend env; NODE_SSH_KEY locates the key.
set -eu

ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
remote_script_path="/home/ubuntu/check_results_${task_id}.sh"
remote_log_path="/home/ubuntu/logs/check_${benchmark_name}.log"

ssh -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "ubuntu@${benchmark_ip}" \
    "cat > ${remote_script_path} <<'REMOTE_SCRIPT'
#!/bin/bash
cd /home/ubuntu || exit 1
mkdir -p logs
exec > >(tee ${remote_log_path}) 2>&1
set -x
echo '[INFO] validating ${benchmark_name} results with the official scorer'

report() {  # success|failure — POST the log tail so the summary survives node teardown
    tail -c 200000 ${remote_log_path} > /tmp/check_${task_id}.tail 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 --data-binary @/tmp/check_${task_id}.tail ${ROOT_URL}/update/${task_id}/\$1 || true
    return 0
}
skip() {  # the run stands; only its validation is missing
    echo \"[ERROR] \$1\"
    echo '[WARN] skipping validation; the run itself is unaffected'
    report success
    exit 0
}

ensure_uv() {
    command -v curl >/dev/null 2>&1 || { sudo apt-get update && sudo apt-get install -y curl; }
    export PATH=\"\$HOME/.local/bin:\$PATH\"
    command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH=\"\$HOME/.local/bin:\$PATH\"
    command -v uv >/dev/null 2>&1
}

results_csv=/home/ubuntu/logs/results_${benchmark_name}.csv
[ -s \"\${results_csv}\" ] || { echo '[WARN] no results to validate'; report success; exit 0; }

scoring=/home/ubuntu/scoring
rm -rf \${scoring} && mkdir -p \${scoring} && cd \${scoring} \
    && git init -q \
    && git remote add origin ${scoring_repo} \
    && git config core.sparseCheckout true \
    && echo 'SCORING/' >> .git/info/sparse-checkout \
    && git fetch --depth 1 origin ${scoring_ref} \
    && git checkout -q FETCH_HEAD \
    || skip 'could not fetch SCORING/ from ${scoring_repo}'

# The scorer reads the run's folder next to SCORING/, laid out as in the results repo.
run_dir=\${scoring}/${tool_name}/${run_folder}
mkdir -p \${run_dir}
cp \${results_csv} \${run_dir}/results.csv
cp /home/ubuntu/logs/counterexamples/${benchmark_name}/*.counterexample \${run_dir}/ 2>/dev/null \
    || echo '[INFO] no counterexamples in this run to check'
gzip -f \${run_dir}/*.counterexample 2>/dev/null || true

# Keep every cache the scorer writes inside \${scoring}, which we just created as
# ubuntu. A tool installed as root leaves root-owned files under \$HOME/.cache, and
# sharing that cache is what would otherwise make uv/pip fail here with EACCES.
export UV_CACHE_DIR=\${scoring}/.uv-cache
export UV_PYTHON_INSTALL_DIR=\${scoring}/.uv-python
export PIP_CACHE_DIR=\${scoring}/.pip-cache

cd \${scoring}/SCORING || skip 'SCORING/ is missing from the results repo'
ensure_uv || skip 'uv is unavailable'
if command -v python3.12 >/dev/null 2>&1; then
    SCORING_PYTHON=\$(command -v python3.12)
else
    uv python install 3.12 && SCORING_PYTHON=\$(uv python find 3.12)
fi
[ -n \"\${SCORING_PYTHON:-}\" ] || skip 'no Python 3.12 for the scorer'

venv=\${scoring}/.validation-venv
rm -rf \${venv}
uv venv --python \${SCORING_PYTHON} --seed \${venv} || skip 'could not create the scorer venv'
\${venv}/bin/python3 -m pip install --upgrade pip setuptools wheel \
    && \${venv}/bin/python3 -m pip install -r requirements.txt \
    || skip 'could not install the scorer requirements'

# A path relative to SCORING/, never absolute: the scorer reads the tool name out of the
# path's second segment and rebuilds each witness path as ../<tool>/<run folder>/<..>.gz,
# so an absolute path silently makes the tool 'home' and every counterexample missing.
\${venv}/bin/python3 process_results.py \
    --single-benchmark ../${tool_name}/${run_folder}/results.csv \
    || skip 'process_results.py failed'

# Keep each witness's verdict beside its counterexample, so the export ships it.
cp \${run_dir}/*.counterexample.check.json /home/ubuntu/logs/counterexamples/${benchmark_name}/ 2>/dev/null || true
echo '[INFO] validation finished'
report success
REMOTE_SCRIPT
chmod +x ${remote_script_path}
tmux kill-session -t validation 2>/dev/null
tmux new-session -d -s validation /bin/bash ${remote_script_path}"
