# The change the next epoch's merger must absorb

`baseline/` is frozen and is not edited here. This file states, as code, the
two rules that currently live outside it — in `holder_log_guard.py`, run ahead
of the merger — so that when the next epoch's `holder_merge.py` is written they
move inside it and the guard becomes redundant rather than load-bearing.

## Why the rules cannot stay outside forever

`baseline/pipeline/holder_merge.py:23-28` selects records on two fields and
ignores every other one:

```python
        if o.get('event')=='R1A_HOLDER' and o.get('phase')=='campaign': out.append(o)
```

So a `"synthetic": true` flag is invisible to it. A fixture log whose records
carried `phase: "campaign"` would merge to `HOLDER_CONFIRMED` exactly like a
real one. That is why the producer now writes fixtures as
`event: "R1A_HOLDER_SELFTEST"` with `phase: "selftest"` — outside the namespace
the filter reads — rather than relying on a flag the consumer never looks at.

Namespace separation stops the accident. It does not stop a rewrite. A merger
that refuses explicitly does.

## Rule 1 — a fixture marker is a refusal, not a filter

```python
FIXTURE_EVENTS = {'R1A_HOLDER_SELFTEST'}
FIXTURE_PHASES = {'selftest'}
FIXTURE_MODES  = {'selftest_holder'}

        if (o.get('synthetic') or o.get('event') in FIXTURE_EVENTS
                or o.get('phase') in FIXTURE_PHASES
                or o.get('mode') in FIXTURE_MODES):
            raise ValueError('event log line %d carries a fixture marker; '
                             'a fixture is not evidence' % n)
```

**Raise, do not skip.** Filtering the record out would turn a laundered fixture
into "0 campaign events for 3 attempts", which reads as a depth problem and
sends the operator to look at the gadget. Raising reports it as what it is: an
input that must not have been offered. The distinction matters more than the
rejection.

The check runs on **every line**, including the session header, and before the
campaign filter. A header that still says `mode: "selftest_holder"` refuses the
log even if every record below it looks clean.

## Rule 2 — the number must declare the rule that produced it

```python
ACCEPTED_DEFINITIONS = {
    'eshutdown_kills_at_or_before_cutoff_excluding_sync_submit_failures',
}

        if ('pending_definition' in o and
                o.get('pending_definition') not in ACCEPTED_DEFINITIONS):
            raise ValueError('event log line %d declares pending_reads '
                             'rule %r, which this merger does not accept'
                             % (n, o.get('pending_definition')))
        if (o.get('event') == 'R1A_HOLDER' and o.get('phase') == 'campaign'
                and 'pending_definition' not in o):
            raise ValueError('campaign event log line %d omits '
                             'pending_definition' % n)
```

`pending_reads` is a single integer whose meaning is set entirely by the
producer's counting rule. An earlier revision of this producer counted
`(-ESHUTDOWN completions) + (reads that never completed)`, which is a different
and larger number under the same field name. A merger that accepts an
unstamped or unrecognised log is comparing a floor against a quantity it has
not identified.

A campaign record with an absent `pending_definition` is refused for the same
reason: silence is not a declaration. A session/header line does not carry
`pending_reads`, so the canonical producer does not stamp a definition there;
if any other writer does stamp one on such a line, it must still be accepted or
the whole log is refused. This prevents a stale header from contradicting the
records beneath it.

## What this does not claim

Neither rule stops a determined rewrite: the markers are fields in a text file
and can be deleted. What they buy is that laundering stops being a mistake and
becomes an act — a deliberate edit to a file whose sha256 the manifest carries
and whose bytes the gate re-derives.

## Sequence

```text
now      producer separates the namespaces
         holder_log_guard.py enforces both rules ahead of holder_merge.py
         holder_log_guard_selftest.py: 1 positive, 14 fail-closed

next     both rules move into the epoch's holder_merge.py
         holder_log_guard.py becomes redundant; keep it or retire it, but do
         not keep it as the only place the rules live
```

Until then the run order is:

```sh
python3 usbmon_verify.py   --manifest session.json    --usbmon batch.mon -o session+wire.json
python3 holder_log_guard.py --event-log dev-events.jsonl
python3 holder_merge.py    --manifest session+wire.json --event-log dev-events.jsonl --floor 1 -o session+both.json
python3 r1a_manifest.py    session+both.json
```
