#!/bin/sh
# Generate a benchmark's instances on the node, then report back.
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

script_here="$(dirname "$0")"
script_payload="/tmp/generate_benchmark_${task_id}_payload.sh"
remote_script_path="${BASE_DIR}/generate_benchmark_${task_id}.sh"
remote_log_path="${BASE_DIR}/logs/generate.log"

if [ $IS_LOCAL -eq 1 ]; then
    comp_log_path="${COMP_LOG_LIB}"
    normalize_script_path="${script_here}/normalize_instances.py"
else
    comp_log_path="${BASE_DIR}/comp_log.sh"
    normalize_script_path="${BASE_DIR}/normalize_instances.py"
fi

# Create the payload script locally first
cat > "${script_payload}" <<EOF
#!/bin/bash
export COMP_LABEL="${COMP_LABEL:-VNN-COMP}"
. ${comp_log_path}
cd ${BASE_DIR} || exit 1
mkdir -p logs
exec > >(tee ${remote_log_path}) 2>&1
log_stage 'Start — generating instances'
set -x

finish() {  # \$1 = success|failure — close the stage with a banner, then report
    set +x
    if [ "\$1" = success ]; then log_stage 'End — instances generated'; else log_stage 'End — generation FAILED'; fi
    report "\$1"
}

report() {  # success|failure — POST the log tail so the error is captured even after teardown
    tail -c 200000 ${remote_log_path} > /tmp/gen_${task_id}.tail 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 --data-binary @/tmp/gen_${task_id}.tail ${ROOT_URL}/update/${task_id}/\$1 || true
    return 0
}

VENV=${BASE_DIR}/.venvs/gen-${benchmark_id}
cd benchmark/${script_dir} \\
    && \${VENV}/bin/python generate_properties.py ${seed} \\
    && if [ ! -d ${vnnlib_dir} ] && [ -d generated_vnnlib ]; then mv generated_vnnlib ${vnnlib_dir}; fi \\
    && python3 ${normalize_script_path} ${csv_file} ${onnx_dir} ${vnnlib_dir} \\
    && (ls ${vnnlib_dir}/*.vnnlib || ls ${vnnlib_dir}/*/*.vnnlib) \\
    && ls ${csv_file} \\
    && finish success \\
    || finish failure
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
    
    scp -o StrictHostKeyChecking=accept-new -i "${ssh_key}" \
        "${script_here}/normalize_instances.py" "${COMP_LOG_LIB}" "ubuntu@${benchmark_ip}:${BASE_DIR}/"
    ssh -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "ubuntu@${benchmark_ip}" \
        "mv ${BASE_DIR}/log.sh ${BASE_DIR}/comp_log.sh 2>/dev/null || true"
        
    scp -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "${script_payload}" "ubuntu@${benchmark_ip}:${remote_script_path}"
    
    ssh -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "ubuntu@${benchmark_ip}" \
        "chmod +x ${remote_script_path}; \
         tmux kill-session -t generation 2>/dev/null; \
         tmux new-session -d -s generation /bin/bash ${remote_script_path}"
         
    # Clean up local copy
    rm -f "${script_payload}"
fi