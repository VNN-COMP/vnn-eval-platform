#!/bin/sh
# Convert a generated benchmark's VNNLIB 1.0 specs to 2.0 on the node, then report back.
# (Now supports both AWS remote execution and Local Docker execution)
set -eu

# Check if the IP belongs to a local Docker network (172.*, 10.*, 192.168.*, 127.*)
case "$benchmark_ip" in
    127.*|172.*|10.*|192.168.*|localhost)
        IS_LOCAL=1
        BASE_DIR="/app"
        ;;
    *)
        IS_LOCAL=0
        BASE_DIR="/home/ubuntu"
        ;;
esac

script_payload="/tmp/convert_vnnlib_${task_id}_payload.sh"
remote_script_path="${BASE_DIR}/convert_vnnlib_${task_id}.sh"
remote_log_path="${BASE_DIR}/logs/convert.log"

if [ $IS_LOCAL -eq 1 ]; then
    comp_log_path="${COMP_LOG_LIB}"
else
    comp_log_path="${BASE_DIR}/comp_log.sh"
fi

# Create the payload script locally first
cat > "${script_payload}" <<EOF
#!/bin/bash
export COMP_LABEL="${COMP_LABEL:-VNN-COMP}"
. ${comp_log_path}
cd ${BASE_DIR} || exit 1
mkdir -p logs
exec > >(tee ${remote_log_path}) 2>&1
log_stage 'Start — converting VNNLIB 1.0 -> 2.0'
set -x

ensure_uv() {
    export PATH="\$HOME/.local/bin:\$PATH"
    command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="\$HOME/.local/bin:\$PATH"
    command -v uv >/dev/null 2>&1 || { echo '[ERROR] uv unavailable'; return 1; }
}

report() {  # success|failure — POST the log tail so it is captured even after teardown
    tail -c 200000 ${remote_log_path} > /tmp/convert_${task_id}.tail 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 --data-binary @/tmp/convert_${task_id}.tail ${ROOT_URL}/update/${task_id}/\$1 || true
    return 0
}

convert() {  # returns nonzero on any failure; the caller keeps the run best-effort
    cd ${BASE_DIR}/benchmark/${script_dir} || return 1
    ensure_uv || return 1
    CONV=${BASE_DIR}/.venvs/conv312
    rm -rf \${CONV} && uv venv --python 3.12 --seed \${CONV} || return 1
    \${CONV}/bin/python -m pip install numpy onnx pandas vnnlib || return 1
    rm -rf ${BASE_DIR}/vnnlib-benchmarks \\
        && git clone -b feature/to_vnnlib2 --single-branch --depth 1 https://github.com/dlshriver/vnnlib-benchmarks.git ${BASE_DIR}/vnnlib-benchmarks || return 1
    cp ${BASE_DIR}/vnnlib-benchmarks/to_vnnlib2.py . || return 1
    rm -rf vnnlib2
    \${CONV}/bin/python to_vnnlib2.py -o vnnlib2/ "\$(pwd)/${csv_file}"
}

if convert; then
    set +x
    log_info 'VNNLIB 2.0 conversion ok'
    log_stage 'End — conversion done'
else
    set +x
    log_info 'VNNLIB 2.0 conversion failed; keeping only 1.0 (best-effort)'
    rm -rf ${BASE_DIR}/benchmark/${script_dir}/vnnlib2
    log_stage 'End — conversion skipped'
fi
report success
EOF

if [ $IS_LOCAL -eq 1 ]; then
    # ---------------------------------------------------------
    # LOCAL EXECUTION MODE
    # ---------------------------------------------------------
    chmod +x "${script_payload}"
    nohup /bin/bash "${script_payload}" >/dev/null 2>&1 &
else
    # ---------------------------------------------------------
    # REMOTE AWS EXECUTION MODE (Original)
    # ---------------------------------------------------------
    ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
    
    scp -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "${COMP_LOG_LIB}" "ubuntu@${benchmark_ip}:${BASE_DIR}/comp_log.sh"
    scp -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "${script_payload}" "ubuntu@${benchmark_ip}:${remote_script_path}"
    
    ssh -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "ubuntu@${benchmark_ip}" \
        "chmod +x ${remote_script_path}; \
         tmux kill-session -t convert 2>/dev/null; \
         tmux new-session -d -s convert /bin/bash ${remote_script_path}"
         
    # Clean up local copy
    rm -f "${script_payload}"
fi