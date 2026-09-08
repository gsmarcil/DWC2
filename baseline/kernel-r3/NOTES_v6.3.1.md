# v6.3.1 — أربعة تصحيحات من مراجعتك

مراجعتك كانت للحزمة `b4592ac7…`، وهي **ما قبل** إصلاح portability. §7 كان
مُصلَحًا فعلًا في `447f9f62…` (`gen_abi_probe.py` مشحون، و`abi_check.py` يبني
probe بنفسه). أما §8 فكان قائمًا ولم أعالجه، وهو مُعالَج هنا.

---

## 1. رمز الملكية: `current` بدل الـCPU — وكان استشهادي خاطئًا

هذه أخطر نقطة، وأنت محقّ فيها من وجهين لا وجه واحد.

**الاستشهاد أولًا:** كتبت في التعليق `platform.c:526`، وهي تسجّل
`dwc2_handle_common_intr`. مسار الـgadget يسجّل معالجه الخاص:

```c
/* gadget.c:5898 */
	ret = devm_request_irq(hsotg->dev, hsotg->irq, dwc2_hsotg_irq,
			       IRQF_SHARED, dev_name(hsotg->dev), hsotg);
```

**والاستنتاج ثانيًا:** لا `IRQF_NO_THREAD`، والـpin يحتوي:

```c
/* kernel/irq/manage.c:1312 */
static int irq_setup_forced_threading(struct irqaction *new)
{
	if (!force_irqthreads())
		return 0;
	if (new->flags & (IRQF_NO_THREAD | IRQF_PERCPU | IRQF_ONESHOT))
		return 0;
```

فمع `threadirqs=` يصير المعالج kthread قابلًا للإزاحة والهجرة.

وأضيف ما هو أسوأ مما ذكرت: تحت forced threading، مقارنة الـCPU لا تفوّت overlap
فحسب، بل **تنسب إيجابيًا** stop قادمًا من مهمة غير ذات صلة جُدولت على نفس الـCPU.
أي أنها ليست فقدان حساسية بل إسناد كاذب.

```c
	r1->setup_owner_task = current;
	...
	if (r1->setup_owner_task == current)
		DWC2_R1_CAUSE_SYNC_OWNER;
	else
		DWC2_R1_CAUSE_OVERLAP;
```

المؤشر يُقارَن ولا يُفكّ إسناده أبدًا، ولا يصل إلى الـABI. `owner_cpu` بقي في
السجل **تشخيصيًا فقط** — تحققت أن `setup_owner_task` لا يظهر في layout الـprobe.

---

## 2. الـclassifier يتفرّع على `num_mapped_sgs`

عبارتي «نفس اختبارات unmap وبنفس الترتيب» كانت **غير صحيحة حرفيًا**. المصدر:

```c
/* udc/core.c:969-978 */
	if (req->num_mapped_sgs) {
		dma_unmap_sg(...);
	} else if (req->dma_mapped) {
		dma_unmap_single(...);
	}
```

وكنت أتفرّع على `num_sgs`. أخذت صيغتك كما هي، مع `INCONSISTENT_SG` عندما
`num_mapped_sgs` موجب و`num_sgs` صفر — بدل أن يمرّ صامتًا كـSG.

---

## 3. `SG_COUNT_OVERFLOW`

`num_sgs` و`num_mapped_sgs` هما `unsigned` في `gadget.h:109-110`، و`__le16` في
السجل. أخذت حلّك الاقتصادي بدل كسر الـABI:

```c
	if (req->num_sgs > U16_MAX || req->num_mapped_sgs > U16_MAX)
		*f2 |= DWC2_R1_F2_SG_COUNT_OVERFLOW;
```

المسار الخطي غير متأثر — كلاهما صفر فيه.

---

## 4. مقام delayed-dequeue

كنت محقًّا: `candidate_delayed_seen` كان يُزاد في `note_disable_candidate()`
وحدها، ومسار Mass Storage يدخل عبر `ep_dequeue`. فلم يكن هناك مقام أصلًا.

الآن عدّادان منفصلان كما طلبت، و`dwc2_r1_note_dequeue_candidate()` يستخدم
**حالة برمجية فقط** — نوع الـendpoint من `hs_ep->ep.desc` لا من قراءة DOEPCTL،
فلا MMIO إضافي قبل الانتظار.

**تفاوت مسجَّل عمدًا:** مقام مسار disable يؤكد `EPENA` و`EPTYPE_BULK` من قراءة
سجل يقوم بها السائق أصلًا؛ مقام dequeue لا يملك ذلك. لذلك هو **أضعف**، وحُفظ في
حقل ترويسة منفصل حتى لا يجمعهما محلل أبدًا.

**والنافذة العمياء التي كشفتها لم أُصلحها، وسجّلتها:**

```c
/* f_mass_storage.c:382 */
		if (common->thread_task)
			send_sig_info(SIGUSR1, SEND_SIG_PRIV,
				      common->thread_task);
```

الإشارة تُرسل قبل رجوع `fsg_set_alt()`، فقد يستيقظ الـworker ويُلغي بينما
الطور ما زال SYNC على مهمة أخرى → OVERLAP. فشل مغلق، لكنه فقدان حساسية.
لذلك:

```text
Mass-Storage negative result  REQUIRES  overlap_count == 0
```

وأقبل تسميتك: `R1_DELAYED_DEQUEUE_CORRELATED` لا `R1_PASS_...`، حتى لا يتحول
الاقتران الزمني إلى برهان سببي بالاسم.

---

## §8 — الأدلة صارت داخل الحزمة

كان اعتراضك صحيحًا: منهج الحملة يرفض artifact لا يمكن إعادة التحقق منه، وكنت
أطلب تصديق نتائج لا يمكنك اشتقاقها.

```text
evidence/build-v631-arm-y.log      evidence/abi-check-live.txt
evidence/build-v631-arm-n.log      evidence/abi-negative-test.txt
evidence/config-observer-y         evidence/abi-layout-x86_64.txt
evidence/config-observer-n         evidence/abi-layout-arm32.txt
evidence/config-delta.txt          evidence/abi-cross-arch.txt
evidence/scope-audit.txt           evidence/clean-room-identity.txt
SHA256SUMS                         VERIFY.sh
```

`config-delta.txt` يستحق نظرة: الفرق بين الإعدادين **سطر واحد بالضبط**:

```text
1722d1721
< CONFIG_DWC2_REQ_UNMAP_R1_OBSERVER=y
```

و`./VERIFY.sh` يفحص السلامة والABI وportability ويؤكد أن الأدلة المسجَّلة تقول
ما يجب، و`./VERIFY.sh /path/to/linux` يعيد اشتقاق ABI وscope من شجرتك.
جرّبته سلبيًا: تخريب ملف دليل أو patch يُرصد بـRC=1.

---

## الحالة

```text
P0_SYNC        OWNER TOKEN HARDENED  (current، والاستشهاد مُصحَّح)
P0_DELAYED     TEMPORAL CORRELATION ONLY
               blind window مسجَّلة، وnegative يتطلب overlap_count == 0
               denominator موجود الآن، وأضعف صراحةً
P1             PASS
P2_LINEAR      PASS
P2_SG          num_mapped_sgs مُصحَّح، truncation مُعلَّم
ABI            v8، 80/112، بلا holes، ARM32 == x86_64
ABI_TOOLING    self-contained + anti-drift + negative-tested
PACKAGE        REPRODUCIBLE (VERIFY.sh + SHA256SUMS + evidence)
P3 / P4        NOT BUILT
RUNTIME        NOT EXECUTED
```

لم أذهب إلى العتاد، وأوافق أن P4 يسبقه.
