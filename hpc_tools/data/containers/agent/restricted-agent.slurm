#!/bin/bash
#SBATCH --job-name=restricted-agent
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=04:00:00
#SBATCH --output=restricted-agent-%j.out
#SBATCH --error=restricted-agent-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?This launcher must run in a Slurm allocation}"
: "${SLURM_TMPDIR:?The site must provide a private per-job temporary directory}"

manifest=/path/to/protected/delegation.toml
ledger=/path/to/protected/delegations.sqlite3
agent_image=/path/to/restricted-codex.sif
agent_env_file=/path/to/protected/codex.env
prompt_file=/path/to/reviewed-task.md

# codex.env must be mode 0600 and outside every directory bound into the image.
# For programmatic use it normally contains one line: OPENAI_API_KEY=<key>
# Start from the generated task.md and keep the $hpc-delegated-slurm invocation.
hpc-agent-launch \
    --manifest "$manifest" \
    --ledger "$ledger" \
    --profile example \
    --agent-env-file "$agent_env_file" \
    --agent-image "$agent_image" \
    -- codex-agent - < "$prompt_file"
