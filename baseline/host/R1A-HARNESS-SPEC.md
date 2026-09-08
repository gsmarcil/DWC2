# R1A Harness Specification v4.2

<!-- R1A_CONTRACT {"manifest_version":2,"gate_entry":"r1_gate_v9_1.py","gate_manifest_arg":"--manifest","gate_harness_arg":"absent","legacy_bridge_trusted":false,"epoch_artifacts":["image","observer_patch","dwc2_r1_v9","r1_gate_v9","r1_gate_v9_1","harness","manifest_validator","usbmon_verifier","holder_merger","verdict_generator"],"host_epoch_arg":"--epoch-json"} -->

الـpin: `f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8`. كل استشهاد أدناه منه.

الـharness وشاهدا الإثبات ينتجان manifest واحدًا مربوطًا بالأدلة الخام:

```text
device side   r1a_ffs_out_v2 / holder event log   على اللوحة
host side     r1a_host v4                         على المضيف
capture       usbmon                              على المضيف
observer      S0 / S1 / S2                        من DWC2 ABI v9
                    ↓
              base manifest v2
                    ↓
       usbmon_verify.py → holder_merge.py
                    ↓
              merged manifest v2
                    ↓
       r1_gate_v9_1.py --manifest ... --json S2.bin
                    ↓
              r1_verdict.py
```

`manifest_to_p4.py` **ليس حد ثقة ولا يدخل مسار الحكم**. والبوابة الأصلية
`r1_gate_v9.py` تبقى مجمّدة بايتيًا وتُستورد داخل wrapper v9.1؛ لا تُستدعى
مباشرةً لحكم الحملة.

---

## §1 القيد المُثبت: لماذا usbfs الخام، ولماذا لا شيء غيره

### 1.1 لماذا الـAPI المريح ممنوع

```c
/* drivers/usb/core/message.c:2124 — usb_set_configuration() */
		usb_disable_device(dev, 1);	/* Skip ep0 */
/* :2209 */
	ret = usb_control_msg_send(dev, 0, USB_REQ_SET_CONFIGURATION, 0,
```

```c
/* drivers/usb/core/message.c:1617 — usb_set_interface() */
	 * Make sure the interface endpoints are flushed before that
	 */
	usb_disable_interface(dev, iface, false);
/* :1649 */
		ret = usb_control_msg_send(dev, 0,
					   USB_REQ_SET_INTERFACE,
```

التعطيل يسبق الـcontrol transfer في الحالتين. فأي مسار يمر بهما **يقتل الـURBs
قبل إرسال الطلب**، ويُلغي الشرط التجريبي الوحيد الذي تقوم عليه الحملة.

**ممنوع منعًا باتًا:**

```text
libusb_set_configuration()          libusb_set_interface_alt_setting()
USBDEVFS_SETCONFIGURATION  (U,5)    ioctl USBDEVFS_SETINTERFACE
أي غلاف يستدعي أيًا مما سبق
```

### 1.2 لماذا usbfs الخام يعمل — مُثبت لا مأمول

```c
/* drivers/usb/core/devio.c:881 */
static int check_ctrlrecip(struct usb_dev_state *ps, unsigned int requesttype,
			   unsigned int request, unsigned int index)
{
	...
/* :908 */
	switch (requesttype & USB_RECIP_MASK) {
	case USB_RECIP_ENDPOINT:
		...
	case USB_RECIP_INTERFACE:
		ret = checkintf(ps, index);
		break;
	}
	return ret;
}
```

**لا يوجد `case USB_RECIP_DEVICE`.** و`SET_CONFIGURATION` هو
`bmRequestType = 0x00`، و`0x00 & USB_RECIP_MASK = USB_RECIP_DEVICE` → يسقط من
الـswitch بـ`ret = 0` → يُسمح.

ثم:

```c
/* drivers/usb/core/devio.c:1180 — do_proc_control() */
	ret = check_ctrlrecip(ps, ctrl->bRequestType, ctrl->bRequest,
			      ctrl->wIndex);
	if (ret)
		return ret;
```

ويبني URB من `usb_ctrlrequest` كما سلّمه المستدعي حرفيًا. **لا اعتراض على
`SET_CONFIGURATION` بالاسم في الملف كله** — تحققت بالبحث.

