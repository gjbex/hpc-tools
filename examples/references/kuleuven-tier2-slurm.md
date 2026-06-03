# Slurm Profile: KU Leuven/UHasselt Tier-2

Source: https://docs.vscentrum.be/leuven/slurm_specifics.html

## Job Script Policy

- Use `#!/bin/bash -l` for batch scripts.
- Include `#SBATCH --account=<account>` because jobs require compute credits.
- Include `#SBATCH --clusters=<cluster>` when submitting jobs.
- Choose partitions from the hardware profile and target cluster.

## Credit Checks

Use:

```bash
hpc balance
hpc statement --account <account>
hpc statement --account <account> --start <YYYY-mm-dd> --end <YYYY-mm-dd>
```

Check available credits before writing or submitting jobs that request an
account.
