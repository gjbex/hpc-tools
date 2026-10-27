#!/bin/bash
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

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?This launcher must run in a Slurm allocation}"
: "${SLURM_TMPDIR:?The site must provide a private per-job temporary directory}"

manifest=/path/to/protected/delegation.toml
ledger=/path/to/protected/delegations.sqlite3
config=${HPC_TOOLS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/hpc-tools/config.toml}
agent_image=/path/to/restricted-codex.sif
agent_env_file=/path/to/protected/codex.env
network_env_file=  # Optional: /path/to/protected/network.env
prompt_file=/path/to/reviewed-task.md

# Both environment files must be mode 0600 and outside every bind root.
# codex.env contains exactly one credential: OPENAI_API_KEY or CODEX_ACCESS_TOKEN.
# network.env is optional and accepts only documented proxy and CA variables.
# The reviewed prompt must also be mode 0600 and outside every bind root.
# Start from the generated task.md and keep the $hpc-delegated-slurm invocation.
network_env_args=()
if [[ -n "$network_env_file" ]]; then
    network_env_args=(--network-env-file "$network_env_file")
fi
hpc-agent-launch \
    --manifest "$manifest" \
    --ledger "$ledger" \
    --config "$config" \
    --profile example \
    --agent-env-file "$agent_env_file" \
    "${network_env_args[@]}" \
    --agent-image "$agent_image" \
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