`SET_INTERFACE` (`bmRequestType = 0x01`) يمر عبر `checkintf()` فيتطلب أن يكون
الـharness قد طالب بالواجهة (`USBDEVFS_CLAIMINTERFACE`). هذا مقبول ومطلوب أصلًا.

### 1.3 النتيجة المقصودة: المضيف يفقد التزامن

لأن usbcore لا يرى هذا الطلب، يبقى `dev->actconfig` قديمًا. المضيف يظن الجهاز
مضبوطًا بينما الجهاز فكّ ضبطه فعلًا. **هذا مقصود ولازم**، وله ثلاث تبعات
إلزامية:

```text
1  الـURBs المعلّقة تبقى مقدَّمة من منظور المضيف لحظة الـtrigger — وهذا الشرط
2  ما يليها سيفشل بـEPIPE/ESHUTDOWN/ENODEV أو يُعاد تعداد الجهاز
3  الـharness يجب أن يعيد التزامن صراحةً (§6) لا أن ينتظر انهيارًا
4  حالة الطرف على جانب المضيف لا تُصفَّر — وهذه هي §6.1
```

**التبعة الرابعة أخطر من الثلاث الأولى لأنها صامتة.** المسار الطبيعي يصفّر
حالة الطرف على جانب المضيف:

```text
drivers/usb/core/message.c:1819   usb_enable_interface(dev, intf, true);
drivers/usb/core/message.c:1520-1521  if (reset_ep) usb_hcd_reset_endpoint(dev, ep);
```

والجهاز يصفّر نفسه بلا شرط حين تعيد طبقة composite تمكين الطرف:

```text
drivers/usb/dwc2/gadget.c:5162    /* for non control endpoints, set PID to D0 */
drivers/usb/dwc2/gadget.c:5164    epctrl |= DXEPCTL_SETD0PID;
```

فبعد استعادة خام: الـgadget على DATA0 والمضيف حيث توقّف. محاولة لا تتحرك فيها
حمولة الـBulk OUT ليست نتيجة صفرية — إنها **أداة معطوبة تُنتج سجلًا يطابق
النتيجة الصفرية حرفًا بحرف**. لا يوجد في المخرجات ما يفرّق بينهما، ولهذا §6.1
شرط لبدء الحملة لا تحسينًا لها.

---

## §2 الجانب الجهازي

### 2.1 الموجود

`r1a_ffs_out_v2` (حزمة `r1a-harness-v2.tar.gz`) يوفّر بالفعل:

```text
AIO حصرًا عبر io_submit          العمق الحقيقي > 1 مستحيل بدونه
ep2 مؤكَّد بـENDPOINT_DESC        لا يُفترض
ready من حدث ENABLE مرصود        لا من sleep
measured_peak_inflight            مقاس لا مطلوب
sensitivity.verdict               HARNESS_SENSITIVE ضروري لا كافٍ
```

### 2.2 الإضافات المطلوبة لـv6.3.2 / P4

```text
--boot-id            يقرأ /proc/sys/kernel/random/boot_id ويضعه في المخرَج
                     ليمنع دمج محاولات من إقلاعات مختلفة في جلسة واحدة

--dump-after PATH    يقرأ <debugfs>/usb/<dev>/r1_trace بعد إغلاق الجلسة
                     ويحفظه، ثم يحسب sha256 له

--caps-out PATH      يستخرج g_dma / g_dma_desc / abi / snapshot_atomic / lost
                     من ترويسة الـdump — لا من cmdline. المصدر إلزاميًا
                     dump_header كما يفرض الـmanifest

--reset-before       يكتب إلى r1_reset قبل الجلسة، ويسجّل reset_generation
                     الناتج، فلا تختلط جلستان في حلقة واحدة
```

**لا يُطلب من الجانب الجهازي أن يُصدر الـtrigger.** الـtrigger من المضيف
حصرًا، وهو مصدر عدّ المقام الوحيد.

---

## §3 الجانب المضيف — التسلسل الدقيق

جهاز الوصول: `/dev/bus/usb/BBB/DDD`.

