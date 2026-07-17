#!/bin/sh
# Clone a submitted tool onto the node and run its install_tool.sh, then report back.
#
# Per the VNN-COMP rules a tool ships install_tool.sh (once per node) plus
# prepare_instance.sh / run_instance.sh (per instance, driven later by
# run_benchmark.sh) under ${script_dir}. All three must exist, so this fails fast
# here rather than midway through a benchmark. The remote script POSTs the log tail
# to ${ROOT_URL}/update/${task_id}/success|failure, so the error is captured in the
# DB even after the node is torn down.
#
# Params (env, from the step handler): benchmark_ip task_id repository hash
# script_dir run_as_root. ROOT_URL comes from the backend environment.
# NODE_SSH_KEY locates the node key.
set -eu

ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
remote_script_path="/home/ubuntu/install_tool_${task_id}.sh"
remote_log_path="/home/ubuntu/logs/install.log"

if [ "${run_as_root}" = "true" ]; then sudo="sudo -E"; else sudo=""; fi

ssh -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "ubuntu@${benchmark_ip}" \
    "cat > ${remote_script_path} <<'REMOTE_SCRIPT'
#!/bin/bash
cd /home/ubuntu || exit 1
mkdir -p logs
exec > >(tee ${remote_log_path}) 2>&1
set -x
echo '[INFO] toolkit installation started'

report() {  # success|failure — POST the log tail so the error survives node teardown
    tail -c 200000 ${remote_log_path} > /tmp/install_${task_id}.tail 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 --data-binary @/tmp/install_${task_id}.tail ${ROOT_URL}/update/${task_id}/\$1 || true
    return 0
}

# Tools built against a conda base image (the AWS AMIs ship one) expect it on PATH.
if [ -f /home/ubuntu/anaconda3/etc/profile.d/conda.sh ]; then
    . /home/ubuntu/anaconda3/etc/profile.d/conda.sh
else
    export PATH=\"/home/ubuntu/anaconda3/bin:\$PATH\"
fi

rm -rf toolkit \
    && git clone ${repository} toolkit \
    && if [ -n \"${hash}\" ]; then git -C toolkit checkout ${hash}; fi \
    && cd toolkit/${script_dir} \
    && ls install_tool.sh prepare_instance.sh run_instance.sh \
    && chmod +x install_tool.sh prepare_instance.sh run_instance.sh \
    && ${sudo} env SHELLOPTS=xtrace /bin/bash install_tool.sh v1 \
    && report success \
    || report failure
REMOTE_SCRIPT
chmod +x ${remote_script_path}
tmux kill-session -t installation 2>/dev/null
tmux new-session -d -s installation /bin/bash ${remote_script_path}"
