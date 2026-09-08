# No-edit baseline repair rule

Until canonical re-import is complete, do not edit files under `baseline/` to make `SHA256SUMS` pass.

A mismatch is evidence that the checked-in file is not the pinned artifact. The remedy is replacement from the verified archive, not regeneration or manual correction.