### 3.1 التهيئة، مرة لكل جلسة

```c
fd = open("/dev/bus/usb/003/007", O_RDWR);

unsigned intf = 0;
ioctl(fd, USBDEVFS_CLAIMINTERFACE, &intf);   /* U,15 */
```

المطالبة بالواجهة **إلزامية** حتى لو لم نُصدر `SET_INTERFACE`: بدونها لا يمكن
تقديم URBs على نقاطها الطرفية.

### 3.2 تسليح الـBulk OUT

```c
struct usbdevfs_urb u[DEPTH];
for (i = 0; i < DEPTH; i++) {
	memset(&u[i], 0, sizeof(u[i]));
	u[i].type          = USBDEVFS_URB_TYPE_BULK;   /* 3 */
	u[i].endpoint      = 0x02;                     /* OUT، من الواصفات */
	u[i].buffer        = buf[i];
	u[i].buffer_length = XFER_LEN;
	u[i].usercontext   = (void *)(uintptr_t)i;     /* للربط عند القطف */
	if (ioctl(fd, USBDEVFS_SUBMITURB, &u[i]) < 0)  /* U,10 */
		abort_attempt("submit_failed");
	inflight++;
}
```

`endpoint = 0x02` وليس رقمًا مفترضًا — يُقرأ من واصفات الجهاز، ويجب أن يطابق
ما أكّده الجانب الجهازي بـ`FUNCTIONFS_ENDPOINT_DESC`. عدم التطابق = إجهاض.

### 3.3 predicate الصلاحية — الفحص الآلي لحظة الـtrigger

هذا هو البند الذي طلبته: **«معلَّق» ليست حالة تُفترض بل تُقاس.**

```c
/* اقطف كل ما اكتمل، بلا انتظار، ثم اعرف كم بقي فعلًا */
static int drain_completed(int fd, unsigned *inflight)
{
	struct usbdevfs_urb *done;
	int reaped = 0;

	while (ioctl(fd, USBDEVFS_REAPURBNDELAY, &done) == 0) {  /* U,13 */
		(*inflight)--;
		reaped++;
	}
	if (errno != EAGAIN)          /* EAGAIN وحده يعني "لا شيء جاهز" */
		return -1;
	return reaped;
}

/* لحظة الإطلاق، وليس قبلها بثانية */
drain_completed(fd, &inflight);
if (inflight < 1) {
	record_attempt_invalid("not_outstanding");
	goto resync;                  /* لا تُصدر trigger على محاولة ميتة */
}
unsigned inflight_at_trigger = inflight;
```

القيم التي تدخل الـmanifest:

```json
"outstanding": {
  "checked": true,
  "method": "urb_status_pending",
  "inflight_at_trigger": 8,
  "urb_completed": false
}
```

`method` من قائمة مغلقة (`aio_inflight` جهازيًا، `urb_status_pending` مضيفًا).
والـvalidator يرفض أي قيمة أخرى صراحةً لا صامتًا.

**الترتيب إلزامي:** القطف ثم الفحص ثم الإطلاق، بلا أي عملية مُدخِلة تأخيرًا
بينها. تأخير بين الفحص والإطلاق يجعل الفحص عن لحظة أخرى.

### 3.4 الـtrigger الخام

```c
struct usbdevfs_ctrltransfer ct = {
	.bRequestType = 0x00,   /* OUT | STANDARD | DEVICE */
	.bRequest     = 0x09,   /* USB_REQ_SET_CONFIGURATION */
	.wValue       = 0x0000, /* الضبط صفر */
	.wIndex       = 0x0000,
	.wLength      = 0,
	.timeout      = 1000,
	.data         = NULL,
};
clock_gettime(CLOCK_REALTIME, &t_trigger);
int rc = ioctl(fd, USBDEVFS_CONTROL, &ct);   /* U,0 */
```

`wIndex` و`wLength` صفران لأن `dwc2_r1_classify_setup()` يشترطهما:

```c
/* drivers/usb/dwc2/gadget.c */
	if (ctrl->bRequestType ==
	    (USB_DIR_OUT | USB_TYPE_STANDARD | USB_RECIP_DEVICE) &&
	    ctrl->bRequest == USB_REQ_SET_CONFIGURATION && !w_index && !w_length)
```

