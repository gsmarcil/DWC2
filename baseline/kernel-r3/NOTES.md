# DWC2 R1 v6.3.2 + P4 — package revision r2

Pin: `f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8`.

## Why r2 exists

The first v6.3.2/P4 package was not a valid real-base artifact:

1. `base/v62-llseek-fixup-v2.patch` had a truncated hunk (`@@ -644,7 +644,6 @@` but only 5/4 body lines).
2. Its v6.3.2 delta expected duplicate assignments that were not present in the shipped byte-identical v6.3.1 patch.
3. `delta_context_selftest.py` reconstructed a base from the patch's own old-side and therefore tested internal patch consistency, not applicability to the real shipped base.

Revision r2 removes that test from the gate, ships the correct llseek fixup, and adopts the independently validated **structural causal-class contract**.

## Design decision: structural cause propagation

Chosen implementation:

```c
u8 cause = dwc2_r1_stop_enter(...);
dwc2_r1_note_*_candidate(..., cause);
dwc2_hsotg_ep_stop_xfr(...);
dwc2_r1_stop_exit(...);
```

`dwc2_r1_stop_enter()` returns the class it wrote. Candidate accounting consumes that explicit value instead of re-reading `r1->stop_causal` or depending merely on line order.

Required properties:

- synchronous cfg0/cfgn/interface denominator accepts only `CAUSE_SYNC_OWNER`;
- `CAUSE_OVERLAP` is never credited to a synchronous trigger;
- delayed-disable counts only `CAUSE_DELAYED`;
- delayed-dequeue counts only `CAUSE_DELAYED`;
- timeout records still read the live `stop_causal` inside `stop_xfr`, so the previously valid positive record path is unchanged;
- semantic dump version remains **9**, with ABI sizes **header=112 / record=80**.

This is stronger than a pure reordering fix because the causal class is a data dependency of candidate accounting. A future move of `note_candidate()` without producing/passing `cause` breaks the function contract rather than silently reviving the denominator bug.

## Property guards, not source-shape guards

`delta_property_guard.py` deliberately ignores comments and exact spelling/line positions. In real-tree mode it checks the applied `gadget.c` for:

- `stop_enter()` returning the causal class;
- explicit `cause` parameters on both candidate functions;
- producer -> consumer dataflow in both callers;
- no candidate function re-reading `r1->stop_causal` as its classifier;
- `SYNC_OWNER`, `DELAYED`, and `OVERLAP` gates;
- semantic ABI v9.

`VERIFY.sh /path/to/linux` is the authoritative applicability gate. Package-local patch-contract checks are explicitly **not** a substitute for real-base apply.

## Denominator semantics

The v6.3.1 order defect was deterministic, not intermittent: candidate accounting ran before the only writer (`stop_enter`) and after initialization/previous `stop_exit` had set the field to `NONE`. Therefore the delayed-disable and overlap branches in `note_disable_candidate()` were unreachable at that point.

The supplied C control reproduces:

```text
counter                  v6.3.1  structural-v6.3.2
cfg0                           6                  2
delayed_disable                0                  2
overlap_count                  2                  2
```

P4 denominator unit remains **endpoint_stop_opportunities**, not host USB attempts. Host-attempt budget must come from the host harness/usbmon. A negative verdict still requires harness `SENSITIVE`.

## Delayed-status boundary

Mass Storage delayed attribution remains **temporal correlation only**. `__raise_exception()` can wake its worker before `fsg_set_alt()` returns `USB_GADGET_DELAYED_STATUS`; that early worker can be classified as overlap. Therefore delayed-negative interpretation requires `overlap_count == 0`. No claim of a worker-carried DWC2 cookie is made.

## Evidence state

The attached fixup package supplied build/audit evidence for the structural source:

- ARM observer=y, `W=1`: RC=0;
- ARM observer=n, `W=1`: RC=0;
- scope audit: 28/28;
- live ABI: v9, 80/112, no holes;
- denominator control: PASS.

Those files are preserved under `evidence/v632-structural/`. They are evidence artifacts, not a replacement for running `./VERIFY.sh /path/to/linux` on another checkout.

## P4

P4 remains fail-closed and selftest-proven (26/26). A negative result requires, among other things: v9, atomic snapshot, `lost=0`, buffer-DMA/non-DDMA target, stable target identity, branch-specific denominator, no duplicate trace, harness `SENSITIVE`, and for delayed branches `overlap_count==0`.

