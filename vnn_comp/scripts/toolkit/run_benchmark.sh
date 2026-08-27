#!/bin/sh
# Put one benchmark on the node and start the tool over its instances.
# (Now supports both AWS remote execution and Local Docker execution)

set -eu

LOGFILE="$(mktemp)"
exec >"$LOGFILE" 2>&1

script_here="$(dirname "$0")"

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

# ---------------------------------------------------------
# Check if the IP belongs to a local Docker network (172.*, 10.*, 192.168.*, 127.*)
# ---------------------------------------------------------
case "$benchmark_ip" in
    127.*|172.*|10.*|192.168.*|localhost)
        IS_LOCAL=1
        ;;
    *)
        IS_LOCAL=0
        ;;
esac

# ---------------------------------------------------------
# LOCAL EXECUTION MODE
# ---------------------------------------------------------
if [ $IS_LOCAL -eq 1 ]; then
    # We are running locally. No need to scp files or use tmux.
    # The benchmark repository is already accessible locally (mounted via volume).
    
    # Export parameters required by run_instances.sh
    export COMP_LABEL="${COMP_LABEL:-VNN-COMP}"
    export ROOT_URL="${ROOT_URL}"
    export task_id="${task_id}"
    export benchmark_name="${benchmark_name}"
    export competition_year="${competition_year}"
    export vnnlib_version="${vnnlib_version}"
    export script_dir="${script_dir}"
    export run_networks="${run_networks}"
    export run_as_root="${run_as_root}"
    export COMP_LOG_LIB="${COMP_LOG_LIB:-/app/vnn_comp/scripts/toolkit/comp_log.sh}"

    # Execute the actual test loop script in the background
    nohup /bin/bash "${script_here}/run_instances.sh" >/dev/null 2>&1 &
    
    echo "[INFO] ${benchmark_name} started locally; the script reports back when it finishes"
    exit 0
fi

# ---------------------------------------------------------
# AWS / REMOTE EXECUTION MODE (Original Code)
# ---------------------------------------------------------
ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
ssh_opts="-o StrictHostKeyChecking=accept-new -i ${ssh_key}"
node="ubuntu@${benchmark_ip}"

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

# Ship the benchmark tree and the loop to the node. It goes where the official scorer
# looks for it (Settings.BENCHMARK_REPOS resolves to ~/vnncomp<year>_benchmarks, and the
# layout below is the one it expects), so the run and its validation read the same files.
dest="/home/ubuntu/vnncomp${competition_year}_benchmarks/benchmarks/${benchmark_name}"
ssh $ssh_opts "$node" "mkdir -p ${dest} /home/ubuntu/logs && rm -rf ${dest}/${vnnlib_version}" \
    || fail "node ${benchmark_ip} unreachable"
scp -r $ssh_opts "$src" "${node}:${dest}/${vnnlib_version}" \
    || fail "copying ${benchmark_name} to the node failed"
scp $ssh_opts "${script_here}/run_instances.sh" "${node}:/home/ubuntu/run_instances.sh" \
    || fail "copying run_instances.sh to the node failed"
scp $ssh_opts "${COMP_LOG_LIB}" "${node}:/home/ubuntu/comp_log.sh" \
    || fail "copying the logging helpers to the node failed"

ssh $ssh_opts "$node" \
    "chmod +x /home/ubuntu/run_instances.sh
     tmux kill-session -t measurements 2>/dev/null
     rm -f /home/ubuntu/measurement.pgid
     tmux new-session -d -s measurements \
        'COMP_LABEL=\"${COMP_LABEL:-VNN-COMP}\" ROOT_URL=${ROOT_URL} task_id=${task_id} benchmark_name=${benchmark_name} competition_year=${competition_year} vnnlib_version=${vnnlib_version} script_dir=${script_dir} run_networks=${run_networks} run_as_root=${run_as_root} /bin/bash /home/ubuntu/run_instances.sh'" \
    || fail "starting the run on the node failed"

echo "[INFO] ${benchmark_name} started on ${benchmark_ip}; the node reports back when it finishes"