قيمة غير صفرية في أيهما تعطي `TRIG_NONE` → لا مقام → المحاولة ضائعة صامتًا.
**الـharness يجب أن يرفض تشغيل نفسه إن كانت أي منهما غير صفر.**

لـR1B: `wValue = 1` (أو رقم الضبط الفعلي). لـR1C: `bRequestType = 0x01`،
`bRequest = 0x0b`، `wIndex = رقم الواجهة` — ويتطلب claim تلك الواجهة.

### 3.5 ما بعد الإطلاق مباشرة

```text
settle        انتظار محدَّد (مثلًا 200 ms) قبل أي قراءة — يُسجَّل في الـmanifest
              لأنه يحدد نافذة الالتقاط
capture       اقطف كل URB متبقٍ وسجّل status لكل منها
              (سترى EPIPE / ESHUTDOWN / ENODEV — متوقع، ليس فشلًا)
```

---

## §6 إعادة التزامن

المضيف الآن يظن الجهاز مضبوطًا وهو ليس كذلك (§1.3). قبل المحاولة التالية:

```text
1  اقطف كل URB معلّق أو DISCARDURB (U,11) ما بقي
2  RELEASEINTERFACE (U,16)
3  أعد الضبط بـtrigger خام آخر: SET_CONFIGURATION(wValue = الضبط الأصلي)
   — لا بـUSBDEVFS_SETCONFIGURATION، فذاك يستدعي المسار الممنوع
4  CLAIMINTERFACE مجددًا
5  إن فشل أي مما سبق: أغلق fd، انتظر إعادة التعداد، افتح العقدة الجديدة،
   وسجّل نافذة مستبعدة بسبب enumeration
```

الخطوة 3 مهمة: إعادة الضبط عبر الـAPI المريح ستستدعي `usb_disable_device()`
على جهاز المضيف يظنه مضبوطًا — سلوك غير معرَّف، ويلوّث الجلسة.

### 6.1 تصفير حالة الطرف على جانب المضيف — خطوة 4.5

بعد `CLAIMINTERFACE` ومباشرةً قبل المحاولة التالية:

```text
4.5  USBDEVFS_RESETEP (U,3) على bEndpointAddress للطرف تحت الاختبار
```

الإثبات من الشجرة المثبتة، لا من الذاكرة:

```text
include/uapi/linux/usbdevice_fs.h:191
    #define USBDEVFS_RESETEP  _IOR('U', 3, unsigned int)

drivers/usb/core/devio.c:2659     case USBDEVFS_RESETEP:
drivers/usb/core/devio.c:1396     static int proc_resetep(struct usb_dev_state *ps, ...
drivers/usb/core/devio.c:1409     check_reset_of_active_ep(ps->dev, ep, "RESETEP");
drivers/usb/core/devio.c:1410     usb_reset_endpoint(ps->dev, ep);
drivers/usb/core/message.c:1373-1374  * Resets any host-side endpoint state such as the toggle bit, ...
```

نصّ التوثيق كاملًا كما هو في الشجرة: "Resets any host-side endpoint state such
as the toggle bit, sequence number or current window."

ثلاث حقائق تجعل هذه الخطوة مقبولة داخل البروتوكول المجمّد:

```text
أ  لا تغيير ضبط في المسار كله — proc_resetep ينتهي عند usb_reset_endpoint،
   و USB_REQ_SET_CONFIGURATION لا يرد في devio.c إطلاقًا (0 مرة)
ب  لا هدم لأي URB — check_reset_of_active_ep (devio.c:1382-1394) يصدر
   dev_warn فقط ولا يرفض ولا يُفرغ قائمة urb_list
ج  موضع النداء بين المحاولات، وهي اللحظة الوحيدة التي لا يُشترط فيها وجود
   أي نقل معلّق — فلا يمكن لهذه الخطوة أن تهدم الشرط محل الدراسة
```

**ما لا نعود إليه:** `USBDEVFS_SETCONFIGURATION` (U,5). يعيد المشكلة الأصلية
لأنه يمر بـ`usb_disable_device()` قبل الطلب (message.c:2124 قبل 2209).

