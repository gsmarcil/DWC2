#!/usr/bin/env python3
"""Property-level guard for the v6.3.2 denominator-causality contract.

Two modes:
  --patch PATCH   package-local: verify that the delta *encodes* the structural
                  contract. This is NOT a real-base apply test.
  --gadget FILE   authoritative post-image check after the real patch chain is
                  applied to the pinned tree.

The guard intentionally checks dataflow/property shape, not comments or exact
line placement.
"""
import argparse, re, sys
from pathlib import Path

REQ = {
    'version9': r'#define\s+DWC2_R1_DUMP_VERSION\s+9U',
    'stop_enter_returns_u8': r'static\s+u8\s+dwc2_r1_stop_enter\s*\(',
    'stop_enter_returns_class': r'return\s+r1->stop_causal\s*;',
    'disable_cause_parameter': r'dwc2_r1_note_disable_candidate\s*\([\s\S]*?u32\s+ctrl\s*,\s*u8\s+cause\s*\)',
    'dequeue_cause_parameter': r'dwc2_r1_note_dequeue_candidate\s*\([\s\S]*?struct\s+dwc2_hsotg_req\s*\*hs_req\s*,\s*u8\s+cause\s*\)',
    'disable_cause_produced': r'u8\s+cause\s*=\s*dwc2_r1_stop_enter\s*\(hsotg\s*,\s*DWC2_R1_STOP_DISABLE\s*\)\s*;',
    'disable_cause_consumed': r'dwc2_r1_note_disable_candidate\s*\(hsotg\s*,\s*hs_ep\s*,\s*ctrl\s*,\s*cause\s*\)\s*;',
    'dequeue_cause_produced': r'u8\s+cause\s*=\s*dwc2_r1_stop_enter\s*\(hs\s*,\s*DWC2_R1_STOP_DEQUEUE\s*\)\s*;',
    'dequeue_cause_consumed': r'dwc2_r1_note_dequeue_candidate\s*\(hs\s*,\s*hs_ep\s*,\s*hs_req\s*,\s*cause\s*\)\s*;',
    'sync_owner_gate': r'cause\s*!=\s*DWC2_R1_CAUSE_SYNC_OWNER',
    'delayed_disable_gate': r'cause\s*==\s*DWC2_R1_CAUSE_DELAYED',
    'overlap_drop': r'cause\s*==\s*DWC2_R1_CAUSE_OVERLAP',
    'delayed_dequeue_gate': r'cause\s*!=\s*DWC2_R1_CAUSE_DELAYED',
}

def _closing_paren(src: str, open_idx: int) -> int:
    """Index of the ')' matching the '(' at open_idx, or -1."""
    depth = 0
    for i in range(open_idx, len(src)):
        if src[i] == '(':
            depth += 1
        elif src[i] == ')':
            depth -= 1
            if depth == 0:
                return i
    return -1


def extract_function(src: str, name: str) -> str:
    """Body of the DEFINITION of `name`, skipping forward declarations.

    Taking the first textual match is wrong whenever the function has a
    prototype earlier in the file: dwc2_hsotg_ep_disable is declared at
    gadget.c:4342 and defined at 5215, so the first match is the prototype and
    the following '{' belongs to some unrelated function.  The guard then
    brace-matched that stranger and reported on it.

    That is not merely a false alarm.  Running the old guard over the correct
    postimage and over one with the ordering deliberately reversed produced the
    SAME verdict, so the check carried no information about the property it
    named.  A definition is distinguished from a declaration by what follows
    the closing paren: '{' rather than ';'.
    """
    pat = re.compile(r'\b' + re.escape(name) + r'\s*\(')
    brace = -1
    for m in pat.finditer(src):
        close = _closing_paren(src, m.end() - 1)
        if close < 0:
            continue
        tail = src[close + 1:close + 200]
        stripped = tail.lstrip(' \t\r\n')
        if stripped.startswith('{'):
            brace = close + 1 + (len(tail) - len(stripped))
            start = src.rfind('\n', 0, m.start()) + 1
            break
    else:
        raise ValueError(f'missing function {name}')
    if brace < 0:
        raise ValueError(f'missing body for {name}')
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[start:i+1]
    raise ValueError(f'unterminated body for {name}')

