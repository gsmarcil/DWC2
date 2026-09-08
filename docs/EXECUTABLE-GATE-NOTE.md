# Executable gate invocation

The repository completeness check is intended to be invoked from the repository root as:

```sh
./VERIFY-REPOSITORY.sh
```

The file mode should remain executable (`100755`). If a transport strips the executable bit, running `sh VERIFY-REPOSITORY.sh` is equivalent for diagnosis, but the canonical repository should preserve the executable mode.

The process exit status governs readiness. `REPOSITORY_BASELINE: PASS` may appear
alongside a nonzero exit when a repository-external campaign contract is
blocked; this separation prevents a device-producer defect from being mislabeled
as corruption of the canonical archive.
