# Storage Profile: KU Leuven/UHasselt Tier-2

Sources:

- https://docs.vscentrum.be/leuven/tier2_hardware.html
- https://docs.vscentrum.be/leuven/tier2_hardware/storage.html

## Filesystem Guidance

- Use SCRATCH filesystems for jobs with parallel I/O or heavy temporary I/O.
- Do not run parallel I/O workloads from `VSC_HOME` or `VSC_DATA`; these are
  NFS-mounted and intended for home/data storage, not high-throughput parallel
  job I/O.
- Use project/staging storage for shared project data and persistent datasets
  where appropriate.
- Copy important output from scratch to persistent storage when the job is
  complete.

## Mindwell

- The new SCRATCH filesystem is available as an IBM Storage Scale filesystem.
- IBM Storage Scale is the current name for GPFS, so users may also see or
  recognize this as the GPFS scratch filesystem.
- Capacity: 5.8 PB.
- Network: connected over Infiniband NDR.
- Existing Lustre data remains accessible over an Infiniband HDR-100 network.

## wICE

- Compute nodes are connected to the Lustre parallel filesystem over
  Infiniband HDR-100.
- H100 and huge-memory nodes communicate with each other over Ethernet rather
  than a high-performance interconnect; consider this for distributed jobs and
  parallel I/O placement.