## Current state

```text
v6.3.2 structural source   USER-BUILD/AUDIT SUPPORTED
package r2 integrity       LOCAL VERIFY REQUIRED
real-base apply            VERIFY.sh TREE gate
P4                         SELFTEST 26/26
P3                         NOT BUILT
runtime                    NOT EXECUTED
```

One non-load-bearing documentation debt is retained from the user-validated structural source: an older comment around `stop_enter()` still says “different CPU” even though ownership is task-based (`current`). Property guards do not depend on that comment. Changing it would produce a source postimage different from the already-built structural evidence and should be done, if desired, as a separately revalidated comment-only revision.

---

## r3 — الحارس المصحَّح مدمج (housekeeping فقط)

`delta_property_guard.py` استُبدل بالنسخة التي تميّز التعريف عن التصريح.

```text
before  adbb6b19970c46581aeff6dfc136dc403cf00d77d06ce9a6451996edda7fc598
after   69b063a37498dc5567b9a89f6130146f324c0f14f27a8ac51266aec306779e52
```

`SHA256SUMS` أُعيد توليده في مكانه (45 ملفًا). لا تغيير آخر في الحزمة، ولا
تغيير في أي patch أو في الـABI.

### سبب الاستبدال

`extract_function()` كان يأخذ أول تطابق نصّي للاسم:

```text
gadget.c:4342  static int dwc2_hsotg_ep_disable(struct usb_ep *ep);   <- تصريح
gadget.c:5215  static int dwc2_hsotg_ep_disable(struct usb_ep *ep)    <- تعريف
```

فيمسك التصريح، ثم يأخذ `{` التالية — وهي لدالة أخرى — ويصدر حكمه عليها.
`dwc2_hsotg_ep_dequeue` بلا تصريح أمامي فكان يمر؛ اللاتماثل سببه وجود prototype
لا الخاصية المفحوصة.

اختبار قوة التمييز، قبل وبعد:

```text
                        القديم        المصحَّح
صورة بعدية صحيحة        RC=1          RC=0
ترتيب معكوس عمدًا        RC=1          RC=1
```

القديم يعطي الحكم نفسه للحالتين — أي أنه لا يحمل معلومة عن الخاصية على هذا
الملف. المصحَّح يميّز.

### نطاق P3 — مُثبت من المصدر، لا مفترض

`dwc2_r1_classify_setup()` يصنّف شكلين قياسيين فقط:

```c
	if (ctrl->bRequestType ==
	    (USB_DIR_OUT | USB_TYPE_STANDARD | USB_RECIP_DEVICE) &&
	    ctrl->bRequest == USB_REQ_SET_CONFIGURATION && !w_index && !w_length)
		return w_value ? DWC2_R1_TRIG_SET_CONFIG_NONZERO :
				 DWC2_R1_TRIG_SET_CONFIG_ZERO;

	if (ctrl->bRequestType ==
	    (USB_DIR_OUT | USB_TYPE_STANDARD | USB_RECIP_INTERFACE) &&
	    ctrl->bRequest == USB_REQ_SET_INTERFACE && !w_length)
		return DWC2_R1_TRIG_SET_INTERFACE;

	return DWC2_R1_TRIG_NONE;
```

**غير حاجز لـ:** R1A، R1B، R1C بكل عائلاتها — ACM وPhonet وSourceSink وLoopback
وECM/NCM/RNDIS كلها `SET_INTERFACE` قياسي — وMass Storage كذلك (`fsg_set_alt`).

**حاجز لـ:** الطلبات الصنفية، ومنها Printer `SOFT_RESET` (`USB_TYPE_CLASS`).

**ولا يمكن أن يتحول ضمنيًا إلى PASS.** طلب غير مصنَّف يعطي `TRIG_NONE`،
وكلا `note_*_candidate` يعود فورًا عنده، فلا مقام أصلًا. والسجل ما زال يُكتب
(`goutnak_timeout` لا يشترط trigger)، فيصل إلى P4 بـ`causal_state=NONE`
و`trigger=NONE`، ولا يطابق أي mode، فينتهي إلى:

```text
INCONCLUSIVE_AMBIGUOUS_TIMEOUTS_PRESENT
```

أي فشل مغلق، لا نتيجة سالبة صالحة. فالقيد الذي طلبته محفوظ بالبناء.
