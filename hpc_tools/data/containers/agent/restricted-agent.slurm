#!/bin/bash -l
#SBATCH --job-name=restricted-agent
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=04:00:00
#SBATCH --requeue
#SBATCH --signal=B:USR1@600
#SBATCH --open-mode=append
#SBATCH --output=restricted-agent-%j.out
#SBATCH --error=restricted-agent-%j.err

# Site adaptations: add only reviewed directives that the target site needs.
##SBATCH --account=<account>
##SBATCH --clusters=<cluster>
##SBATCH --partition=<partition>
##SBATCH --qos=<qos>
##SBATCH --reservation=<reservation>
##SBATCH --mem=<memory>

set -euo pipefail
umask 077

# Site adaptations: initialize the batch environment and load exact versions.
# module purge
# module load Apptainer/<version>
# module load hpc-tools/<version>

die() {
    printf 'restricted-agent: %s\n' "$*" >&2
    exit 2
}

require_private_file() {
    local path=$1
    local label=$2
    local owner mode
    [[ "$path" = /* ]] || die "$label must be an absolute path: $path"
    [[ -f "$path" && ! -L "$path" ]] || \
        die "$label must be a real regular file: $path"
    owner=$(stat -c %u -- "$path") || die "cannot inspect $label: $path"
    mode=$(stat -c %a -- "$path") || die "cannot inspect $label: $path"
    [[ "$owner" -eq "$UID" && "$mode" = 600 ]] || \
        die "$label must be owned by this user with mode 0600: $path"
}

require_private_directory() {
    local path=$1
    local label=$2
    local owner mode
    [[ "$path" = /* ]] || die "$label must be an absolute path: $path"
    [[ -d "$path" && ! -L "$path" ]] || \
        die "$label must be a real directory: $path"
    owner=$(stat -c %u -- "$path") || die "cannot inspect $label: $path"
    mode=$(stat -c %a -- "$path") || die "cannot inspect $label: $path"
    [[ "$owner" -eq "$UID" && "$mode" = 700 ]] || \
        die "$label must be owned by this user with mode 0700: $path"
}

require_trusted_file() {
    local path=$1
    local label=$2
    local executable=${3:-false}
    local owner mode mode_value
    [[ "$path" = /* ]] || die "$label must be an absolute path: $path"
    [[ -f "$path" && ! -L "$path" ]] || \
        die "$label must be a real regular file: $path"
    owner=$(stat -c %u -- "$path") || die "cannot inspect $label: $path"
    mode=$(stat -c %a -- "$path") || die "cannot inspect $label: $path"
    mode_value=$((8#$mode))
    [[ "$owner" -eq "$UID" || "$owner" -eq 0 ]] || \
        die "$label must be owned by this user or root: $path"
    (( (mode_value & 8#022) == 0 )) || \
        die "$label must not be group- or world-writable: $path"
    if [[ "$executable" = true && ! -x "$path" ]]; then
        die "$label is not executable: $path"
    fi
}

manifest_warning_seconds() {
    awk '
        /^[[:space:]]*\[/ {
            in_lifecycle = ($0 ~ /^[[:space:]]*\[lifecycle\][[:space:]]*(#.*)?$/)
            next
        }
        in_lifecycle && /^[[:space:]]*warning_seconds[[:space:]]*=/ {
            value = $0
            sub(/^[^=]*=/, "", value)
            sub(/#.*/, "", value)
            gsub(/[[:space:]]/, "", value)
            if (value !~ /^[0-9]+$/) {
                exit 3
            }
            found += 1
            result = value
        }
        END {
            if (found != 1) {
                exit 2
            }
            print result
        }
    ' "$1"
}

: "${SLURM_JOB_ID:?This launcher must run in a Slurm allocation}"

