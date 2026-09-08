# Reconstructed audit chronology

> **RECONSTRUCTED — not original commit history.**
>
> This branch exists to preserve *why* each surviving guard and proof rule exists. It must not be read as if these commits were created at the original research dates.

## Rules for reconstructed milestones

Each milestone records only conclusions that survived later review. A milestone must state:

- the gap;
- how it was discovered;
- the correction;
- the discriminating test;
- the surviving claim after correction.

If an original package is not present and hash-verifiable, the chronology must not assign an exact historical package version to the milestone.

---

## Milestone A — observer denominator causality

**Gap.** A candidate counter on the endpoint-disable path could observe the causal state before `stop_enter()` established it, making the denominator structurally wrong.

**Discovery.** Clean-room review of the call order showed that `note_disable_candidate()` consumed `stop_causal` before the stop operation populated it.

**Correction.** `dwc2_r1_stop_enter()` returns an explicit cause; candidate accounting consumes that value directly before `dwc2_hsotg_ep_stop_xfr()` and `stop_exit()` clears the state.

**Discriminating evidence.** The denominator-order control distinguishes the old ordering from the corrected one; the corrected postimage is also checked by the property guard against a deliberately reversed ordering.

**Surviving claim.** The observer denominator can be used only under the corrected structural ordering and its verification gates.

---

## Milestone B — delta/property guard integrity

**Gap.** An earlier context/selftest reconstructed the old side synthetically and could pass an internally consistent patch without proving that the patch applied to the real frozen base. A function extractor also matched a forward declaration instead of the function definition.

**Discovery.** Real-base application and a deliberately reversed postimage produced the same failure until the extractor was corrected.

**Correction.** Real-base application became mandatory; the function extractor skips declarations and accepts only definitions. The synthetic context gate was removed from the trust path.

**Discriminating evidence.** Correct postimage: PASS. Reversed-order malformed postimage: FAIL.

**Surviving claim.** Structural patch verification is meaningful only when tied to the real frozen base and a discriminating postimage property.

---

## Milestone C — ABI/provenance correction

**Gap.** Earlier evidence handling contained stale artifacts and a negative ABI capture whose surrounding evidence could report failure while the shell status remained zero.

**Discovery.** SHA/ABI clean-room reruns exposed the mismatch and an injected-hole test confirmed the live checker itself failed correctly.

**Correction.** ABI v9 (`header=112`, `record=80`) is the frozen observer interface; clean-room identity and negative ABI tests are retained as supporting evidence.

**Surviving claim.** The current pre-runtime observer/parser contract is ABI v9 only. Older ABI artifacts are historical and may not be aggregated into the active epoch.

---

## Milestone D — negative-result denominator discipline

**Gap.** Host attempts, endpoint-stop opportunities, sensitivity pre-flight traffic, restore traffic, and invalid attempts could be conflated in aggregate counters.

**Discovery.** Audit showed that pre-flight/restore operations can increase the same branch counters used by a negative campaign; a simple final counter value is therefore not a campaign denominator.

**Correction.** The methodology requires explicit pre-flight/campaign separation, measured multiplicity `k`, and a campaign-scoped denominator. Invalid triggered attempts cannot be silently subtracted from aggregate device-side accounting.

**Surviving claim.** A negative result is valid only when the frozen gate proves its denominator and eligibility predicates; absence alone is never `R1_DISPROVEN`.

---

## Milestone E — wire and holder witnesses

**Gap.** A userspace `inflight` counter alone cannot prove that a Bulk OUT URB remained outstanding at the wire boundary, and a host-side URB alone cannot prove that a function-driver request remained queued on the gadget side.

**Discovery.** Review identified races between nonblocking reap and the raw EP0 trigger, and the distinct possibility of host outstanding traffic while the gadget holder was empty.

**Correction.** The evidence model uses two independent witnesses:

- `usbmon` re-derives the host-side outstanding predicate;
- the holder event log proves the gadget-side queued-request condition.

They are not substitutes for each other. Ambiguous zero-depth observations are rejected rather than interpreted.

**Surviving claim.** R1A requires both host-wire and gadget-holder preconditions under the frozen manifest/gate rules.

---

## Milestone F — cross-session evidence binding

**Gap.** A valid-looking witness or harness JSON from another session could be substituted if hashes/session identity were not checked at the point of verdict generation.

**Discovery.** Cross-session substitution tests showed that a structurally valid but unrelated artifact could otherwise satisfy local schema checks.

**Correction.** Evidence is bound by content hashes and session/boot identity; the gate consumes the manifest directly rather than trusting a hand-authored bridge. Epoch-changing tools are themselves pinned.

**Discriminating evidence.** Swapping the capture, trace, or holder log with another session must fail at the corresponding witness/gate stage.

**Surviving claim.** No negative or positive classification may cross epoch/session boundaries by filename or operator assertion alone.

---

## Milestone G — epoch freezing from executable reality

**Gap.** Manually typing hashes and maintaining a second hand-written artifact list can pin the wrong files while still producing syntactically valid manifests.

**Discovery.** A proposed freezer immediately drifted from the actual validator/gate contract (wrong artifact names and a compatibility tool that had left the trust path).

**Correction.** The freeze design derives the epoch contract from the validator and the modules actually loaded by the gate. The host consumes `epoch.json` directly instead of requiring the operator to retype hashes.

**Surviving claim.** The active epoch must describe the files that actually execute; changing a load-bearing tool creates a new epoch and invalidates accumulated negatives.

---

## Version-name mapping

Historical labels such as `v3.1 → v3.2 → v3.3` are useful only after the corresponding original packages are imported and independently hash-verified. Until that import is complete, this chronology deliberately records **audit milestones rather than inventing exact version boundaries**.