**بديل متاح وليس افتراضيًا:** `USBDEVFS_CLEAR_HALT` (U,21) يصفّر مزلاج المضيف
أيضًا (`usb_clear_halt` ينادي `usb_reset_endpoint` عند النجاح — message.c:1389)
لكنه يضع `CLEAR_FEATURE(ENDPOINT_HALT)` حقيقيًا على السلك أولًا. هذا طلب مرئي
للجهاز لم يطلبه البروتوكول المجمّد، فهو خيار (`--rearm-reset clear-halt`) لا
افتراض.

### 6.2 هل الخطوة 4.5 **لازمة**؟ لا يُحسم من المصدر

```text
drivers/usb/core/hcd.c:1990   void usb_hcd_reset_endpoint(struct usb_device *udev, ...
                                if (hcd->driver->endpoint_reset)
                                        hcd->driver->endpoint_reset(hcd, ep);
                                else
                                        usb_settoggle(udev, epnum, is_out, 0);
```

السلوك خاصية متحكّم المضيف عند المشغّل، لا خاصية للشجرة. لذلك تُحسم **بالقياس**
قبل أي محاولة تُحتسب: `--preflight-rearm`، ذراعان، والمقياس هو **تقدّم الحمولة**
لا نجاح التقديم.

```text
البروتوكول   two_arm_payload_progress
خط الأساس    نقلة Bulk OUT واحدة قبل أي دورة. إن فشلت، فالجانب الجهازي لا
             يقرأ، والحكم REARM_BASELINE_FAILED — خطأ مشغّل، لا دليل عن re-arm
الذراع A     trigger الحملة ← استعادة الحملة ← بلا تصفير ← نقلة واحدة
الذراع B     trigger الحملة ← استعادة الحملة ← تصفير ← نقلة واحدة
التشابك      دورة بدورة، لا ذراع كاملة ثم أخرى: انجراف الجانب الجهازي لا
             يتنكّر في صورة أثر ذراع
التقدّم       reaped ∧ status == 0 ∧ actual_length == probe_len
             "قُدِّم بلا خطأ" مرفوض عمدًا: التقديم ينجح على مزلاج عالق كما
             ينجح على سليم، وهذا الالتباس هو ما وُجد الاختبار ليكشفه
```

قاعدة الحكم، مشتقة لا مُعلَنة. لتكن C عدد الدورات، N تقدّم الذراع A، R تقدّم
الذراع B:

```text
performed = false                → REARM_NOT_TESTED
خط الأساس فشل                    → REARM_BASELINE_FAILED
C < 3                            → REARM_INDETERMINATE
R = C ∧ N = 0                    → REARM_RESET_REQUIRED    (مُميِّز)
R = C ∧ N = C                    → REARM_NO_RESET_NEEDED   (غير مُميِّز)
R = C ∧ 0 < N < C                → REARM_INDETERMINATE
R < C ∧ N = C                    → REARM_RESET_HARMFUL
R < C ∧ N < C                    → REARM_BROKEN
```

يبدأ الحملة حكمان فقط: `REARM_RESET_REQUIRED` و`REARM_NO_RESET_NEEDED`.

الثاني **نتيجة سالبة أمينة**: هذا المتحكّم لم يُظهر فقدان تزامن، فالطرف كان
حيًّا بالبرهان، لكن الجلسة **لا تحمل أي دليل على أن التصفير هو ما جعلها تعمل**،
ويُمنع الاستشهاد به كأنها تحمله. يبقى التصفير مفعّلًا احتياطًا فقط، ويسجّل
المانيفست `discriminating: false`، ويطبع قالب الحكم السطر المقابل تحت
"ما يبقى مجهولًا".

القاعدة نفسها مكتوبة مرتين — `rearm_verdict()` في `r1a_host.c` و
`derive_rearm()` في `r1a_manifest.py` — والانجراف بينهما يعني قبول جلسة رفض
الـharness نفسه تشغيلها. لذلك يُصدِّر الثنائي جدوله كاملًا
(`--dump-rearm-table`، 560 صفًّا) ويقارنه `rearm_crosscheck.py` صفًّا بصف بدل
أن يدّعي أي طرف التكافؤ.

