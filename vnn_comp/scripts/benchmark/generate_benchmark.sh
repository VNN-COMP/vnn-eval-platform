#!/bin/sh
# Generate a benchmark's instances on the node, then report back.
#
# Clones the source git repo @ ${hash}, runs its generator
# (generate_properties.py ${seed}) in an isolated uv/python env — its
# requirements.txt if present, else a legacy baseline dep set on Python 3.9 for
# older benchmarks that ship no requirements — normalizes the
# emitted instances.csv, and — for VNNLIB 1.0 — best-effort converts to VNNLIB 2.0
# (in a dedicated Python 3.12 venv, which to_vnnlib2.py's syntax requires). The
# remote script POSTs the log tail to ${ROOT_URL}/update/${task_id}/success|failure,
# so the error is captured in the DB even after the node is torn down.
#
# Params (env, from the step handler): benchmark_ip task_id benchmark_id repository
# hash script_dir onnx_dir vnnlib_dir csv_file vnnlib_version seed.
# ROOT_URL comes from the backend environment. NODE_SSH_KEY locates the node key.
set -eu

ssh_key="${NODE_SSH_KEY:-$HOME/.ssh/vnncomp.pem}"
script_here="$(dirname "$0")"
remote_script_path="/home/ubuntu/generate_benchmark_${task_id}.sh"
remote_log_path="/home/ubuntu/logs/generate.log"

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

report() {  # success|failure — POST the log tail so the error is captured even after teardown
    tail -c 200000 ${remote_log_path} > /tmp/gen_${task_id}.tail 2>/dev/null || true
    curl --retry 100 --retry-connrefused --max-time 120 --data-binary @/tmp/gen_${task_id}.tail ${ROOT_URL}/update/${task_id}/\$1 || true
    return 0
}

rm -rf benchmark \
    && git clone ${repository} benchmark \
    && if [ -n \"${hash}\" ]; then git -C benchmark checkout ${hash}; fi \
    && cd benchmark/${script_dir} \
    && ensure_uv \
    && VENV=/home/ubuntu/.venvs/gen-${benchmark_id} \
    && rm -rf \${VENV} && mkdir -p /home/ubuntu/.venvs \
    && if [ -f requirements.txt ]; then \
        uv venv --seed \${VENV} \
        && \${VENV}/bin/python -m pip install --upgrade pip \
        && \${VENV}/bin/python -m pip install -r requirements.txt; \
    else \
        echo '[INFO] no requirements.txt; installing legacy baseline deps on Python 3.9'; \
        uv venv --python 3.9 --seed \${VENV} \
        && \${VENV}/bin/python -m pip install --upgrade pip \"setuptools<66\" wheel \
        && \${VENV}/bin/python -m pip install \
            matplotlib==3.5.1 mxnet==1.9.1 numpy==1.23 onnx==1.14.0 onnxruntime==1.15.0 \
            opencv-python==4.7.0.72 pandas==2.0.2 protobuf==4.23.2 scipy==1.10.1 \
            skl2onnx==1.14.1 tensorflow==2.8.0 torch==1.10.2 torchvision==0.11.3; \
    fi \
    && \${VENV}/bin/python generate_properties.py ${seed} \
    && if [ ! -d ${vnnlib_dir} ] && [ -d generated_vnnlib ]; then mv generated_vnnlib ${vnnlib_dir}; fi \
    && python3 /home/ubuntu/normalize_instances.py ${csv_file} ${onnx_dir} ${vnnlib_dir} \
    && (ls ${vnnlib_dir}/*.vnnlib || ls ${vnnlib_dir}/*/*.vnnlib) \
    && ls ${csv_file} \
    && if [ \"${vnnlib_version}\" = \"1.0\" ]; then \
        echo '[INFO] converting VNNLIB 1.0 -> 2.0 (best-effort)'; \
        CONV=/home/ubuntu/.venvs/conv312; \
        rm -rf \${CONV} && uv venv --python 3.12 --seed \${CONV} >/dev/null 2>&1; \
        \${CONV}/bin/python -m pip install numpy onnx pandas vnnlib >/dev/null 2>&1; \
        rm -rf /home/ubuntu/vnnlib-benchmarks \
        && git clone -b feature/to_vnnlib2 --single-branch --depth 1 https://github.com/dlshriver/vnnlib-benchmarks.git /home/ubuntu/vnnlib-benchmarks \
        && cp /home/ubuntu/vnnlib-benchmarks/to_vnnlib2.py . \
        && rm -rf vnnlib2 \
        && if \${CONV}/bin/python to_vnnlib2.py -o vnnlib2/ \"\$(pwd)/${csv_file}\"; then \
            echo '[INFO] VNNLIB 2.0 conversion ok'; \
        else \
            echo '[WARN] VNNLIB 2.0 conversion failed; keeping only 1.0'; rm -rf vnnlib2; \
        fi; \
    fi \
    && report success \
    || report failure
REMOTE_SCRIPT
chmod +x ${remote_script_path}
tmux new-session -d -s generation /bin/bash ${remote_script_path}"
