#!/bin/sh
# Copy the bundle to a scratch directory and run the gate there, unmodified.
#
# The point is narrow and was learned the hard way: an earlier abi_check.py
# passed in the directory it was written in and crashed everywhere else,
# because it invoked a probe binary by absolute path instead of building one.
# Verifying in the author's own tree does not show that.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
D=$(mktemp -d)
trap 'rm -rf "$D"' EXIT

cp "$HERE/abi_check.py" "$HERE/abi_probe.c" "$HERE/gen_abi_probe.py" "$D/" || exit 1
cd "$D" || exit 1

echo "running from $D (no edits, nothing from the author's tree)"
if ! python3 ./abi_check.py > out.txt 2>&1; then
	echo "FAIL: abi_check.py did not pass from a scratch directory"
	sed 's/^/  /' out.txt
	exit 1
fi
tail -1 out.txt | sed 's/^/  /'

if grep -rn '/home/claude' abi_check.py abi_probe.c gen_abi_probe.py; then
	echo "FAIL: an absolute path from the author's container survived"
	exit 1
fi
echo "  ok   no author-container paths in the shipped files"

echo
echo "PORTABILITY SELFTEST: PASS"
