#!/bin/sh
# Convert a generated benchmark's VNNLIB 1.0 specs to 2.0 on the node, then report back.
#
# Its own pipeline step (only for 1.0 submissions) so the dedicated Python 3.12 venv and
# the pip installs — the slow part — show a live log instead of a silent stretch inside
# generation. Uses to_vnnlib2.py, whose syntax needs Python 3.12. Best-effort: a failed
# conversion is NOT fatal — the benchmark still exports its 1.0 files — so this always
# reports success, logging a warning and dropping any partial vnnlib2/ on failure. The
# repo + generated files are already on the node under /home/ubuntu/benchmark from the
# earlier steps.
#
# Params (env, from the step handler): benchmark_ip task_id script_dir csv_file.
# ROOT_URL comes from the backend environment. NODE_SSH_KEY locates the node key.
set -eu

ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
remote_script_path="/home/ubuntu/convert_vnnlib_${task_id}.sh"
remote_log_path="/home/ubuntu/logs/convert.log"

scp -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "${COMP_LOG_LIB}" "ubuntu@${benchmark_ip}:/home/ubuntu/comp_log.sh"

ssh -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "ubuntu@${benchmark_ip}" \
    "cat > ${remote_script_path} <<'REMOTE_SCRIPT'
#!/bin/bash
export COMP_LABEL=\"${COMP_LABEL:-VNN-COMP}\"
. /home/ubuntu/comp_log.sh
cd /home/ubuntu || exit 1
mkdir -p logs
exec > >(tee ${remote_log_path}) 2>&1
log_stage 'Start — converting VNNLIB 1.0 -> 2.0'
set -x

ensure_uv() {
    export PATH=\"\$HOME/.local/bin:\$PATH\"
    command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH=\"\$HOME/.local/bin:\$PATH\"
    command -v uv >/dev/null 2>&1 || { echo '[ERROR] uv unavailable'; return 1; }
}

report() {  # success|failure — POST the log tail so it is captured even after teardown
    tail -c 200000 ${remote_log_path} > /tmp/convert_${task_id}.tail 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 --data-binary @/tmp/convert_${task_id}.tail ${ROOT_URL}/update/${task_id}/\$1 || true
    return 0
}

convert() {  # returns nonzero on any failure; the caller keeps the run best-effort
    cd /home/ubuntu/benchmark/${script_dir} || return 1
    ensure_uv || return 1
    CONV=/home/ubuntu/.venvs/conv312
    rm -rf \${CONV} && uv venv --python 3.12 --seed \${CONV} || return 1
    \${CONV}/bin/python -m pip install numpy onnx pandas vnnlib || return 1
    rm -rf /home/ubuntu/vnnlib-benchmarks \
        && git clone -b feature/to_vnnlib2 --single-branch --depth 1 https://github.com/dlshriver/vnnlib-benchmarks.git /home/ubuntu/vnnlib-benchmarks || return 1
    cp /home/ubuntu/vnnlib-benchmarks/to_vnnlib2.py . || return 1
    rm -rf vnnlib2
    \${CONV}/bin/python to_vnnlib2.py -o vnnlib2/ \"\$(pwd)/${csv_file}\"
}

if convert; then
    set +x
    log_info 'VNNLIB 2.0 conversion ok'
    log_stage 'End — conversion done'
else
    set +x
    log_info 'VNNLIB 2.0 conversion failed; keeping only 1.0 (best-effort)'
    rm -rf /home/ubuntu/benchmark/${script_dir}/vnnlib2
    log_stage 'End — conversion skipped'
fi
report success
REMOTE_SCRIPT
chmod +x ${remote_script_path}
tmux kill-session -t convert 2>/dev/null
tmux new-session -d -s convert /bin/bash ${remote_script_path}"
