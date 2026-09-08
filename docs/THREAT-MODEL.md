# Threat model and severity boundaries

## Current attacker model

The trigger under study is host-controlled USB teardown against a device operating the DWC2 gadget controller while a legitimate Bulk OUT request is active.

The security significance depends on deployment preconditions that are not yet fully established, including:

- whether the attacker needs local/root privileges on the gadget;
- whether the vulnerable gadget function/configuration is normally reachable;
- whether a physically or logically untrusted USB host can issue the trigger without privileged device-side cooperation;
- whether the effect is reliable across normal configurations.

## Severity ladder

| Runtime result | Interpretation |
|---|---|
| timeout causes protocol/reliability anomaly only | Low–Medium candidate |
| I/O remains active past intended teardown | stronger lifetime primitive candidate |
| real unmap + same-I/O post-unmap DMA attempt | concrete DMA lifetime violation |
| completed DMA into memory after lifetime/reuse | High-potential memory-safety primitive |
| controlled content/destination or boundary crossing | High/Critical candidate depending on preconditions |

No final CVSS is frozen before the impact and precondition evidence exists.
