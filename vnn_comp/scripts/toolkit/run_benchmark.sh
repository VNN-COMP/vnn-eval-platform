#!/bin/sh
# Put one benchmark on the node and start the tool over its instances.
#
# A generated benchmark lives in the benchmarks repo (a configured remote, else the
# local repo the benchmark-export step commits to) and never on the node, so this
# copies the tree across first. The per-instance loop itself runs on the node
# (run_instances.sh), which reports to ${ROOT_URL}/update/${task_id}/success|failure;
# only prep failures are reported from here.
#
# Reads the export layout: benchmarks/<name>/<vnnlib_version>/{onnx,vnnlib,instances.csv}
#
# Params (env, from the step handler): benchmark_ip task_id benchmark_name
# vnnlib_version run_networks run_as_root script_dir benchmarks_repo deploy_key
# local_repo. ROOT_URL comes from the backend environment; NODE_SSH_KEY locates the key.
set -eu

# Capture the prep for notify to POST (fire-and-forget; nothing reads our console).
LOGFILE="$(mktemp)"
exec >"$LOGFILE" 2>&1

ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
script_here="$(dirname "$0")"
ssh_opts="-o StrictHostKeyChecking=accept-new -i ${ssh_key}"
node="ubuntu@${benchmark_ip}"

notify() {  # success|failure — report completion to the backend, POSTing the run log
    url="${ROOT_URL}/update/${task_id}/$1"
    curl -fsS --retry 20 --retry-connrefused --data-binary @"$LOGFILE" "$url" 2>/dev/null && return 0
    wget -q -O /dev/null "$url" 2>/dev/null && return 0
    python3 -c "import urllib.request;urllib.request.urlopen('$url')" 2>/dev/null
}
fail() { echo "[ERROR] $1"; notify failure; exit 1; }

ephemeral=""
cleanup() { rm -f "$LOGFILE"; [ -n "$ephemeral" ] && rm -rf "$ephemeral"; }
trap cleanup EXIT

# Source of the generated benchmark: an ephemeral clone of the remote, or the local repo.
if [ -n "${benchmarks_repo}" ]; then
    export GIT_SSH_COMMAND="ssh -i ${deploy_key} -o StrictHostKeyChecking=accept-new"
    ephemeral="$(mktemp -d)"
    git clone --depth 1 "${benchmarks_repo}" "$ephemeral" || fail "cloning the benchmarks repo failed"
    repo_dir="$ephemeral"
else
    repo_dir="${local_repo}"
fi

src="${repo_dir}/benchmarks/${benchmark_name}/${vnnlib_version}"
[ -d "$src" ] || fail "benchmark ${benchmark_name} (vnnlib ${vnnlib_version}) not found at ${src}; has it been generated and exported?"
[ -f "$src/instances.csv" ] || fail "no instances.csv in ${src}"

# Ship the benchmark tree and the loop to the node.
ssh $ssh_opts "$node" "mkdir -p /home/ubuntu/benchmarks /home/ubuntu/logs && rm -rf /home/ubuntu/benchmarks/${benchmark_name}" \
    || fail "node ${benchmark_ip} unreachable"
scp -r $ssh_opts "$src" "${node}:/home/ubuntu/benchmarks/${benchmark_name}" \
    || fail "copying ${benchmark_name} to the node failed"
scp $ssh_opts "${script_here}/run_instances.sh" "${node}:/home/ubuntu/run_instances.sh" \
    || fail "copying run_instances.sh to the node failed"

ssh $ssh_opts "$node" \
    "chmod +x /home/ubuntu/run_instances.sh
     tmux kill-session -t measurements 2>/dev/null
     rm -f /home/ubuntu/measurement.pgid
     tmux new-session -d -s measurements \
        'ROOT_URL=${ROOT_URL} task_id=${task_id} benchmark_name=${benchmark_name} script_dir=${script_dir} run_networks=${run_networks} run_as_root=${run_as_root} /bin/bash /home/ubuntu/run_instances.sh'" \
    || fail "starting the run on the node failed"

echo "[INFO] ${benchmark_name} started on ${benchmark_ip}; the node reports back when it finishes"
