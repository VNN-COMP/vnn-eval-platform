#!/bin/sh
# Set up a benchmark's generation environment on the node, then report back.
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

script_payload="/tmp/setup_benchmark_${task_id}_payload.sh"
remote_script_path="${BASE_DIR}/setup_benchmark_${task_id}.sh"
remote_log_path="${BASE_DIR}/logs/generate_setup.log"

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
log_stage 'Start — setting up generator'
set -x

finish() {  # \$1 = success|failure — close the stage with a banner, then report
    set +x
    if [ "\$1" = success ]; then log_stage 'End — generator ready'; else log_stage 'End — setup FAILED'; fi
    report "\$1"
}

ensure_uv() {
    command -v curl >/dev/null 2>&1 || { sudo apt-get update && sudo apt-get install -y curl; }
    export PATH="\$HOME/.local/bin:\$PATH"
    command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="\$HOME/.local/bin:\$PATH"
    command -v uv >/dev/null 2>&1 || { echo '[ERROR] uv unavailable'; exit 1; }
}

report() {  # success|failure — POST the log tail so the error is captured even after teardown
    tail -c 200000 ${remote_log_path} > /tmp/setup_${task_id}.tail 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 --data-binary @/tmp/setup_${task_id}.tail ${ROOT_URL}/update/${task_id}/\$1 || true
    return 0
}

rm -rf benchmark \\
    && git clone ${repository} benchmark \\
    && if [ -n "${hash}" ]; then git -C benchmark checkout ${hash}; fi \\
    && cd benchmark/${script_dir} \\
    && ensure_uv \\
    && VENV=${BASE_DIR}/.venvs/gen-${benchmark_id} \\
    && rm -rf \${VENV} && mkdir -p ${BASE_DIR}/.venvs \\
    && if [ -f requirements.txt ]; then \\
        uv venv --seed \${VENV} \\
        && \${VENV}/bin/python -m pip install --upgrade pip \\
        && \${VENV}/bin/python -m pip install -r requirements.txt; \\
    else \\
        echo '[INFO] no requirements.txt; installing legacy baseline deps on Python 3.9'; \\
        uv venv --python 3.9 --seed \${VENV} \\
        && \${VENV}/bin/python -m pip install --upgrade pip "setuptools<66" wheel \\
        && \${VENV}/bin/python -m pip install \\
            matplotlib==3.5.1 mxnet==1.9.1 numpy==1.23 onnx==1.14.0 onnxruntime==1.15.0 \\
            opencv-python==4.7.0.72 pandas==2.0.2 protobuf==4.23.2 scipy==1.10.1 \\
            skl2onnx==1.14.1 tensorflow==2.8.0 torch==1.10.2 torchvision==0.11.3; \\
    fi \\
    && finish success \\
    || finish failure
EOF

if [ $IS_LOCAL -eq 1 ]; then
    # ---------------------------------------------------------
    # LOCAL EXECUTION MODE
    # ---------------------------------------------------------
    chmod +x "${script_payload}"
    # Run in background via nohup
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
         tmux kill-session -t generate_setup 2>/dev/null; \
         tmux new-session -d -s generate_setup /bin/bash ${remote_script_path}"
    
    # Clean up the local payload copy as it's now on the remote node
    rm -f "${script_payload}"
fi