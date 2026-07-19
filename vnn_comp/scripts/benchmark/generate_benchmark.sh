#!/bin/sh
# Generate a benchmark's instances on the node, then report back.
#
# The environment was prepared by setup_benchmark.sh: the source repo is cloned at
# /home/ubuntu/benchmark and the generator's venv is at /home/ubuntu/.venvs/gen-<id>.
# This runs generate_properties.py ${seed} in that venv, normalizes the emitted
# instances.csv, and checks the outputs exist. VNNLIB 1.0 -> 2.0 conversion is a
# separate step (convert_vnnlib.sh). The remote script POSTs the log tail to
# ${ROOT_URL}/update/${task_id}/success|failure.
#
# Params (env, from the step handler): benchmark_ip task_id benchmark_id script_dir
# onnx_dir vnnlib_dir csv_file seed. ROOT_URL comes from the backend environment.
# NODE_SSH_KEY locates the node key.
set -eu

ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
script_here="$(dirname "$0")"
remote_script_path="/home/ubuntu/generate_benchmark_${task_id}.sh"
remote_log_path="/home/ubuntu/logs/generate.log"

scp -o StrictHostKeyChecking=accept-new -i "${ssh_key}" \
    "${script_here}/normalize_instances.py" "${COMP_LOG_LIB}" "ubuntu@${benchmark_ip}:/home/ubuntu/"
ssh -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "ubuntu@${benchmark_ip}" \
    "mv /home/ubuntu/log.sh /home/ubuntu/comp_log.sh 2>/dev/null || true"

ssh -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "ubuntu@${benchmark_ip}" \
    "cat > ${remote_script_path} <<'REMOTE_SCRIPT'
#!/bin/bash
export COMP_LABEL=\"${COMP_LABEL:-VNN-COMP}\"
. /home/ubuntu/comp_log.sh
cd /home/ubuntu || exit 1
mkdir -p logs
exec > >(tee ${remote_log_path}) 2>&1
log_stage 'Start — generating instances'
set -x

finish() {  # \$1 = success|failure — close the stage with a banner, then report
    set +x
    if [ \"\$1\" = success ]; then log_stage 'End — instances generated'; else log_stage 'End — generation FAILED'; fi
    report \"\$1\"
}

report() {  # success|failure — POST the log tail so the error is captured even after teardown
    tail -c 200000 ${remote_log_path} > /tmp/gen_${task_id}.tail 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 --data-binary @/tmp/gen_${task_id}.tail ${ROOT_URL}/update/${task_id}/\$1 || true
    return 0
}

VENV=/home/ubuntu/.venvs/gen-${benchmark_id}
cd benchmark/${script_dir} \
    && \${VENV}/bin/python generate_properties.py ${seed} \
    && if [ ! -d ${vnnlib_dir} ] && [ -d generated_vnnlib ]; then mv generated_vnnlib ${vnnlib_dir}; fi \
    && python3 /home/ubuntu/normalize_instances.py ${csv_file} ${onnx_dir} ${vnnlib_dir} \
    && (ls ${vnnlib_dir}/*.vnnlib || ls ${vnnlib_dir}/*/*.vnnlib) \
    && ls ${csv_file} \
    && finish success \
    || finish failure
REMOTE_SCRIPT
chmod +x ${remote_script_path}
tmux kill-session -t generation 2>/dev/null
tmux new-session -d -s generation /bin/bash ${remote_script_path}"
