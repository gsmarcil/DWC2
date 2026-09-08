# Executable gate invocation

The repository completeness check is intended to be invoked from the repository root as:

```sh
./VERIFY-REPOSITORY.sh
```

The file mode should remain executable (`100755`). If a transport strips the executable bit, running `sh VERIFY-REPOSITORY.sh` is equivalent for diagnosis, but the canonical repository should preserve the executable mode.
