#!/bin/bash
# Runs ON THE NODE (scp'd there by run_benchmark.sh, started under tmux).
# (Now supports both AWS remote execution and Local Docker execution)
#
# Loops one benchmark's instances through the tool's script contract and writes
# logs/results_<benchmark>.csv in the official harness's layout.
set -u

# ---------------------------------------------------------
# LOCAL vs REMOTE EXECUTION SETUP
# ---------------------------------------------------------
if [ -d "/app" ] && [ ! -d "/home/ubuntu/vnncomp${competition_year}_benchmarks" ]; then
    IS_LOCAL=1
    BASE_DIR="/app"
    
    found_csv=$(find /app -type f -name "instances.csv" 2>/dev/null | head -n 1)
    
    if [ -z "$found_csv" ]; then
        echo "ERROR: instances.csv not found anywhere in /app!" >&2
        exit 1
    else
        abs_bench_dir=$(dirname "$found_csv")
        bench_rel="${abs_bench_dir#/app/}"
    fi
else
    IS_LOCAL=0
    BASE_DIR="/home/ubuntu"
    # In remote mode, it uses the standard VNN-COMP path structure
    bench_rel="vnncomp${competition_year}_benchmarks/benchmarks/${benchmark_name}/${vnnlib_version}"
fi

# Everything runs from BASE_DIR with repo-relative paths, so the paths recorded in
# results.csv are the ones the scorer expects.
bench_dir="${BASE_DIR}/${bench_rel}"
tool_dir="${BASE_DIR}/toolkit/${script_dir}"
# Bare, no year: this is the tool's `category` argument.
category="${benchmark_name}"
results="${BASE_DIR}/logs/results_${benchmark_name}.csv"
ce_dir="${BASE_DIR}/logs/counterexamples/${benchmark_name}"
log="${BASE_DIR}/logs/run_${benchmark_name}.log"

mkdir -p "${BASE_DIR}/logs" "$ce_dir"
exec > >(tee "$log") 2>&1

# Source the appropriate logging helpers based on the execution mode
if [ $IS_LOCAL -eq 1 ]; then
    . "${COMP_LOG_LIB}"
else
    . "${BASE_DIR}/comp_log.sh"
fi

# Record the process group so the backend can group-kill the whole run tree if aborted
echo $$ > "${BASE_DIR}/measurement.pgid"

if [ "${run_as_root}" = "true" ]; then sudo="sudo -E"; else sudo=""; fi

report() {  # success|failure — POST the log tail so it survives node teardown
    tail -c 200000 "$log" > "/tmp/run_${task_id}.tail" 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 \
        --data-binary "@/tmp/run_${task_id}.tail" "${ROOT_URL}/update/${task_id}/$1" || true
}

if [ $IS_LOCAL -eq 0 ]; then
    # Tools built against a conda base image (the AWS AMIs ship one) expect it on PATH.
    if [ -f "${BASE_DIR}/anaconda3/etc/profile.d/conda.sh" ]; then
        . "${BASE_DIR}/anaconda3/etc/profile.d/conda.sh"
    else
        export PATH="${BASE_DIR}/anaconda3/bin:$PATH"
    fi
fi

log_superstage "Start — running ${benchmark_name} (run_networks=${run_networks})"
[ -d "$bench_dir" ] || { log_info "ERROR: benchmark not on node: $bench_dir"; report failure; exit 1; }
[ -x "$tool_dir/run_instance.sh" ] || { log_info "ERROR: tool not installed: $tool_dir"; report failure; exit 1; }
cd "${BASE_DIR}" || exit 1

# Instance subset; the testing modes mirror the old run_all_categories.sh vocabulary.
select_instances() {
    case "${run_networks}" in
        first)    head -n 1 "$bench_dir/instances.csv" ;;
        different) awk -F, '!seen[$1]++' "$bench_dir/instances.csv" ;;
        random10)  shuf -n 10 "$bench_dir/instances.csv" ;;
        *)         cat "$bench_dir/instances.csv" ;;
    esac
}

since() { awk "BEGIN{printf \"%.2f\", $(date +%s.%N) - $1}"; }
record() {  # <prepare_time> <verdict> <runtime>
    echo "${category},${onnx_path},${vnnlib_path},$1,$2,$3" >> "$results"
}

: > "$results"
instances="$(select_instances)"
total=$(printf '%s\n' "$instances" | grep -c '[^[:space:]]')
count=0

while IFS=, read -r onnx vnnlib tmo || [ -n "$onnx" ]; do
    [ -z "${onnx// /}" ] && continue
    tmo="${tmo:-600}"
    
    # instances.csv is benchmark-relative; the tool and the scorer both need the paths
    # rooted at BASE_DIR, which is where this runs from.
    onnx_path="${bench_rel}/${onnx}"
    vnnlib_path="${bench_rel}/${vnnlib}"
    name="$(basename "$onnx" .onnx)/$(basename "$vnnlib" .vnnlib)"
    out="/tmp/result_${task_id}.txt"
    rm -f "$out"
    count=$((count + 1))
    log_stage "Running instance ${count}/${total}: ${name}"

    log_box_open "run prepare_instance.sh (timeout 600s)"
    prep_start=$(date +%s.%N)
    timeout 600 $sudo /bin/bash "$tool_dir/prepare_instance.sh" \
        v1 "${category}" "$onnx_path" "$vnnlib_path" 2>&1 | log_wall
    prep_rc=${PIPESTATUS[0]}
    prepare_time=$(since "$prep_start")

    if [ "$prep_rc" -ne 0 ]; then
        if [ "$prep_rc" -eq 124 ]; then verdict=prepare_instance_timeout
        else verdict="prepare_instance_error_${prep_rc}"; fi
        log_box_note "prepare_instance.sh -> ${verdict} in ${prepare_time}s; a failed prepare skips the rest of this category"
        log_box_close
        # The rules make a failed prepare skip the category, so this is the last row.
        record "$prepare_time" "$verdict" 0
        break
    fi
    log_box_note "prepare_instance.sh done in ${prepare_time}s"
    log_box_close

    log_box_open "run run_instance.sh (timeout ${tmo}s)"
    run_start=$(date +%s.%N)
    timeout "$tmo" $sudo /bin/bash "$tool_dir/run_instance.sh" \
        v1 "${category}" "$onnx_path" "$vnnlib_path" "$out" "$tmo" 2>&1 | log_wall
    rc=${PIPESTATUS[0]}
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

    log_box_note "run_instance.sh -> ${verdict} in ${runtime}s"
    log_box_close
    record "$prepare_time" "$verdict" "$runtime"
    
    # Keep the witness for the scorer to validate; it is the whole point of a sat.
    if [ "$verdict" = "sat" ] || [ "$verdict" = "violated" ]; then
        [ -s "$out" ] && cp "$out" "${ce_dir}/$(basename "$onnx" .onnx)_$(basename "$vnnlib" .vnnlib).counterexample"
    fi
done <<EOF
$instances
EOF

log_superstage "End — finished ${count} instance(s); results in ${results}"
report success