### 6.3 البديل المعتمَد إن فشل الـpre-flight

لا يُرتجل لاحقًا. إن خرج الحكم `REARM_BROKEN` أو `REARM_RESET_HARMFUL` أو
`REARM_INDETERMINATE`، فالمسار المعتمَد هو:

```text
محاولة واحدة مُتلِفة لكل epoch تعداد/ضبط جديد
    - محاولة واحدة فقط، ثم إعادة تعداد كاملة للجهاز
    - لا إعادة استخدام لحالة مضيف بعد استعادة خام إطلاقًا
    - B يصير عدد الـepochs، لا عدد المحاولات
    - denominator.unit يبقى host_attempts، لكن كل epoch يساهم بـ1
```

الكلفة صريحة: الإنتاجية تنهار بمقدار زمن إعادة التعداد لكل محاولة، وحدّ
"قاعدة الثلاثة" يتضخّم بنفس النسبة لأن B أصغر بكثير. المكسب أنه **لا يحتاج
re-arm عاملًا على الإطلاق**: كل محاولة تبدأ من حالة مضيف طازجة أنشأها المسار
الطبيعي، بما فيه `usb_enable_interface(dev, intf, true)`.

---

## §6.4 المقام يُقاس، ولا يُقرأ من عدّاد

عدّادات المراقب تراكمية، فقراءة واحدة في النهاية تحوي burst الحساسية و
pre-flight الـre-arm. وفي وضع **cfgn** الأمر أسوأ: الاستعادة في §6 هي نفسها
`SET_CONFIGURATION` بـwValue غير صفري، ويصنّفها
`dwc2_r1_classify_setup()` كـ`DWC2_R1_TRIG_SET_CONFIG_NONZERO` — أي أنها تزيد
`candidate_cfgn_seen`، وهو بعينه مقام ذلك الفرع. كل محاولة تضيف إلى مقامها
مرتين.

ثلاث لقطات للـdump عبر `--snapshot-cmd`، كلٌّ بـsha256 خاصتها:

```text
S0   بعد pre-flight الـre-arm، قبل burst الحساسية
S1   بعد burst الحساسية، قبل الحملة   ← صفر الحملة
S2   بعد الحملة                        ← وهذا هو الـdump الذي يُشحن
```

```text
k            = (S1 - S0) / محاولات الحساسية      ← مقيس، ويجب أن يكون صحيحًا
delta الحملة = (S2 - S1)
الشرط        delta == k × B_valid
```

يُرفض قبل ذلك: تغيّر `reset_generation` بين اللقطات، أو `lost != 0`، أو تراجع
العدّاد، أو محاولة حساسية واحدة غير صالحة، أو **B_valid = 0** — وهذا الأخير
يُفحص قبل العلاقة لا بعدها، لأن `0 == k × 0` صحيحة ولا تعني شيئًا.

## §6.5 حقائق الهدف تُقرأ من الـdump

`--g-dma` و`--lost` و`--abi-*` صارت **توقّعات**. القيم الحاملة تُستخرج من
بايتات ترويسة ABI v9 (28 كلمة، little-endian) ويُقارن التوقّع بها. ولا يستطيع
المشغّل توليد `"source": "dump_header"` بالكتابة: الحقل يُكتب هكذا فقط إذا
فُكّت ترويسة فعلًا، ويحمل `from_sha256` الذي يجب أن يساوي الـdump المشحون.

وترتيب الإغلاق مُلزِم: إيقاف الالتقاط ← جلب S2 ← ثم التجزئة. artifact
يُجزَّأ وهو ما زال يُكتب يثبّت **بادئة** الدليل ويسمّيها الدليل.

## §7-bis شاهدان مستقلان

الـharness يقرّر صلاحية المحاولة من دفاتره:

```c
pool_drain();                  /* اقطف ما انتهى */
n = p->inflight;               /* اقرأ كم بقي */
ioctl(fd, USBDEVFS_CONTROL);   /* أطلق */
```

