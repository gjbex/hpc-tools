# Slurm Partition Discovery Report

This report records live Slurm limits and hardware context for one partition.
Reuse it by replacing the values in the report section and rerunning the
commands in the refresh section.

## Report: wice batch_icelake

Generated from live Slurm queries on 2026-06-04.

### Partition Limits

| Property | Value |
|---|---:|
| Cluster | `wice` |
| Partition | `batch_icelake` |
| State | `UP` |
| Available | `up` |
| Default job time | `01:00:00` |
| Maximum walltime | `3-00:00:00` |
| Partition-level max nodes per job | `UNLIMITED` |
| Practical partition node ceiling | `172` nodes |
| Total CPUs | `12384` |
| CPUs per node | `72` |
| Default memory per CPU | `3400 MB` |
| Maximum memory per CPU | `3400 MB` |
| Slurm memory per node | `248800 MB` |
| GRES/GPU | none |
| Oversubscribe | `NO` |
| Partition QoS | `normal` |
| Default partition | `NO` |

`MaxNodes=UNLIMITED` means Slurm does not set a lower partition-level node cap
for a single job. The practical ceiling is still bounded by `TotalNodes`,
current availability, account policy, QoS, reservations, and fair-share policy.

### Submit and Array Limits

| Limit | Value | Source |
|---|---:|---|
| Per-user submitted jobs for QoS `normal` | `500` | `MaxSubmitJobsPU` |
| Max array size | `1001` | `MaxArraySize` |
| Largest simple zero-based array | `--array=0-1000` | inferred from `MaxArraySize` |
| Max job count in controller | `10000` | `MaxJobCount` |
| Max tasks per node | `512` | `MaxTasksPerNode` |

The array-size limit is a Slurm controller setting, not a partition field.
Submit limits can be counted differently for array jobs and array tasks on
different sites, so keep the QoS submit limit separate from `MaxArraySize`.

### Hardware Context

| Property | Value |
|---|---:|
| Node class | wICE thin CPU, Ice Lake |
| Nodes in class | `172` |
| CPU model | `2 x Intel Xeon Platinum 8360Y` |
| Cores per socket | `36` |
| Sockets per node | `2` |
| Hardware threads per core | `1` |
| NUMA nodes | `2` |
| Memory | about `256 GiB` physical, `248800 MB` Slurm allocatable |
| Local scratch | about `600 GB` usable on a `960 GB` SSD |

Probe output from an allocated `batch_icelake` node confirmed 72 CPUs, two NUMA
domains, about 251 GiB visible memory, and a 600 GB `/local_scratch` logical
volume. Treat probe output as a sample of one allocated node, not a guarantee
that every node is identical in every operational detail.

## Refresh Commands

Set these placeholders before rerunning the commands:

- `<profile>`: hpc-tools profile name, or omit `--profile` for the configured default.
- `<cluster>`: Slurm cluster name.
- `<partition>`: Slurm partition name.
- `<qos>`: QoS attached to the partition, often from `scontrol show partition`.

Partition limits:

```bash
hpc --profile <profile> run 'scontrol -M <cluster> show partition <partition>'
hpc --profile <profile> run 'sinfo -M <cluster> -p <partition> -o "%P|%a|%l|%D|%N"'
hpc --profile <profile> run 'sinfo -M <cluster> -p <partition> -N -o "%N|%c|%m|%G|%t" | sed -n "1,12p"'
```

QoS and association limits:

```bash
hpc --profile <profile> run 'sacctmgr -n -P show qos <qos> format=Name,MaxJobsPU,MaxSubmitJobsPU,MaxTRESPU,GrpJobs,GrpSubmitJobs,GrpTRES,MaxWall'
hpc --profile <profile> run 'sacctmgr -n -P show assoc where cluster=<cluster> user=$USER format=Cluster,Account,User,Partition,QOS,DefaultQOS,MaxJobs,MaxSubmitJobs,MaxTRES,GrpJobs,GrpSubmitJobs,GrpTRES'
hpc --profile <profile> run 'sacctmgr -n -P show assoc where cluster=<cluster> user=$USER partition=<partition> format=Cluster,Account,User,Partition,QOS,DefaultQOS,MaxJobs,MaxSubmitJobs,MaxTRES,GrpJobs,GrpSubmitJobs,GrpTRES'
```

Controller-wide array limits:

```bash
hpc --profile <profile> run 'scontrol -M <cluster> show config | grep -Ei "MaxArraySize|MaxJobCount|MaxSubmitJobs|MaxTasksPerNode|SchedulerParameters"'
```

Hardware probe, when documentation or Slurm node fields are not enough:

```bash
hpc --profile <profile> submit --test-only hardware-probe.slurm --directory <remote-dir>
hpc --profile <profile> submit hardware-probe.slurm --directory <remote-dir>
```

The probe writes `hardware-probe-<host>-<jobid>` under the submission directory
unless `HPC_PROBE_OUTPUT_DIR` is set.

## Interpretation Checklist

- Separate partition limits from QoS, account, and user association limits.
- Treat empty `sacctmgr` fields as no explicit limit in that field, not as zero.
- Report `MaxNodes=UNLIMITED` together with `TotalNodes`.
- Report `MaxArraySize=N` as allowing up to `N` array index values; for
  zero-based arrays that is normally `--array=0-<N-1>`.
- Distinguish Slurm allocatable memory from physical memory reported by a probe.
- State whether each hardware claim came from documentation, Slurm, or an
  allocated-node probe.
