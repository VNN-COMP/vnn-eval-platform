#!/bin/sh
# Store one benchmark run's results in a git repo.
#
# Runs on the backend host (like export_benchmark.sh): pulls results.csv and any
# counterexamples off the node and commits them. Default (empty results_repo) -> a
# persistent local repo under local_repo, no external setup. A configured remote is
# cloned/pushed instead; its deploy key stays on the host, never copied to a node.
# The step is reported done via ${ROOT_URL}/update/${task_id}/success|failure.
#
# Layout: <tool>/<benchmark>/results.csv plus *.counterexample.gz.
#
# Params (env, from the step handler): benchmark_ip task_id benchmark_name tool_name
# results_repo deploy_key local_repo. ROOT_URL/NODE_SSH_KEY from the environment.
set -eu

LOGFILE="$(mktemp)"
exec >"$LOGFILE" 2>&1

ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
node="ubuntu@${benchmark_ip}"

notify() {  # success|failure — report completion to the backend, POSTing the run log
    url="${ROOT_URL}/update/${task_id}/$1"
    curl -fsS --retry 20 --retry-connrefused --data-binary @"$LOGFILE" "$url" 2>/dev/null && return 0
    wget -q -O /dev/null "$url" 2>/dev/null && return 0
    python3 -c "import urllib.request;urllib.request.urlopen('$url')" 2>/dev/null
}
fail() { echo "[ERROR] $1"; notify failure; exit 1; }

work="$(mktemp -d)"
ephemeral=""
cleanup() { rm -rf "$work"; rm -f "$LOGFILE"; [ -n "$ephemeral" ] && rm -rf "$ephemeral"; }
trap cleanup EXIT

# Working repo: an ephemeral clone of the remote, or the persistent local repo.
if [ -n "${results_repo}" ]; then
    export GIT_SSH_COMMAND="ssh -i ${deploy_key} -o StrictHostKeyChecking=accept-new"
    ephemeral="$(mktemp -d)"
    repo_dir="$ephemeral"
    git clone "${results_repo}" "$repo_dir" || fail "cloning the results repo failed"
else
    repo_dir="${local_repo}"
    mkdir -p "$repo_dir"
    [ -d "$repo_dir/.git" ] || git init -q "$repo_dir"
fi

# Pull the run's artifacts back from the node.
scp -o StrictHostKeyChecking=accept-new -i "${ssh_key}" \
    "${node}:/home/ubuntu/logs/results_${benchmark_name}.csv" "$work/results.csv" \
    || fail "no results.csv on the node for ${benchmark_name}"
scp -r -o StrictHostKeyChecking=accept-new -i "${ssh_key}" \
    "${node}:/home/ubuntu/logs/counterexamples/${benchmark_name}" "$work/counterexamples" 2>/dev/null \
    || echo "[INFO] no counterexamples for ${benchmark_name}"

cd "$repo_dir"
git config user.name 'VNN-Comp Bot'
git config user.email 'noreply@vnn-comp'

base="${tool_name}/${benchmark_name}"
rm -rf "$base"
mkdir -p "$base"
cp "$work/results.csv" "$base/results.csv" || fail "copying results.csv failed"
if [ -d "$work/counterexamples" ]; then
    cp "$work"/counterexamples/*.counterexample "$base/" 2>/dev/null || true
    gzip -f "$base"/*.counterexample 2>/dev/null || true
fi

git add "$base"
# Nothing staged means an identical re-run; that is a success, not a failure.
if git diff --cached --quiet; then
    echo "[INFO] results unchanged; nothing to commit"
    notify success
    exit 0
fi
git commit -q -m "Results: ${tool_name} on ${benchmark_name}" || fail "commit failed"

# Push only when a remote is configured; rebase-and-retry on non-fast-forward.
if [ -n "${results_repo}" ]; then
    n=0
    until git push; do
        n=$((n + 1)); [ "$n" -ge 20 ] && fail "push rejected"
        git pull --rebase --autostash || fail "rebase failed"
    done
fi
echo "[INFO] exported ${base}"
notify success
