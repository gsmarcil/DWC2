#!/bin/sh
# r1a_host tests that need no USB device.
#
# The abort paths matter as much as the happy one: every one of them exists
# because the alternative is a session that looks like data and is not.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
BIN="${BIN:-$HERE/r1a_host}"
[ -x "$BIN" ] || { echo "build r1a_host first (make)"; exit 1; }
fails=0
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

SCOPE="--g-dma 1 --g-dma-desc 0 --abi-version 9 --abi-header 112 \
--abi-record 80 --snapshot-atomic 1 --lost 0 --overlap-count 0"
ID="--epoch-id e --session-id s --boot-id b \
--sha-image $(printf '%064d' 1) --sha-patch $(printf '%064d' 2) \
--sha-parser $(printf '%064d' 3) --sha-gate $(printf '%064d' 4) \
--sha-gate-v9-1 $(printf '%064d' 10) --sha-harness $(printf '%064d' 5) --sha-validator $(printf '%064d' 6) \
--sha-usbmon-verifier $(printf '%064d' 11) --sha-holder-merger $(printf '%064d' 12) --sha-verdict $(printf '%064d' 13)"

t() {
	desc=$1; want=$2; shift 2
	# shellcheck disable=SC2068
	$@ >"$tmp/o" 2>&1
	rc=$?
	if [ "$rc" = "$want" ]; then
		printf 'ok   %-52s rc=%s\n' "$desc" "$rc"
	else
		printf 'FAIL %-52s rc=%s want=%s\n' "$desc" "$rc" "$want"
		sed 's/^/       /' "$tmp/o" | head -3
		fails=$((fails+1))
	fi
}

echo '== sha256 =='
t "NIST vectors"                    0 "$BIN" --selftest-sha

echo
echo '== scope aborts (spec section 11) =='
# shellcheck disable=SC2086
t "descriptor DMA target rejected"  2 "$BIN" --selftest $ID \
  --g-dma 1 --g-dma-desc 1 --abi-version 9 --abi-header 112 --abi-record 80 \
  --snapshot-atomic 1 --lost 0 --overlap-count 0 --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "lost records rejected"           2 "$BIN" --selftest $ID \
  --g-dma 1 --g-dma-desc 0 --abi-version 9 --abi-header 112 --abi-record 80 \
  --snapshot-atomic 1 --lost 3 --overlap-count 0 --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "non-atomic snapshot rejected"    2 "$BIN" --selftest $ID \
  --g-dma 1 --g-dma-desc 0 --abi-version 9 --abi-header 112 --abi-record 80 \
  --snapshot-atomic 0 --lost 0 --overlap-count 0 --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "ABI v8 rejected"                 2 "$BIN" --selftest $ID \
  --g-dma 1 --g-dma-desc 0 --abi-version 8 --abi-header 112 --abi-record 80 \
  --snapshot-atomic 1 --lost 0 --overlap-count 0 --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "unknown mode rejected"           2 "$BIN" --selftest $SCOPE $ID \
  --mode set-address --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "delayed mode needs overlap 0"    2 "$BIN" --selftest $ID \
  --g-dma 1 --g-dma-desc 0 --abi-version 9 --abi-header 112 --abi-record 80 \
  --snapshot-atomic 1 --lost 0 --overlap-count 2 --mode delayed-dequeue \
  --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "no device and no vid/pid"        2 "$BIN" $SCOPE $ID --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "snapshot source required"        2 "$BIN" $SCOPE $ID --vid 0x1d6b --pid 0x0104

echo
echo '== host endpoint re-arm =='
# shellcheck disable=SC2086
t "two cycles cannot discriminate"  2 "$BIN" --selftest $SCOPE $ID \
  --rearm-cycles 2 --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "65 cycles exceeds the array"     2 "$BIN" --selftest $SCOPE $ID \
  --rearm-cycles 65 --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "two identical arms rejected"     2 "$BIN" --selftest $SCOPE $ID \
  --rearm-reset none --rearm-cycles 8 --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "unknown reset method rejected"   2 "$BIN" --selftest $SCOPE $ID \
  --rearm-reset toggle --manifest "$tmp/m.json"
