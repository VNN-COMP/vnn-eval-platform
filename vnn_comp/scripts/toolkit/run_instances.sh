#!/bin/bash
# Runs ON THE NODE (scp'd there by run_benchmark.sh, started under tmux).
#
# Loops one benchmark's instances through the tool's script contract and writes
# logs/results_<benchmark>.csv in the official harness's layout,
#
#     category,onnx,vnnlib,prepare_time,result,runtime
#
# with its verdict vocabulary (run_instance_timeout, prepare_instance_error_<rc>,
# error_exit_code_<rc>, no_result_in_file, …). That is what the scorer reads, so
# emitting anything else would make our results unscoreable by the official tooling.
# For VNN-COMP the category is the benchmark name. The rows carry each instance's own
# two paths, so the backend names the case itself (vnn_comp/instances.py) rather than
# keeping a second naming rule in step here.
# Per the VNN-COMP rules:
#   * prepare_instance.sh v1 <category> <onnx> <vnnlib>            capped at 600s
#   * run_instance.sh v1 <category> <onnx> <vnnlib> <out> <timeout> capped at the
#     per-instance timeout from instances.csv
# and a nonzero prepare_instance.sh exit skips the category. For VNN-COMP the
# category is the benchmark name. The tool writes its verdict as the first line of
# <out>; the rest, when sat, is the counterexample.
#
# Params (env, from run_benchmark.sh): task_id benchmark_name script_dir
# run_networks run_as_root ROOT_URL.
set -u

bench_dir="/home/ubuntu/benchmarks/${benchmark_name}"
tool_dir="/home/ubuntu/toolkit/${script_dir}"
results="/home/ubuntu/logs/results_${benchmark_name}.csv"
ce_dir="/home/ubuntu/logs/counterexamples/${benchmark_name}"
log="/home/ubuntu/logs/run_${benchmark_name}.log"

mkdir -p /home/ubuntu/logs "$ce_dir"
exec > >(tee "$log") 2>&1
# tmux runs this pane in its own session, so this bash is the process-group leader
# (PID == PGID) and the orchestrator's per-benchmark cap can group-kill the whole
# run tree (wrapper scripts + verifier) in one shot.
echo $$ > /home/ubuntu/measurement.pgid

if [ "${run_as_root}" = "true" ]; then sudo="sudo -E"; else sudo=""; fi

report() {  # success|failure — POST the log tail so it survives node teardown
    tail -c 200000 "$log" > "/tmp/run_${task_id}.tail" 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 \
        --data-binary "@/tmp/run_${task_id}.tail" "${ROOT_URL}/update/${task_id}/$1" || true
}

# Tools built against a conda base image (the AWS AMIs ship one) expect it on PATH.
if [ -f /home/ubuntu/anaconda3/etc/profile.d/conda.sh ]; then
    . /home/ubuntu/anaconda3/etc/profile.d/conda.sh
else
    export PATH="/home/ubuntu/anaconda3/bin:$PATH"
fi

cd "$bench_dir" || { echo "[ERROR] benchmark not on node: $bench_dir"; report failure; exit 1; }
[ -x "$tool_dir/run_instance.sh" ] || { echo "[ERROR] tool not installed: $tool_dir"; report failure; exit 1; }

# Instance subset; the testing modes mirror the old run_all_categories.sh vocabulary.
select_instances() {
    case "${run_networks}" in
        first)     head -n 1 instances.csv ;;
        different) awk -F, '!seen[$1]++' instances.csv ;;
        random)    shuf -n 10 instances.csv ;;
        *)         cat instances.csv ;;
    esac
}

since() { awk "BEGIN{printf \"%.2f\", $(date +%s.%N) - $1}"; }
record() {  # <prepare_time> <verdict> <runtime>
    echo "${benchmark_name},${onnx},${vnnlib},$1,$2,$3" >> "$results"
}

: > "$results"
count=0
echo "[INFO] running ${benchmark_name} (run_networks=${run_networks})"

while IFS=, read -r onnx vnnlib tmo || [ -n "$onnx" ]; do
    [ -z "${onnx// /}" ] && continue
    tmo="${tmo:-600}"
    name="$(basename "$onnx" .onnx)/$(basename "$vnnlib" .vnnlib)"
    out="/tmp/result_${task_id}.txt"
    rm -f "$out"

    echo "[INFO] preparing ${name}"
    prep_start=$(date +%s.%N)
    prep_rc=0
    timeout 600 $sudo /bin/bash "$tool_dir/prepare_instance.sh" \
        v1 "${benchmark_name}" "$onnx" "$vnnlib" || prep_rc=$?
    prepare_time=$(since "$prep_start")

    if [ "$prep_rc" -ne 0 ]; then
        if [ "$prep_rc" -eq 124 ]; then verdict=prepare_instance_timeout
        else verdict="prepare_instance_error_${prep_rc}"; fi
        # The rules make a failed prepare skip the category, so this is the last row.
        echo "[WARN] ${name} -> ${verdict}; skipping the rest of this category"
        record "$prepare_time" "$verdict" 0
        count=$((count + 1))
        break
    fi

    echo "[INFO] running ${name} (timeout ${tmo}s)"
    run_start=$(date +%s.%N)
    rc=0
    timeout "$tmo" $sudo /bin/bash "$tool_dir/run_instance.sh" \
        v1 "${benchmark_name}" "$onnx" "$vnnlib" "$out" "$tmo" || rc=$?
    runtime=$(since "$run_start")

    if [ "$rc" -eq 124 ]; then
        verdict=run_instance_timeout
    elif [ "$rc" -ne 0 ]; then
        verdict="error_exit_code_${rc}"
    elif [ ! -s "$out" ]; then
        verdict=no_result_in_file
    else
        verdict=$(head -n 1 "$out" | tr -d '\r\n ')
        verdict="${verdict:-no_result_in_file}"
    fi

    echo "[INFO] ${name} -> ${verdict} in ${runtime}s"
    record "$prepare_time" "$verdict" "$runtime"
    # Keep the witness for the scorer to validate; it is the whole point of a sat.
    if [ "$verdict" = "sat" ] || [ "$verdict" = "violated" ]; then
        [ -s "$out" ] && cp "$out" "${ce_dir}/$(basename "$onnx" .onnx)_$(basename "$vnnlib" .vnnlib).counterexample"
    fi
    count=$((count + 1))
done <<EOF
$(select_instances)
EOF

echo "[INFO] finished ${count} instance(s); results in ${results}"
report success
