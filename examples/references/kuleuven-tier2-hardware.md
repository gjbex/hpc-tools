# Hardware Profile: KU Leuven/UHasselt Tier-2

Source: https://docs.vscentrum.be/leuven/tier2_hardware.html

## Slurm Policy

- Account required: yes
- Cluster flag required for job submission: yes
- Recommended batch shell: `#!/bin/bash -l`
- Accounting commands: `sam-balance`, `sam-statement --account <account>`

## Clusters

### Mindwell

Planned production around mid 2026.

#### Thin CPU: Granite Rapids

- Nodes: 40
- CPUs: 2 x Intel Xeon Platinum 6972P, 96 cores per socket
- Memory: 768 GiB
- Local scratch: 600 GB usable on a 960 GB NVMe drive
- Partitions: `batch_graniterapids`, `batch_graniterapids_long`

#### Big Memory

- Nodes: 10
- CPUs: 2 x Intel Xeon 6972P, 96 cores per socket
- Memory: 1536 GiB
- Local scratch: approximately 3500 GB usable on a 3840 GB NVMe drive
- Partition: `bigmem`

#### GPU: B200

- Nodes: 3
- GPUs: 8 x NVIDIA B200 SXM6 192 GiB per node
- CPUs: 2 x AMD EPYC 9655, 96 cores per socket
- Memory: 1536 GiB
- Local scratch: 600 GB usable on a 960 GB NVMe drive
- Partition: `gpu_b200`

### wICE

#### Thin CPU: Ice Lake

- Nodes: 172
- CPUs: 2 x Intel Xeon Platinum 8360Y, 36 cores per socket
- Memory: 256 GiB
- Local scratch: 600 GB usable on a 960 GB SSD
- Partitions: `batch`, `batch_long`, `batch_icelake`, `batch_icelake_long`

#### Thin CPU: Sapphire Rapids

- Nodes: 68
- CPUs: 2 x Intel Xeon Platinum 8468, 48 cores per socket
- Memory: 256 GiB
- Local scratch: 600 GB usable on a 960 GB SSD
- Partitions: `batch_sapphirerapids`, `batch_sapphirerapids_long`

#### Memory Nodes

- Big memory: 5 nodes, 2048 GiB RAM, partition `bigmem`
- Huge memory: 1 node, 8 TiB RAM, partition `hugemem`

#### GPU

- A100: 4 nodes, 4 x NVIDIA A100 SXM4 80 GiB per node, partitions `gpu`, `gpu_a100`
- H100: 5 nodes, 4 x NVIDIA H100 SXM5 80 GiB per node, partition `gpu_h100`
- Debug: 1 A100 node, partition `gpu_a100_debug`
- Interactive: 4 A100 nodes, partition `interactive`

### Genius

Currently mainly login nodes and most GPU nodes remain in operation.

#### GPU: P100

- Nodes: 14
- GPUs: 4 x NVIDIA P100 SXM2 16 GiB per node
- CPUs: 2 x Xeon Gold 6140, 18 cores per socket
- Memory: 192 GiB
- Local scratch: 200 GB SSD
- Partitions: `gpu_p100`, `gpu_p100_long`, `gpu_p100_debug`

#### GPU: V100

- Nodes: 2
- GPUs: 8 x NVIDIA V100 SXM2 32 GiB per node
- CPUs: 2 x Xeon Gold 6240, 18 cores per socket
- Memory: 768 GiB
- Local scratch: 200 GB SSD
- Partitions: `gpu_v100`, `gpu_v100_long`