لا شيء يغلق الفجوة بين السطرين الثاني والثالث. نقل Bulk OUT قد يكتمل فيها،
فتُسجَّل المحاولة `valid=true, inflight_at_trigger=1` بينما لم يكن على السلك
شيء معلّق لحظة وصول SETUP. الـharness لا يستطيع كشف ذلك لأنه هو المخطئ،
والخطأ في الاتجاه الذي يجعل النتيجة السالبة تبدو أقوى.

```text
wire     usbmon_verify.py    عمق معاد اشتقاقه من التقاط لا يتحكّم به الـharness
holder   holder_merge.py     عمق قائمة الـgadget نفسه عند الهدم
```

وهما **ادعاءان مختلفان ولا يُغني أحدهما عن الآخر**: الأول عن URB معلّق عند
سائق متحكّم المضيف، والثاني عن request ما زال في قائمة function driver — وهذا
الثاني هو ما تقوم عليه R1. الخلاف في أيّهما **رفض**، لا تصحيح.

## §7 usbmon: علاقة ترتيب، لا تجاور

اعتراضك هنا صحيح ومُدمج: ظهور الاثنين في نفس الملف لا يثبت شيئًا.

```sh
cat /sys/kernel/debug/usb/usbmon/<bus>u > session.mon   # نصّي، أسهل تفكيكًا
# أو tcpdump -i usbmon<bus> -w session.pcap
```

الـharness يستخرج **علاقة ترتيب صريحة** لكل محاولة:

```text
لكل محاولة n، يجب أن يوجد في السجل:
    S Bo:<bus>:<dev>:2   لكل URB مقدَّم        (submit، bulk out)
    S Co:<bus>:<dev>:0   للـSETUP              (submit، control out)
    C Bo:...             الإكمالات

والشرط القابل للفحص:
    ts(S Co ... 0900 0000 0000 0000)
        يقع بين ts(آخر S Bo) وts(أول C Bo يلي الـSETUP)
    وعدد (S Bo بلا C Bo مقابل) لحظة الـSETUP  >=  1
```

أي أن الـharness يعيد اشتقاق `inflight_at_trigger` **من الـcapture مستقلًا**
عن عدّاده الداخلي. اختلافهما = المحاولة `invalid` بسبب `not_outstanding`، ولا
تُحتسب. هذا هو الشاهد المستقل الذي يمنع أن يكذب العدّاد على نفسه.

**usbmon قناة تحقق لا مصدر عدّ.** سترى فيه traffic التعداد وطلبات نظام
التشغيل، ولو عددت منه لضخّمت المقام.

---

## §8 الحساسية: positive control مزدوج، قبل الحملة

يُنفَّذ في pre-flight لكل إقلاع، **لا أثناء الحملة**:

```text
لـ N من الـtriggers الخام (N >= 20):
    سلّح Bulk OUT بعمق كامل
    تحقق من inflight >= 1
    أصدر SET_CONFIGURATION(0) خامًا
    أعد التزامن
اقرأ الـdump

الشرط:
    N  ==  عدد سجلات المرشّحين بفئة CAUSE_SYNC_OWNER
    lost == 0
```

المساواة تثبت حساسية السلسلة كاملة — harness → wire → UDC → observer → dump →
P4 — **دون انتظار حدوث الظاهرة**. وهي التي تمنح `SENSITIVE` التي يشترطها الحكم
السلبي.

والـvalidator يشتق الحكم من العدّين ولا يقبل إعلانه:

```text
SENSITIVE  ⟺  issued == observed  ∧  issued >= 1
```

استبعد من نافذة القياس: traffic التعداد، وport resets — الـreset يولّد أحداث
stop بفئة مختلفة عبر `dwc2_hsotg_disconnect() → kill_all_requests()` فيلوّث
المقام.

---

## §8.1 تجميد الـepoch بلا إعادة كتابة hashes

المسار المجمد لا يقبل أن ينسخ المشغّل قيم sha256 واحدةً واحدة. الأداة
`pipeline/freeze_epoch.py` تقرأ قائمة المفاتيح من
`r1a_manifest.py::EPOCH_ARTIFACTS`، وتأخذ مسارات الأدوات المحلية الفعلية من
`r1_gate_v9_1.py::runtime_epoch_local_files()` حيث المسارات مبنية من
`module.__file__`. الباقي فقط يصبح paths خارجية مطلوبة (`image`,
`observer_patch`, `harness`).

