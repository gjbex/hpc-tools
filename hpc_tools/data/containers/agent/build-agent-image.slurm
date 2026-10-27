#!/bin/bash -l
#SBATCH --job-name=build-restricted-agent
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --time=01:00:00
#SBATCH --output=build-restricted-agent-%j.out
#SBATCH --error=build-restricted-agent-%j.err
# Add site-approved account, cluster, partition, QoS, memory, and module lines.

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?This build must run in a Slurm allocation}"
: "${SLURM_TMPDIR:?Select a private per-job build root for this site}"

# These three paths are site inputs. Keep the cache in project/scratch storage,
# not in Git or a home directory. The durable directory must already exist.
bundle_directory=/path/to/reviewed/restricted-codex-build
cache_directory=/path/to/private/project-or-scratch/apptainer-cache
durable_directory=/path/to/durable/project/images
output_basename=restricted-codex-0.150.1-node-22.16.0

command -v apptainer >/dev/null
test -f "${bundle_directory}/Apptainer.def"
test -d "$durable_directory"
test -w "$durable_directory"
[[ "$output_basename" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]

mkdir -p "$cache_directory"
chmod 0700 "$cache_directory"
test "$(stat -c %u "$cache_directory")" -eq "$UID"
test "$(stat -c %a "$cache_directory")" = 700
export APPTAINER_CACHEDIR="$cache_directory"

build_directory="${SLURM_TMPDIR}/hpc-tools-agent-image"
mkdir -m 0700 "$build_directory"
staged_sif="${build_directory}/${output_basename}.sif"

(
    cd "$bundle_directory"
    apptainer build --fakeroot "$staged_sif" Apptainer.def
)
apptainer test "$staged_sif"

sif_sha256=$(sha256sum "$staged_sif" | awk '{print $1}')
[[ "$sif_sha256" =~ ^[0-9a-f]{64}$ ]]

destination_sif="${durable_directory}/${output_basename}.sif"
destination_checksum="${destination_sif}.sha256"
if [[ -e "$destination_sif" || -e "$destination_checksum" ]]; then
    echo "Refusing to replace an existing durable image or checksum" >&2
    exit 1
fi

temporary_sif="${durable_directory}/.${output_basename}.${SLURM_JOB_ID}.sif.partial"
temporary_checksum="${temporary_sif}.sha256"
published_sif=false
published_checksum=false
cleanup() {
    if [[ "$published_sif" = true ]]; then
        rm -f -- "$destination_sif"
    fi
    if [[ "$published_checksum" = true ]]; then
        rm -f -- "$destination_checksum"
    fi
    rm -f -- "$temporary_sif" "$temporary_checksum"
}
trap cleanup EXIT

install -m 0444 "$staged_sif" "$temporary_sif"
printf '%s  %s\n' "$sif_sha256" "$(basename "$destination_sif")" \
    >"$temporary_checksum"
chmod 0444 "$temporary_checksum"

# Hard links provide no-replace publication on the durable filesystem. The
# cleanup trap removes either durable link if the pair cannot be completed.
ln "$temporary_checksum" "$destination_checksum"
published_checksum=true
ln "$temporary_sif" "$destination_sif"
published_sif=true
published_sif=false
published_checksum=false
cleanup
trap - EXIT

printf 'SIF: %s\nSHA-256: %s\n' "$destination_sif" "$sif_sha256"
