#!/bin/bash -l
#SBATCH --job-name=hardware-probe
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --exclusive
#SBATCH --time=00:20:00
#SBATCH --output=%x-%j.out

set -euo pipefail

# Add site-required directives such as --account, --clusters, or --partition
# before submitting on clusters that need them.
# For meaningful Intel MLC results, use an entire node. Keep --exclusive and,
# on sites that enforce CPU cgroups, also add a partition-specific
# --cpus-per-task value equal to the full node core count.
# Intel MLC measurements can take several minutes; increase --time if the node
# is slow or additional probe commands are added.

OUTPUT_ROOT=${HPC_PROBE_OUTPUT_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}
JOB_ID=${SLURM_JOB_ID:-manual}
HOST=$(hostname -s 2>/dev/null || hostname)
OUTPUT_DIR="${OUTPUT_ROOT}/hardware-probe-${HOST}-${JOB_ID}"

mkdir -p "$OUTPUT_DIR"

run_capture() {
    local name=$1
    shift
    {
        echo "$ $*"
        "$@"
    } >"${OUTPUT_DIR}/${name}.txt" 2>&1 || true
}

capture_file() {
    local source=$1
    local destination=$2
    if [[ -r "$source" ]]; then
        cp "$source" "${OUTPUT_DIR}/${destination}"
    fi
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
    echo "cpus_on_node=${SLURM_CPUS_ON_NODE:-}"
    echo "cpus_per_task=${SLURM_CPUS_PER_TASK:-}"
    echo "exclusive=${SLURM_JOB_EXCLUSIVE:-}"
    echo "submit_dir=${SLURM_SUBMIT_DIR:-}"
    echo "scratch_node=${VSC_SCRATCH_NODE:-}"
} >"${OUTPUT_DIR}/summary.env"

run_capture uname uname -a
run_capture hostname hostname -f
run_capture lscpu lscpu
run_capture lscpu-cache lscpu --cache
run_capture numactl-hardware numactl --hardware
run_capture memory free -h
run_capture meminfo cat /proc/meminfo
run_capture cpuinfo cat /proc/cpuinfo
run_capture mounts findmnt
run_capture df df -hT
run_capture lsblk lsblk -o NAME,MODEL,SIZE,TYPE,FSTYPE,MOUNTPOINT
run_capture block-devices bash -lc 'for d in /sys/block/*; do echo "## $d"; cat "$d/device/model" 2>/dev/null || true; cat "$d/queue/rotational" 2>/dev/null || true; cat "$d/size" 2>/dev/null || true; done'
run_capture nvidia-smi nvidia-smi
run_capture rocm-smi rocm-smi
run_capture hwloc lstopo-no-graphics
run_capture intel-mlc mlc
run_capture intel-mlc-bandwidth mlc --bandwidth_matrix
run_capture intel-mlc-latency mlc --latency_matrix

mkdir -p "${OUTPUT_DIR}/cache"
for cpu_cache in /sys/devices/system/cpu/cpu*/cache/index*; do
    [[ -d "$cpu_cache" ]] || continue
    cpu_name=$(basename "$(dirname "$(dirname "$cpu_cache")")")
    index_name=$(basename "$cpu_cache")
    destination="${OUTPUT_DIR}/cache/${cpu_name}-${index_name}.txt"
    {
        echo "path=$cpu_cache"
        for field in level type size coherency_line_size number_of_sets ways_of_associativity shared_cpu_list shared_cpu_map; do
            if [[ -r "${cpu_cache}/${field}" ]]; then
                echo "${field}=$(cat "${cpu_cache}/${field}")"
            fi
        done
    } >"$destination"
done

capture_file /proc/self/status proc-self-status.txt

echo "Hardware probe output written to ${OUTPUT_DIR}"