```text
actual files -> freeze_epoch.py -> epoch.json -> r1a_host --epoch-json
```

خلط `--epoch-json` مع `--epoch-id` أو أي `--sha-*` يُجهض. والـharness يعيد
تجزئة `/proc/self/exe` ويطابقها مع `epoch.artifacts.harness`.

## §9 النوافذ المستبعدة

```json
"excluded_windows": [
  {"reason": "enumeration", "t0": "...", "t1": "..."},
  {"reason": "port_reset",  "t0": "...", "t1": "..."}
]
```

أي محاولة يقع `t_trigger_utc` داخل نافذة مستبعدة تُسجَّل
`invalid_reason: "in_excluded_window"`. لا تُحذف — تبقى في السجل.

---

## §10 ما يُخرجه الـharness

ملف manifest v2 واحد لكل جلسة؛ المرجع التنفيذي للمخطط هو `pipeline/r1a_manifest.py` و`pipeline/README.md`. الحقول
التي يملكها الـharness حصرًا:

```text
session.boot_id                       من اللوحة
session.host.*                        نواة المضيف وbus الـusbmon (لا libusb في التنفيذ)
preflight.sensitivity.*               عدّا الاقتران والنوافذ المستبعدة
attempts[].*                          كل محاولة، صالحة أو لا، بسببها
denominator.*                         يُملأ، ثم يُعاد حسابه بالـvalidator
artifacts.*                           المسارات وsha256 لكل من dump/usbmon/log
```

**المقام = triggers الصادرة من الـharness فقط.** لا من usbmon، ولا من عدّادات
النواة — تلك `endpoint_stop_opportunities` ووحدتها مرفوضة في الـmanifest برسالة
صريحة.

---

## §11 أوضاع تُوجب الإجهاض لا التدهور

الـharness يتوقف ويسجّل، ولا يكمل «على أمل»:

```text
ep2 لا يطابق ما أكّده الجانب الجهازي        mismatch = بيانات عن نقطة أخرى
wIndex أو wLength غير صفر لـSET_CONFIG      TRIG_NONE، محاولات ضائعة صامتًا
lost > 0 في الـdump                          الجلسة لاغية لأغراض السلبية
caps تغيّرت بين الـpreflight والإغلاق        الهدف تبدّل تحت القياس
reset_generation تغيّر أثناء الجلسة          خلط حلقتين
sensitivity < SENSITIVE في الـpreflight      لا تبدأ الحملة أصلًا
أي فشل في القطف غير EAGAIN                   حالة URB غير معروفة
```

---

## §12 ما لا يفعله هذا الـharness

```text
لا يقرر R1                    ذلك عمل P4 على الـdump
لا يعدّ من usbmon             قناة تحقق فقط
لا يصدر أحكامًا سببية          الـobserver وحده يصنّف السببية داخل النواة
لا يعدّل الأداة أثناء الحملة   أي تعديل = epoch جديد وقاعدة الهدم
لا يفترض i.i.d.               تعدد الإقلاعات عبر الجلسات هو ما يخفف الارتباط
```

---

## ملحق: ما تحقق في هذه الجولة

```text
devio.c:881-938   check_ctrlrecip بلا case USB_RECIP_DEVICE      مُثبت
devio.c:1180      do_proc_control يمرر usb_ctrlrequest حرفيًا     مُثبت
devio.c كله       لا اعتراض على SET_CONFIGURATION بالاسم          مُثبت بالبحث
usbdevice_fs.h    U,0 CONTROL / U,10 SUBMITURB / U,13 REAPNDELAY  مُثبت
                  U,11 DISCARDURB / U,15 CLAIM / U,16 RELEASE
                  U,5 SETCONFIGURATION ← الممنوع، مُعرَّف ومُسمّى
message.c:2124/2209, 1619/1649   التعطيل يسبق الطلب              مُثبت سابقًا
```

**حالة التنفيذ:** `r1a_host` وأدوات الشاهد/الـgate منفذة ومختبرة دون USB حقيقي؛ تشغيل R1A على لوحة DWC2 ما زال `NOT EXECUTED`.
