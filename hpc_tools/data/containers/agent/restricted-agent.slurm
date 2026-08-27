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
agent_image=/path/to/restricted-agent.sif

# Replace the final command with the site's non-interactive agent invocation.
# The image must configure its MCP client to execute hpc-mcp-relay.
hpc-agent-launch \
    --manifest "$manifest" \
    --ledger "$ledger" \
    --profile example \
    --agent-image "$agent_image" \
    -- your-agent --non-interactive
