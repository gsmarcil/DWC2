#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE"
sha256sum -c SHA256SUMS
make clean >/dev/null 2>&1 || true
make CFLAGS='-O2 -Wall -Wextra -Werror'
make check
printf '%s\n' 'HOST_V4_VERIFY: PASS (runtime not executed)'
