#!/bin/bash -l
#SBATCH --job-name=cuda-device-properties
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus-per-node=1
#SBATCH --time=00:10:00
#SBATCH --output=%x-%j.out

set -euo pipefail

# Add site-required directives such as --account, --clusters, or --partition
# before submitting on clusters that need them. For Mindwell B200, this usually
# means adding --clusters=mindwell, --partition=gpu_b200, and an account.
#
# Override CUDA_DEVICE_PROPERTIES_LOAD_MODULES=0 if the submit environment
# already provides compatible CMake and CUDA tools.
if [[ "${CUDA_DEVICE_PROPERTIES_LOAD_MODULES:-1}" == "1" ]]; then
    module load CMake/3.31.3-GCCcore-14.2.0
    module load CUDA/12.8.0
fi

OUTPUT_ROOT=${CUDA_DEVICE_PROPERTIES_OUTPUT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
JOB_ID=${SLURM_JOB_ID:-manual}
HOST=$(hostname -s 2>/dev/null || hostname)
OUTPUT_DIR="${OUTPUT_ROOT}/cuda-device-properties-${HOST}-${JOB_ID}"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR=${CUDA_DEVICE_PROPERTIES_SOURCE_DIR:-}

if [[ -z "$SOURCE_DIR" ]]; then
    if [[ -f "${SCRIPT_DIR}/cuda/CMakeLists.txt" ]]; then
        SOURCE_DIR="${SCRIPT_DIR}/cuda"
    elif [[ -f "${SLURM_SUBMIT_DIR:-$PWD}/examples/cuda/CMakeLists.txt" ]]; then
        SOURCE_DIR="${SLURM_SUBMIT_DIR:-$PWD}/examples/cuda"
    elif [[ -f "${SCRIPT_DIR}/../cuda/CMakeLists.txt" ]]; then
        SOURCE_DIR="${SCRIPT_DIR}/../cuda"
    else
        echo "Could not find examples/cuda/CMakeLists.txt." >&2
        echo "Set CUDA_DEVICE_PROPERTIES_SOURCE_DIR to the directory containing it." >&2
        exit 1
    fi
fi

BUILD_PARENT=${VSC_SCRATCH_NODE:-${TMPDIR:-/tmp}}
BUILD_DIR="${BUILD_PARENT}/cuda-device-properties-build-${JOB_ID}"

mkdir -p "$OUTPUT_DIR" "$BUILD_DIR"

run_capture() {
    local name=$1
    shift
    {
        echo "$ $*"
        "$@"
    } >"${OUTPUT_DIR}/${name}.txt" 2>&1
}

run_capture_allow_failure() {
    local name=$1
    shift
    {
        echo "$ $*"
        "$@"
    } >"${OUTPUT_DIR}/${name}.txt" 2>&1 || true
}

{
    echo "generated_at=$(date --iso-8601=seconds 2>/dev/null || date)"
    echo "hostname=$(hostname)"
    echo "kernel=$(uname -a)"
    echo "job_id=${SLURM_JOB_ID:-}"
    echo "job_name=${SLURM_JOB_NAME:-}"
    echo "cluster=${SLURM_CLUSTER_NAME:-}"
    echo "partition=${SLURM_JOB_PARTITION:-}"
    echo "node_list=${SLURM_JOB_NODELIST:-}"
    echo "gpus=${SLURM_GPUS:-}"
    echo "gpus_on_node=${SLURM_GPUS_ON_NODE:-}"
    echo "submit_dir=${SLURM_SUBMIT_DIR:-}"
    echo "source_dir=${SOURCE_DIR}"
    echo "build_dir=${BUILD_DIR}"
    echo "scratch_node=${VSC_SCRATCH_NODE:-}"
} >"${OUTPUT_DIR}/summary.env"

run_capture cmake-version cmake --version
run_capture nvcc-version nvcc --version
run_capture_allow_failure nvidia-smi nvidia-smi

run_capture cmake-configure cmake -S "$SOURCE_DIR" -B "$BUILD_DIR"
run_capture cmake-build cmake --build "$BUILD_DIR"

cp "${BUILD_DIR}/device_properties" "${OUTPUT_DIR}/device_properties"
run_capture device-properties "${OUTPUT_DIR}/device_properties"

echo "CUDA device properties output written to ${OUTPUT_DIR}"
