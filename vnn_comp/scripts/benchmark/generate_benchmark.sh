#!/bin/sh
# Generate a benchmark's instances on the node, then report back.
#
# Clones the source git repo @ ${hash}, runs its generator
# (generate_properties.py ${seed}) in an isolated uv/python env, normalizes the
# emitted instances.csv, and — for VNNLIB 1.0 — best-effort converts to VNNLIB 2.0.
# The remote script curls ${ROOT_URL}/update/${task_id}/success|failure.
#
# Params (env, from the step handler): benchmark_ip task_id benchmark_id repository
# hash script_dir onnx_dir vnnlib_dir csv_file vnnlib_version seed.
# ROOT_URL comes from the backend environment. NODE_SSH_KEY locates the node key.
set -eu

ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
script_here="$(dirname "$0")"
remote_script_path="/home/ubuntu/generate_benchmark_${task_id}.sh"
remote_log_path="logs/generate.log"

scp -o StrictHostKeyChecking=accept-new -i "${ssh_key}" \
    "${script_here}/normalize_instances.py" "ubuntu@${benchmark_ip}:/home/ubuntu/"

ssh -o StrictHostKeyChecking=accept-new -i "${ssh_key}" "ubuntu@${benchmark_ip}" \
    "cat > ${remote_script_path} <<'REMOTE_SCRIPT'
#!/bin/bash
cd /home/ubuntu || exit 1
mkdir -p logs
exec > >(tee ${remote_log_path}) 2>&1
set -x
echo '[INFO] benchmark generation started'

ensure_uv() {
    command -v curl >/dev/null 2>&1 || { sudo apt-get update && sudo apt-get install -y curl; }
    export PATH=\"\$HOME/.local/bin:\$PATH\"
    command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH=\"\$HOME/.local/bin:\$PATH\"
    command -v uv >/dev/null 2>&1 || { echo '[ERROR] uv unavailable'; exit 1; }
}

rm -rf benchmark \
    && git clone ${repository} benchmark \
    && if [ -n \"${hash}\" ]; then git -C benchmark checkout ${hash}; fi \
    && cd benchmark/${script_dir} \
    && ensure_uv \
    && VENV=/home/ubuntu/.venvs/gen-${benchmark_id} \
    && rm -rf \${VENV} && mkdir -p /home/ubuntu/.venvs \
    && uv venv --seed \${VENV} \
    && \${VENV}/bin/python -m pip install --upgrade pip \
    && if [ -f requirements.txt ]; then \${VENV}/bin/python -m pip install -r requirements.txt; fi \
    && \${VENV}/bin/python generate_properties.py ${seed} \
    && if [ ! -d ${vnnlib_dir} ] && [ -d generated_vnnlib ]; then mv generated_vnnlib ${vnnlib_dir}; fi \
    && python3 /home/ubuntu/normalize_instances.py ${csv_file} ${onnx_dir} ${vnnlib_dir} \
    && (ls ${vnnlib_dir}/*.vnnlib || ls ${vnnlib_dir}/*/*.vnnlib) \
    && ls ${csv_file} \
    && if [ \"${vnnlib_version}\" = \"1.0\" ]; then \
        echo '[INFO] converting VNNLIB 1.0 -> 2.0 (best-effort)'; \
        \${VENV}/bin/python -m pip install numpy onnx pandas vnnlib >/dev/null 2>&1; \
        rm -rf /home/ubuntu/vnnlib-benchmarks \
        && git clone -b feature/to_vnnlib2 --single-branch --depth 1 https://github.com/dlshriver/vnnlib-benchmarks.git /home/ubuntu/vnnlib-benchmarks \
        && cp /home/ubuntu/vnnlib-benchmarks/to_vnnlib2.py . \
        && rm -rf vnnlib2 \
        && if \${VENV}/bin/python to_vnnlib2.py -o vnnlib2/ \"\$(pwd)/${csv_file}\"; then \
            echo '[INFO] VNNLIB 2.0 conversion ok'; \
        else \
            echo '[WARN] VNNLIB 2.0 conversion failed; keeping only 1.0'; rm -rf vnnlib2; \
        fi; \
    fi \
    && curl --retry 100 --retry-connrefused ${ROOT_URL}/update/${task_id}/success \
    || curl --retry 100 --retry-connrefused ${ROOT_URL}/update/${task_id}/failure
REMOTE_SCRIPT
chmod +x ${remote_script_path}
tmux new-session -d -s generation /bin/bash ${remote_script_path}"
