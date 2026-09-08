# Security / disclosure status

This repository is a **private, embargoed security-research workspace**.

Do not make the repository public, mirror its contents, publish proof material, or disclose unpublished findings from it until all of the following are true:

1. the current research campaign is complete enough for reporting;
2. the relevant maintainer/vendor/project has been notified through the appropriate disclosure channel;
3. any requested coordination/embargo period has been respected; and
4. explicit publication permission has been obtained when required.

## Current claim boundary

The memory-safety/security impact is **not yet proven**.

Do not represent the current state as confirmed memory corruption, a final exploit, a CVE, or a final CVSS severity. The strongest runtime claims remain pending real DWC2 hardware evidence.

Current evidence labels remain:

- source teardown/unmap ordering: `SOURCE-PROVEN`;
- R1A real-hardware reachability: `NOT EXECUTED`;
- real `UNMAP_DONE` for a timed-out request: `NOT PROVEN`;
- post-unmap DMA attempt (`D_issue`): `UNKNOWN`;
- completed post-lifetime memory effect (`D_commit`): `UNKNOWN`;
- security-boundary impact and severity: `UNKNOWN` / `UNRESOLVED`.

## Publication rule

When publication eventually becomes permitted, create a dedicated disclosure/publication review first. Do **not** simply flip repository visibility: review the entire history, artifacts, logs, machine identifiers, paths, timestamps, and any third-party/confidential material before producing a public tree.
