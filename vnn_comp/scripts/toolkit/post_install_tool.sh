#!/bin/sh
# Run the post-installation script on the node, after install_tool.sh.
#
# Source of the script, in order: the text the submitter typed into the form
# (${post_install_tool}, written to the node, overwriting any repo copy — that is what
# the form field is for), else the post_install_tool.sh the tool repo ships under
# ${script_dir}. Neither is a no-op that still reports success, since most tools need
# nothing here. The remote script POSTs its log tail to
# ${ROOT_URL}/update/${task_id}/success|failure.
#
# Params (env, from the step handler): benchmark_ip task_id script_dir run_as_root
# post_install_tool. ROOT_URL from the backend environment; NODE_SSH_KEY locates the key.
set -eu

ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
node="ubuntu@${benchmark_ip}"
remote_dir="/home/ubuntu/toolkit/${script_dir}"
remote_script_path="/home/ubuntu/post_install_${task_id}.sh"
remote_log_path="/home/ubuntu/logs/post_install.log"

if [ "${run_as_root}" = "true" ]; then sudo="sudo -E"; else sudo=""; fi

# Ship the shared logging helpers so the remote banners match every other stage.
scp -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "${COMP_LOG_LIB}" "${node}:/home/ubuntu/comp_log.sh"

# A submitted script replaces the repo's copy. Strip CRs: the form is a browser textarea.
if [ -n "${post_install_tool}" ]; then
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    printf '%s' "${post_install_tool}" > "$tmp"
    sed -i 's/\r$//' "$tmp"
    scp -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "$tmp" \
        "${node}:${remote_dir}/post_install_tool.sh"
fi

ssh -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "$node" \
    "cat > ${remote_script_path} <<'REMOTE_SCRIPT'
#!/bin/bash
export COMP_LABEL=\"${COMP_LABEL:-VNN-COMP}\"
. /home/ubuntu/comp_log.sh
cd /home/ubuntu || exit 1
mkdir -p logs
exec > >(tee ${remote_log_path}) 2>&1
log_stage 'Start — post-installation'

report() {  # success|failure — POST the log tail so the error survives node teardown
    tail -c 200000 ${remote_log_path} > /tmp/post_install_${task_id}.tail 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 --data-binary @/tmp/post_install_${task_id}.tail ${ROOT_URL}/update/${task_id}/\$1 || true
    return 0
}

if [ ! -f ${remote_dir}/post_install_tool.sh ]; then
    log_info 'no post-installation script for this submission; nothing to do'
    log_stage 'End — post-installation (skipped)'
    report success
    exit 0
fi

# Tools built against a conda base image (the AWS AMIs ship one) expect it on PATH.
if [ -f /home/ubuntu/anaconda3/etc/profile.d/conda.sh ]; then
    . /home/ubuntu/anaconda3/etc/profile.d/conda.sh
else
    export PATH=\"/home/ubuntu/anaconda3/bin:\$PATH\"
fi

log_box_open 'run post_install_tool.sh'
if cd ${remote_dir} && chmod +x post_install_tool.sh; then
    ${sudo} /bin/bash post_install_tool.sh 2>&1 | log_wall
    post_rc=\${PIPESTATUS[0]}
else
    post_rc=1
fi
log_box_close
if [ \"\${post_rc}\" -eq 0 ]; then
    log_stage 'End — post-installation done'
    report success
else
    log_stage 'End — post-installation FAILED'
    report failure
fi
REMOTE_SCRIPT
chmod +x ${remote_script_path}
tmux kill-session -t post_installation 2>/dev/null
tmux new-session -d -s post_installation /bin/bash ${remote_script_path}"