profile=example
warning_seconds=600  # Must equal both --signal=...@600 and lifecycle.warning_seconds.
apptainer_path=/usr/bin/apptainer  # Must equal filesystem.apptainer_path.
manifest_template=/path/to/protected/delegation-template.toml
manifest_directory=/path/to/protected/materialized-manifests
manifest_output="${manifest_directory}/delegation-${SLURM_JOB_ID}.toml"
ledger=/path/to/protected/delegations.sqlite3
config=${HPC_TOOLS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/hpc-tools/config.toml}
agent_image=/path/to/restricted-codex.sif
agent_image_sha256=REPLACE_WITH_REVIEWED_LOWERCASE_SHA256
agent_env_file=/path/to/protected/codex.env
network_env_file=  # Optional: /path/to/protected/network.env
prompt_file=/path/to/protected/reviewed-task.md

# Prefer the site-provided private per-job directory. If the site does not set
# SLURM_TMPDIR, replace this empty fallback with an existing owner-only mode-0700
# directory outside every container bind root.
runtime_directory=${SLURM_TMPDIR:-}
# runtime_directory=/path/to/private/runtime-directory

command -v hpc-agent-launch >/dev/null || die "hpc-agent-launch is not in PATH"
require_trusted_file "$apptainer_path" "Apptainer executable" true
require_private_file "$manifest_template" "manifest template"
require_private_directory "$manifest_directory" "manifest directory"
if [[ -e "$manifest_output" ]]; then
    require_private_file "$manifest_output" "materialized manifest"
fi
require_private_directory "${ledger%/*}" "ledger directory"
if [[ -e "$ledger" ]]; then
    require_private_file "$ledger" "delegation ledger"
fi
require_trusted_file "$config" "hpc-tools configuration"
require_trusted_file "$agent_image" "agent image"
[[ "$agent_image_sha256" =~ ^[0-9a-f]{64}$ ]] || \
    die "agent_image_sha256 must be a reviewed lowercase SHA-256 digest"
require_private_file "$agent_env_file" "agent credential file"
if [[ -n "$network_env_file" ]]; then
    require_private_file "$network_env_file" "network environment file"
fi
require_private_file "$prompt_file" "reviewed task"
[[ -n "$runtime_directory" ]] || \
    die "SLURM_TMPDIR is unset; configure runtime_directory explicitly"
require_private_directory "$runtime_directory" "runtime directory"

if ! template_warning_seconds=$(manifest_warning_seconds "$manifest_template"); then
    die "manifest template must contain one numeric lifecycle.warning_seconds"
fi
[[ "$template_warning_seconds" = "$warning_seconds" ]] || \
    die "SBATCH warning ($warning_seconds) must equal lifecycle.warning_seconds ($template_warning_seconds)"

# The launcher repeats canonical path, ownership, permission, bind-overlap,
# digest, and manifest validation. These checks provide earlier job-log errors;
# they do not replace the launcher security boundary.
network_env_args=()
if [[ -n "$network_env_file" ]]; then
    network_env_args=(--network-env-file "$network_env_file")
fi
hpc-agent-launch \
    --manifest-template "$manifest_template" \
    --manifest-output "$manifest_output" \
    --ledger "$ledger" \
    --config "$config" \
    --profile "$profile" \
    --runtime-directory "$runtime_directory" \
    --agent-env-file "$agent_env_file" \
    "${network_env_args[@]}" \
    --agent-image "$agent_image" \
    --agent-image-sha256 "$agent_image_sha256" \
    --prompt-file "$prompt_file" \
    -- codex-agent - &
launcher_pid=$!

forward_requeue() {
    kill -USR1 "$launcher_pid" 2>/dev/null || true
}
forward_termination() {
    kill -TERM "$launcher_pid" 2>/dev/null || true
}
trap forward_requeue USR1
trap forward_termination TERM INT

set +e
while true; do
    wait "$launcher_pid"
    status=$?
    if ! kill -0 "$launcher_pid" 2>/dev/null; then
        break
    fi
done
set -e
exit "$status"
