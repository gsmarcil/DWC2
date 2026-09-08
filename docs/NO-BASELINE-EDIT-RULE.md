# No-edit baseline repair rule

The canonical re-import is complete. The rule remains binding: do not edit files
under `baseline/` to make `SHA256SUMS` pass.

A future mismatch is evidence that the checked-in file is not the pinned
artifact. The remedy is replacement from the verified archive, not regeneration
or manual correction.