def patch_added_text(p: str) -> str:
    out=[]
    for line in p.splitlines():
        if line.startswith('+++'):
            continue
        if line.startswith('+'):
            out.append(line[1:])
    return '\n'.join(out)

def check_text(text: str, *, full_postimage: bool) -> list[str]:
    bad=[]
    if full_postimage:
        req = REQ
    else:
        # Patch-local mode sees only added lines; unchanged portions of a
        # multi-line signature may live in context/old-side. Check the
        # structural commitments that must be present in the delta itself.
        req = {
            'version9': REQ['version9'],
            'stop_enter_returns_u8': REQ['stop_enter_returns_u8'],
            'stop_enter_returns_class': REQ['stop_enter_returns_class'],
            'disable_cause_parameter_delta': r'u32\s+ctrl\s*,\s*u8\s+cause\s*\)',
            'cause_parameter_occurs_for_both_candidates': r'(?:u8\s+cause\s*\))[\s\S]*(?:u8\s+cause\s*\))',
            'disable_cause_produced': REQ['disable_cause_produced'],
            'disable_cause_consumed': REQ['disable_cause_consumed'],
            'dequeue_cause_produced': REQ['dequeue_cause_produced'],
            'dequeue_cause_consumed': REQ['dequeue_cause_consumed'],
            'sync_owner_gate': REQ['sync_owner_gate'],
            'delayed_disable_gate': REQ['delayed_disable_gate'],
            'overlap_drop': REQ['overlap_drop'],
            'delayed_dequeue_gate': REQ['delayed_dequeue_gate'],
        }
    for k, pat in req.items():
        if not re.search(pat, text, re.M):
            bad.append(k)
    if full_postimage:
        try:
            dis = extract_function(text, 'dwc2_r1_note_disable_candidate')
            deq = extract_function(text, 'dwc2_r1_note_dequeue_candidate')
            epd = extract_function(text, 'dwc2_hsotg_ep_disable')
            epq = extract_function(text, 'dwc2_hsotg_ep_dequeue')
        except ValueError as e:
            bad.append(str(e)); return bad
        # Candidate functions must consume the explicit cause, not re-read the
        # shared stop_causal field as their classification source.
        if 'r1->stop_causal' in dis:
            bad.append('disable_candidate_re_reads_shared_stop_causal')
        if 'r1->stop_causal' in deq:
            bad.append('dequeue_candidate_re_reads_shared_stop_causal')
        # Dataflow order: the cause producer statement must lexically precede
        # its consumer in the concrete callers. This is a consequence of the
        # explicit variable dependency, not the primary contract itself.
        for name, body, prod, cons in [
            ('disable', epd, 'u8 cause = dwc2_r1_stop_enter', 'dwc2_r1_note_disable_candidate'),
            ('dequeue', epq, 'u8 cause = dwc2_r1_stop_enter', 'dwc2_r1_note_dequeue_candidate')]:
            a,b=body.find(prod),body.find(cons)
            if a < 0 or b < 0 or a >= b:
                bad.append(f'{name}_producer_not_before_consumer')
    return bad

def main():
    ap=argparse.ArgumentParser()
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--patch')
    g.add_argument('--gadget')
    a=ap.parse_args()
    raw=Path(a.patch or a.gadget).read_text()
    text=patch_added_text(raw) if a.patch else raw
    bad=check_text(text, full_postimage=bool(a.gadget))
    if bad:
        print('PROPERTY_GUARD: FAIL')
        for x in bad: print('  -',x)
        return 1
    print('PROPERTY_GUARD: PASS (' + ('postimage' if a.gadget else 'patch-contract') + ')')
    return 0
if __name__=='__main__': raise SystemExit(main())