# shellcheck disable=SC2086
t "probe timeout floor enforced"    2 "$BIN" --selftest $SCOPE $ID \
  --rearm-timeout-ms 10 --manifest "$tmp/m.json"

# The verdict rule lives in this binary and in r1a_manifest.py. Two copies that
# drift would accept a session the harness itself refused to run, so the tables
# are diffed rather than assumed equal.
if command -v python3 >/dev/null && [ -f "$HERE/rule_crosscheck.py" ]; then
	if python3 "$HERE/rule_crosscheck.py" "$BIN" >"$tmp/x" 2>&1; then
		printf 'ok   %-52s\n' "$(tail -1 "$tmp/x")"
	else
		printf 'FAIL %-52s\n' "C and python rule copies disagree"
		sed 's/^/       /' "$tmp/x" | head -6
		fails=$((fails+1))
	fi
else
	printf 'skip %-52s\n' "rule_crosscheck.py not beside this script"
fi

echo
echo '== epoch JSON intake =='
selfh=$(sha256sum "$BIN" | awk '{print $1}')
zero=$(printf '%064d' 0)
cat >"$tmp/epoch.json" <<EOF
{
  "artifacts": {
    "dwc2_r1_v9": "$zero",
    "harness": "$selfh",
    "holder_merger": "$zero",
    "image": "$zero",
    "manifest_validator": "$zero",
    "observer_patch": "$zero",
    "r1_gate_v9": "$zero",
    "r1_gate_v9_1": "$zero",
    "usbmon_verifier": "$zero",
    "verdict_generator": "$zero"
  },
  "epoch_id": "selftest-epoch"
}
EOF
# shellcheck disable=SC2086
t "epoch JSON consumed directly"       0 "$BIN" --selftest $SCOPE \
  --epoch-json "$tmp/epoch.json" --session-id s --boot-id b \
  --manifest "$tmp/epoch-manifest.json"
# shellcheck disable=SC2086
t "epoch JSON cannot mix manual hashes" 2 "$BIN" --selftest $SCOPE \
  --epoch-json "$tmp/epoch.json" --epoch-id manual --session-id s --boot-id b \
  --manifest "$tmp/no.json"
cp "$tmp/epoch.json" "$tmp/epoch-dup.json"
sed -i '2i\  "epoch_id": "duplicate",' "$tmp/epoch-dup.json"
# shellcheck disable=SC2086
t "duplicate epoch_id refused"          2 "$BIN" --selftest $SCOPE \
  --epoch-json "$tmp/epoch-dup.json" --session-id s --boot-id b \
  --manifest "$tmp/no2.json"

echo
echo '== manifest emission =='
# shellcheck disable=SC2086
t "selftest emits a manifest"       0 "$BIN" --selftest $SCOPE $ID \
  --usbmon /etc/hostname --usbmon-bus 1 \
  --manifest "$tmp/m.json"

# The harness alone cannot produce a complete manifest, and should not be able
# to: the two witnesses are merged in afterwards by usbmon_verify.py and
# holder_merge.py, from evidence the harness does not control. So the check is
# not "the validator accepts this" -- it is "the ONLY things missing are the
# two witnesses". Anything else rejected here is a real defect.
if [ -f "$tmp/m.json" ] && command -v python3 >/dev/null; then
	V="$HERE/r1a_manifest.py"
	if [ -f "$V" ]; then
		python3 "$V" "$tmp/m.json" >"$tmp/v" 2>&1
		other=$(grep '^  reject:' "$tmp/v" \
			| grep -cv 'missing wire\|missing holder\|missing artifacts.holder_event_log')
		if [ "$other" = "0" ]; then
			printf 'ok   %-52s\n' \
			  "only the two witnesses are missing"
		else
			printf 'FAIL %-52s\n' \
			  "the emitted manifest has $other other defect(s)"
			sed 's/^/       /' "$tmp/v"
			fails=$((fails+1))
		fi
	else
		printf 'skip %-52s\n' "r1a_manifest.py not beside this script"
	fi
fi

echo
echo '== dump header and denominator window =='
t "header parser and window rule"    0 "$BIN" --selftest-snapshot

echo
if [ "$fails" -gt 0 ]; then echo "R1A_HOST SELFTEST: $fails FAILURE(S)"; exit 1; fi
echo "R1A_HOST SELFTEST: all passed"
