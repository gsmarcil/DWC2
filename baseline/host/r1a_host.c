/*
 * r1a_host -- host side of the DWC2 R1A campaign harness.
 * TEST-ONLY. Implements R1A-HARNESS-SPEC.md against the campaign pin
 * f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8.
 *
 * WHY RAW usbfs AND NOT libusb
 * ----------------------------
 * The experiment needs a Bulk OUT transfer still outstanding at the instant
 * the control request reaches the device. Every convenience path destroys
 * that precondition before sending anything:
 *
 *   drivers/usb/core/message.c:2124   usb_disable_device(dev, 1);
 *   drivers/usb/core/message.c:2209   usb_control_msg_send(... SET_CONFIGURATION ...)
 *
 *   drivers/usb/core/message.c:1619   usb_disable_interface(dev, iface, false);
 *   drivers/usb/core/message.c:1649-1650  usb_control_msg_send(... SET_INTERFACE ...)
 *
 * The teardown precedes the transfer in both. libusb_set_configuration() and
 * USBDEVFS_SETCONFIGURATION (U,5) both land there, so neither may be used.
 *
 * The raw path does reach the device untouched:
 *
 *   drivers/usb/core/devio.c:908   switch (requesttype & USB_RECIP_MASK) {
 *                                  case USB_RECIP_ENDPOINT: ...
 *                                  case USB_RECIP_INTERFACE: ...
 *                                  }
 *
 * There is no case for USB_RECIP_DEVICE, so a SET_CONFIGURATION
 * (bmRequestType 0x00) falls through with ret = 0 and is allowed; and
 * USB_REQ_SET_CONFIGURATION appears nowhere in devio.c, so nothing intercepts
 * it by name. do_proc_control() (devio.c:1180) then hands the caller's exact
 * usb_ctrlrequest to a URB.
 *
 * Consequence, deliberate: usbcore never sees the request, so the host's
 * dev->actconfig goes stale. Resynchronisation is explicit (see resync()), and
 * must itself use the raw path -- calling the convenience API on a device the
 * host still believes is configured is undefined.
 *
 * HOST ENDPOINT STATE AFTER A RAW RECONFIGURE
 * -------------------------------------------
 * Skipping usb_set_configuration() also skips what it does to the HOST side
 * of the endpoint:
 *
 *   drivers/usb/core/message.c:1819   usb_enable_interface(dev, intf, true);
 *   drivers/usb/core/message.c:1520-1521  if (reset_ep) usb_hcd_reset_endpoint(dev, ep);
 *
 * The DEVICE side resets itself regardless, when the composite layer
 * re-enables the endpoint:
 *
 *   drivers/usb/dwc2/gadget.c:5162    for non control endpoints, set PID to D0
 *   drivers/usb/dwc2/gadget.c:5164    epctrl |= DXEPCTL_SETD0PID;
 *
 * So after a raw restore the gadget is on DATA0 and the host is wherever it
 * left off. A Bulk OUT that then never moves is not a null result, it is a
 * broken instrument, and it would look exactly like one.
 *
 * The repair does not need the forbidden call. USBDEVFS_RESETEP (U,3) reaches
 *
 *   drivers/usb/core/devio.c:1396     static int proc_resetep(...)
 *   drivers/usb/core/devio.c:1410     usb_reset_endpoint(ps->dev, ep);
 *
 * and usb_reset_endpoint() is documented at message.c:1373-1374 as resetting
 * "any host-side endpoint state such as the toggle bit, sequence number or
 * current window". No configuration change, no URB teardown anywhere on that
 * path; check_reset_of_active_ep() (devio.c:1382) only dev_warn()s. It is
 * called between attempts, the one moment when nothing is required to be
 * outstanding, so it cannot destroy the precondition under study.
 *
 * Whether it is NEEDED cannot be settled by reading source:
 * usb_hcd_reset_endpoint() (hcd.c:1990) dispatches to
 * hcd->driver->endpoint_reset where the controller supplies one and clears
 * the toggle itself otherwise, so the answer is a property of the operator's
 * host controller. --preflight-rearm settles it by measurement, in two arms,
 * before any attempt is counted.
 *
 *   cc -O2 -Wall -Wextra -Werror -o r1a_host r1a_host.c
 */
#define _GNU_SOURCE

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/utsname.h>

#include <linux/usbdevice_fs.h>
#include <linux/usb/ch9.h>

#define MAX_DEPTH        256
#define MAX_ATTEMPTS     100000
#define MAX_WINDOWS      512
#define DESC_BUF         4096
#define TSLEN            64
#define REARM_MAX_CYCLES 64
#define REARM_PROBE_TAG  ((void *)(uintptr_t)0xC0DE1AUL)

/* ------------------------------------------------------------------ sha256 */
/* Self-contained so the tool has no dependency and cannot silently disagree
 * with whatever sha256sum happens to be on the operator's machine. */
typedef struct {
	uint32_t h[8];
	uint64_t len;
	uint8_t buf[64];
	size_t n;
} sha256_t;

static const uint32_t K256[64] = {
	0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,
	0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
	0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,
	0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
	0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,
	0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
	0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,
	0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
	0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,
	0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
	0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
};

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void sha256_block(sha256_t *s, const uint8_t *p)
{
	uint32_t w[64], a, b, c, d, e, f, g, h, t1, t2;
	int i;

	for (i = 0; i < 16; i++)
		w[i] = (uint32_t)p[i * 4] << 24 | (uint32_t)p[i * 4 + 1] << 16 |
		       (uint32_t)p[i * 4 + 2] << 8 | p[i * 4 + 3];
	for (; i < 64; i++) {
		uint32_t s0 = ROR(w[i-15],7) ^ ROR(w[i-15],18) ^ (w[i-15] >> 3);
		uint32_t s1 = ROR(w[i-2],17) ^ ROR(w[i-2],19) ^ (w[i-2] >> 10);
		w[i] = w[i-16] + s0 + w[i-7] + s1;
	}
	a=s->h[0]; b=s->h[1]; c=s->h[2]; d=s->h[3];
	e=s->h[4]; f=s->h[5]; g=s->h[6]; h=s->h[7];
	for (i = 0; i < 64; i++) {
		t1 = h + (ROR(e,6)^ROR(e,11)^ROR(e,25)) + ((e&f)^(~e&g))
		     + K256[i] + w[i];
		t2 = (ROR(a,2)^ROR(a,13)^ROR(a,22)) + ((a&b)^(a&c)^(b&c));
		h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
	}
	s->h[0]+=a; s->h[1]+=b; s->h[2]+=c; s->h[3]+=d;
	s->h[4]+=e; s->h[5]+=f; s->h[6]+=g; s->h[7]+=h;
}

static void sha256_init(sha256_t *s)
{
	static const uint32_t iv[8] = {
		0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
		0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
	memcpy(s->h, iv, sizeof(iv));
	s->len = 0;
	s->n = 0;
}

static void sha256_update(sha256_t *s, const void *data, size_t len)
{
	const uint8_t *p = data;

	s->len += len;
	while (len) {
		size_t take = 64 - s->n;

		if (take > len)
			take = len;
		memcpy(s->buf + s->n, p, take);
		s->n += take;
		p += take;
		len -= take;
		if (s->n == 64) {
			sha256_block(s, s->buf);
			s->n = 0;
		}
	}
}

static void sha256_final(sha256_t *s, char out[65])
{
	uint64_t bits = s->len * 8;
	uint8_t pad = 0x80;
	int i;

	sha256_update(s, &pad, 1);
	pad = 0;
	while (s->n != 56)
		sha256_update(s, &pad, 1);
	for (i = 7; i >= 0; i--) {
		uint8_t b = (bits >> (i * 8)) & 0xff;
		sha256_update(s, &b, 1);
	}
	for (i = 0; i < 8; i++)
		sprintf(out + i * 8, "%08x", s->h[i]);
	out[64] = 0;
}

/* Returns 0 and fills out[65]; -1 if the file cannot be read. */
static int sha256_file(const char *path, char out[65])
{
	uint8_t b[65536];
	sha256_t s;
	FILE *f = fopen(path, "rb");
	size_t n;

	if (!f)
		return -1;
	sha256_init(&s);
	while ((n = fread(b, 1, sizeof(b), f)) > 0)
		sha256_update(&s, b, n);
	if (ferror(f)) {
		fclose(f);
		return -1;
	}
	fclose(f);
	sha256_final(&s, out);
	return 0;
}

static bool sha256_text_ok(const char *s)
{
	unsigned i;
	if (!s || strlen(s) != 64)
		return false;
	for (i = 0; i < 64; i++)
		if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f')))
			return false;
	return true;
}

/* --------------------------------------------------------------- utilities */

static volatile sig_atomic_t stop_flag;
static void on_sig(int s) { (void)s; stop_flag = 1; }

static void die(const char *fmt, ...)
{
	va_list ap;

	fputs("ABORT: ", stderr);
	va_start(ap, fmt);
	vfprintf(stderr, fmt, ap);
	va_end(ap);
	fputc('\n', stderr);
	exit(2);
}

/* ---------------------------------------------------------- epoch JSON */
/*
 * freeze_epoch.py emits a deliberately tiny JSON object: epoch_id plus an
 * artifacts object of plain strings.  The host consumes that object directly
 * so no sha256 value is retyped on the command line.  This is not a general
 * JSON parser: values with escapes are refused, duplicate keys are refused,
 * and every hash is validated after extraction.
 */
static char *read_small_text_file(const char *path)
{
	FILE *f;
	long n;
	char *buf;

	f = fopen(path, "rb");
	if (!f)
		die("cannot open epoch JSON %s: %s", path, strerror(errno));
	if (fseek(f, 0, SEEK_END) || (n = ftell(f)) < 0 || n > (1 << 20)) {
		fclose(f);
		die("epoch JSON %s is unreadable or larger than 1 MiB", path);
	}
	if (fseek(f, 0, SEEK_SET)) {
		fclose(f);
		die("cannot rewind epoch JSON %s", path);
	}
	buf = malloc((size_t)n + 1);
	if (!buf) {
		fclose(f);
		die("out of memory reading epoch JSON");
	}
	if (n && fread(buf, 1, (size_t)n, f) != (size_t)n) {
		free(buf);
		fclose(f);
		die("short read from epoch JSON %s", path);
	}
	buf[n] = '\0';
	fclose(f);
	return buf;
}

static int json_unique_plain_string(const char *json, const char *key,
				    char *out, size_t outsz)
{
	char pattern[128];
	const char *p = json, *value = NULL;
	size_t plen, n;
	unsigned hits = 0;

	if (snprintf(pattern, sizeof(pattern), "\"%s\"", key) >=
	    (int)sizeof(pattern))
		return -1;
	plen = strlen(pattern);
	while ((p = strstr(p, pattern)) != NULL) {
		const char *q = p + plen;

		while (*q && isspace((unsigned char)*q))
			q++;
		if (*q == ':') {
			hits++;
			value = q + 1;
		}
		p += plen;
	}
	if (hits != 1 || !value)
		return -1;
	while (*value && isspace((unsigned char)*value))
		value++;
	if (*value++ != '"')
		return -1;
	for (n = 0; value[n] && value[n] != '"'; n++) {
		unsigned char c = (unsigned char)value[n];
		if (c < 0x20 || c == '\\' || n + 1 >= outsz)
			return -1;
		out[n] = (char)c;
	}
	if (value[n] != '"')
		return -1;
	out[n] = '\0';
	return 0;
}

static const char *owned_copy(const char *s)
{
	char *p = strdup(s);
	if (!p)
		die("out of memory storing epoch field");
	return p;
}


/*
 * The manifest schema requires \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z.
 * Every field is clamped to its own width so the result cannot exceed the
 * buffer -- the compiler cannot otherwise bound struct tm and rejects the
 * format as possibly truncating.
 */
static void iso_now(char out[TSLEN])
{
	struct timespec ts;
	struct tm tm;
	int year, mon, day, hh, mm, ss;
	unsigned ms;

	clock_gettime(CLOCK_REALTIME, &ts);
	gmtime_r(&ts.tv_sec, &tm);

	year = tm.tm_year + 1900;
	if (year < 0)
		year = 0;
	if (year > 9999)
		year = 9999;
	mon = (tm.tm_mon + 1) % 100;
	day = tm.tm_mday % 100;
	hh = tm.tm_hour % 100;
	mm = tm.tm_min % 100;
	ss = tm.tm_sec % 100;
	ms = (unsigned)((ts.tv_nsec / 1000000) % 1000);

	snprintf(out, TSLEN, "%04d-%02d-%02dT%02d:%02d:%02d.%03uZ",
		 year, mon, day, hh, mm, ss, ms);
}

static void msleep(unsigned ms)
{
	struct timespec t = { ms / 1000, (long)(ms % 1000) * 1000000L };

	nanosleep(&t, NULL);
}

/* JSON string escape, enough for the fields this tool emits. */
static void jstr(FILE *f, const char *s)
{
	fputc('"', f);
	for (; s && *s; s++) {
		if (*s == '"' || *s == '\\')
			fprintf(f, "\\%c", *s);
		else if ((unsigned char)*s < 0x20)
			fprintf(f, "\\u%04x", *s);
		else
			fputc(*s, f);
	}
	fputc('"', f);
}

/* ------------------------------------------------- device and descriptors */

struct target {
	char path[256];
	int fd;
	unsigned busnum, devnum;
	uint16_t vid, pid;
	int intf;              /* interface owning the bulk OUT endpoint */
	uint8_t ep_out;        /* bEndpointAddress, read from descriptors */
	uint16_t ep_mps;
	uint8_t cfg_value;     /* bConfigurationValue to restore after a trigger */
};

/*
 * Parse the descriptor blob usbfs hands back when the node is read: device
 * descriptor, then each configuration in full. Finds the first bulk OUT
 * endpoint and the interface that owns it. The endpoint address is never
 * assumed -- the spec requires it to match what the device side confirmed
 * with FUNCTIONFS_ENDPOINT_DESC, and a mismatch aborts the run.
 */
static int parse_descriptors(struct target *t, const uint8_t *d, size_t len)
{
	size_t i = 0;
	int cur_intf = -1;
	uint8_t cur_cfg = 0;
	bool found = false;

	while (i + 2 <= len) {
		uint8_t blen = d[i], btype = d[i + 1];

		if (blen < 2 || i + blen > len)
			break;
		switch (btype) {
		case USB_DT_DEVICE:
			if (blen >= 18) {
				t->vid = (uint16_t)(d[i + 8] | d[i + 9] << 8);
				t->pid = (uint16_t)(d[i + 10] | d[i + 11] << 8);
			}
			break;
		case USB_DT_CONFIG:
			if (blen >= 9)
				cur_cfg = d[i + 5];   /* bConfigurationValue */
			break;
		case USB_DT_INTERFACE:
			if (blen >= 9)
				cur_intf = d[i + 2];  /* bInterfaceNumber */
			break;
		case USB_DT_ENDPOINT:
			if (blen >= 7 && !found) {
				uint8_t addr = d[i + 2], attr = d[i + 3];

				if (!(addr & USB_DIR_IN) &&
				    (attr & USB_ENDPOINT_XFERTYPE_MASK)
				    == USB_ENDPOINT_XFER_BULK) {
					t->ep_out = addr;
					t->ep_mps = (uint16_t)(d[i + 4] |
							       d[i + 5] << 8);
					t->intf = cur_intf;
					t->cfg_value = cur_cfg;
					found = true;
				}
			}
			break;
		default:
			break;
		}
		i += blen;
	}
	return found ? 0 : -1;
}

static int open_target(struct target *t, const char *path)
{
	uint8_t buf[DESC_BUF];
	ssize_t n;
	int fd;

	fd = open(path, O_RDWR);
	if (fd < 0)
		return -1;

	n = read(fd, buf, sizeof(buf));
	if (n < 18) {
		close(fd);
		return -1;
	}
	memset(t, 0, sizeof(*t));
	t->intf = -1;
	if (parse_descriptors(t, buf, (size_t)n) < 0) {
		close(fd);
		return -1;
	}
	snprintf(t->path, sizeof(t->path), "%s", path);
	t->fd = fd;
	return 0;
}

/* Scan /dev/bus/usb for a device matching vid:pid. */
static int find_target(struct target *t, uint16_t vid, uint16_t pid)
{
	char bus[512], dev[1024];
	struct dirent *db, *dd;
	DIR *b, *d;
	int rc = -1;

	b = opendir("/dev/bus/usb");
	if (!b)
		return -1;
	while (rc && (db = readdir(b))) {
		if (!isdigit((unsigned char)db->d_name[0]))
			continue;
		snprintf(bus, sizeof(bus), "/dev/bus/usb/%s", db->d_name);
		d = opendir(bus);
		if (!d)
			continue;
		while ((dd = readdir(d))) {
			struct target c;

			if (!isdigit((unsigned char)dd->d_name[0]))
				continue;
			snprintf(dev, sizeof(dev), "%s/%s", bus, dd->d_name);
			if (open_target(&c, dev) < 0)
				continue;
			if (c.vid == vid && c.pid == pid) {
				c.busnum = (unsigned)atoi(db->d_name);
				c.devnum = (unsigned)atoi(dd->d_name);
				*t = c;
				rc = 0;
				break;
			}
			close(c.fd);
		}
		closedir(d);
	}
	closedir(b);
	return rc;
}

/* ------------------------------------------------------------ raw control */

/*
 * The only way a trigger leaves this program. wLength is fixed at zero and
 * there is no data stage: dwc2_r1_classify_setup() requires !w_length for
 * both SET_CONFIGURATION and SET_INTERFACE, and a non-zero value yields
 * TRIG_NONE -- no denominator, and the attempt is lost silently. Refusing
 * here is cheaper than discovering it in the dump.
 */
static int raw_ctrl(int fd, uint8_t bmRequestType, uint8_t bRequest,
		    uint16_t wValue, uint16_t wIndex, unsigned timeout_ms)
{
	struct usbdevfs_ctrltransfer ct;

	memset(&ct, 0, sizeof(ct));
	ct.bRequestType = bmRequestType;
	ct.bRequest = bRequest;
	ct.wValue = wValue;
	ct.wIndex = wIndex;
	ct.wLength = 0;
	ct.timeout = timeout_ms;
	ct.data = NULL;
	return ioctl(fd, USBDEVFS_CONTROL, &ct);
}

/* ------------------------------------------------------------- URB pool */

struct pool {
	struct usbdevfs_urb urb[MAX_DEPTH];
	unsigned char *buf[MAX_DEPTH];
	bool live[MAX_DEPTH];
	unsigned depth, xfer_len;
	unsigned inflight;
	unsigned long long submitted, completed, errors;
	int last_errno;
};

static int pool_init(struct pool *p, unsigned depth, unsigned xfer_len)
{
	unsigned i;

	memset(p, 0, sizeof(*p));
	p->depth = depth;
	p->xfer_len = xfer_len;
	for (i = 0; i < depth; i++) {
		p->buf[i] = calloc(1, xfer_len);
		if (!p->buf[i])
			return -1;
	}
	return 0;
}

static void pool_free(struct pool *p)
{
	unsigned i;

	for (i = 0; i < p->depth; i++)
		free(p->buf[i]);
}

static int submit_one(int fd, struct pool *p, unsigned i, uint8_t ep)
{
	struct usbdevfs_urb *u = &p->urb[i];

	memset(u, 0, sizeof(*u));
	u->type = USBDEVFS_URB_TYPE_BULK;
	u->endpoint = ep;
	u->buffer = p->buf[i];
	u->buffer_length = (int)p->xfer_len;
	u->usercontext = (void *)(uintptr_t)i;
	if (ioctl(fd, USBDEVFS_SUBMITURB, u) < 0) {
		p->last_errno = errno;
		return -1;
	}
	p->live[i] = true;
	p->inflight++;
	p->submitted++;
	return 0;
}

/* Fill the pipe. Returns how many were accepted. */
static unsigned pool_arm(int fd, struct pool *p, uint8_t ep)
{
	unsigned i, n = 0;

	for (i = 0; i < p->depth; i++)
		if (!p->live[i] && submit_one(fd, p, i, ep) == 0)
			n++;
	return n;
}

/*
 * Reap everything already finished, without blocking, and return how many.
 * EAGAIN is the only errno that means "nothing ready"; anything else leaves
 * the URB state unknown and is escalated by the caller rather than ignored.
 */
static int pool_drain(int fd, struct pool *p)
{
	struct usbdevfs_urb *done;
	int reaped = 0;

	for (;;) {
		if (ioctl(fd, USBDEVFS_REAPURBNDELAY, &done) < 0) {
			if (errno == EAGAIN)
				return reaped;
			p->last_errno = errno;
			return -1;
		}
		unsigned i = (unsigned)(uintptr_t)done->usercontext;

		if (i < p->depth && p->live[i]) {
			p->live[i] = false;
			if (p->inflight)
				p->inflight--;
		}
		p->completed++;
		if (done->status != 0) {
			p->errors++;
			p->last_errno = -done->status;
		}
		reaped++;
	}
}

static void pool_discard_all(int fd, struct pool *p)
{
	unsigned i;

	for (i = 0; i < p->depth; i++)
		if (p->live[i])
			ioctl(fd, USBDEVFS_DISCARDURB, &p->urb[i]);
	/* A discarded URB still has to be reaped before its slot is free. */
	for (i = 0; i < 64 && p->inflight; i++) {
		if (pool_drain(fd, p) < 0)
			break;
		if (p->inflight)
			msleep(2);
	}
	for (i = 0; i < p->depth; i++)
		p->live[i] = false;
	p->inflight = 0;
}

/* --------------------------------------- observer dump header (ABI v9) */

/*
 * WHY THIS PARSER EXISTS
 *
 * Two separate failures were being papered over by taking target facts from
 * the command line.
 *
 * The first is fail-open: a manifest that says
 *
 *     "caps": {"g_dma": 1, "g_dma_desc": 0, "source": "dump_header"}
 *
 * while nothing ever opened a dump is a false statement about provenance. A
 * run against a DDMA target with lost records could produce exactly that JSON
 * if the operator typed the expected numbers, and every downstream check
 * would pass. So the values are read from the dump bytes and the command line
 * is demoted to an expectation that must match.
 *
 * The second is the denominator. The observer's counters are cumulative, so
 * the final value contains everything the session did before the campaign --
 * the sensitivity burst and the re-arm pre-flight both fire real triggers. In
 * cfgn mode it is worse than that: the restore between attempts is itself a
 * SET_CONFIGURATION with a non-zero wValue, which
 * dwc2_r1_classify_setup() (gadget.c) classifies as
 * DWC2_R1_TRIG_SET_CONFIG_NONZERO -- the very field that mode uses as its
 * denominator. Reading the counter once at the end cannot separate any of
 * that from the campaign, so it is read three times and only differences are
 * used.
 */
#define R1_HDR_MAGIC   0x424F3152u
#define R1_HDR_WORDS   28
#define R1_HDR_BYTES   (R1_HDR_WORDS * 4)
#define R1_CAP_DMA     (1u << 0)
#define R1_CAP_DDMA    (1u << 1)

/* Field order IS the ABI. These indices mirror HDR_NAMES in dwc2_r1_v9.py;
 * abi_check.py in the observer package is what proves the two agree. */
enum {
	R1H_MAGIC = 0, R1H_VERSION, R1H_HEADER_SIZE, R1H_RECORD_SIZE,
	R1H_COUNT, R1H_LOST, R1H_NEXT_SEQ, R1H_CAPS_FLAGS,
	R1H_GSNPSID, R1H_GHWCFG2, R1H_GHWCFG3, R1H_GHWCFG4,
	R1H_RESET_GENERATION,
	R1H_SETUP_CFG0, R1H_SETUP_CFGN, R1H_SETUP_INTF,
	R1H_CAND_CFG0, R1H_CAND_CFGN, R1H_CAND_INTF,
	R1H_CAND_DELAYED_DISABLE, R1H_OVERLAP_COUNT, R1H_DELAYED_OPEN,
	R1H_DELAYED_CLOSED, R1H_CAUSAL_SYNC, R1H_CAUSAL_UNATTRIBUTED,
	R1H_SNAPSHOT_ATOMIC, R1H_CAND_DELAYED_DEQUEUE, R1H_RESERVED1
};

struct r1_snapshot {
	const char *label;         /* S0 / S1 / S2 */
	const char *when;          /* before_sensitivity / ... */
	char path[256];
	char sha[65];
	char utc[TSLEN];
	bool ok;
	const char *err;
	uint32_t w[R1_HDR_WORDS];
};

static uint32_t rd32(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
	       ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/*
 * Run the operator's fetch command and parse what it produced. "%s" in the
 * command is the destination path; without it the output is redirected there.
 * The command is the operator's own (typically ssh to the target), so the
 * only thing checked here is that it produced a header this build understands.
 */
static bool snapshot_take(struct r1_snapshot *sn, const char *cmd,
			  const char *dir, unsigned n)
{
	char line[1024];
	uint8_t hdr[R1_HDR_BYTES];
	const char *pct = strstr(cmd, "%s");
	FILE *f;
	size_t got;
	int rc;

	snprintf(sn->path, sizeof(sn->path), "%s/r1-snapshot-%u-%s.bin",
		 dir, n, sn->label);
	iso_now(sn->utc);
	sn->ok = false;
	sn->err = NULL;

	if (pct) {
		if (snprintf(line, sizeof(line), "%.*s%s%s",
			     (int)(pct - cmd), cmd, sn->path, pct + 2)
		    >= (int)sizeof(line)) {
			sn->err = "snapshot command too long";
			return false;
		}
	} else if (snprintf(line, sizeof(line), "%s > '%s'", cmd, sn->path)
		   >= (int)sizeof(line)) {
		sn->err = "snapshot command too long";
		return false;
	}

	rc = system(line);
	if (rc != 0) {
		sn->err = "snapshot command failed";
		return false;
	}
	f = fopen(sn->path, "rb");
	if (!f) {
		sn->err = "snapshot command produced no file";
		return false;
	}
	got = fread(hdr, 1, sizeof(hdr), f);
	fclose(f);
	if (got != sizeof(hdr)) {
		sn->err = "snapshot shorter than one ABI v9 header";
		return false;
	}
	for (unsigned i = 0; i < R1_HDR_WORDS; i++)
		sn->w[i] = rd32(hdr + 4 * i);
	if (sn->w[R1H_MAGIC] != R1_HDR_MAGIC) {
		sn->err = "snapshot has the wrong magic";
		return false;
	}
	if (sn->w[R1H_VERSION] != 9 ||
	    sn->w[R1H_HEADER_SIZE] != R1_HDR_BYTES ||
	    sn->w[R1H_RECORD_SIZE] != 80) {
		sn->err = "snapshot is not ABI v9 / header 112 / record 80";
		return false;
	}
	if (sha256_file(sn->path, sn->sha) < 0) {
		sn->err = "snapshot could not be hashed";
		return false;
	}
	sn->ok = true;
	return true;
}

/* ------------------------------------------------- host endpoint re-arm */

enum rearm_method { REARM_NONE = 0, REARM_RESETEP = 1, REARM_CLEAR_HALT = 2 };

static const char *rearm_method_name(int m)
{
	switch (m) {
	case REARM_RESETEP:    return "resetep";
	case REARM_CLEAR_HALT: return "clear_halt";
	default:               return "none";
	}
}

/*
 * Apply the host-side reset chosen for this run. Both ioctls take the raw
 * bEndpointAddress; findintfep() (devio.c:1341) rejects anything outside
 * USB_DIR_IN|0xf, and checkintf() (devio.c:1326) wants the interface claimed,
 * which is why this is called after the CLAIMINTERFACE in resync_ex() and not
 * before it.
 */
static int rearm_reset_apply(int fd, uint8_t ep, int method)
{
	unsigned e = ep;

	switch (method) {
	case REARM_RESETEP:
		return ioctl(fd, USBDEVFS_RESETEP, &e);
	case REARM_CLEAR_HALT:
		/* proc_clearhalt() ends in usb_clear_halt(), which calls
		 * usb_reset_endpoint() too (message.c:1389) -- but only after
		 * putting a real CLEAR_FEATURE on the wire. That is a
		 * device-visible request the frozen protocol did not ask for,
		 * so it is available and not the default. */
		return ioctl(fd, USBDEVFS_CLEAR_HALT, &e);
	default:
		return 0;
	}
}

struct rearm_cycle {
	unsigned n;
	char t0[TSLEN], t1[TSLEN];
	bool reenum;          /* device went away and had to be reopened */
	bool trigger_failed;  /* the cycle's own trigger never went out */
	int trigger_rc;
	bool submitted;
	bool reaped;
	int status;           /* first_bulk_completion_status */
	int actual_length;    /* bytes_after_rearm */
	bool progress;        /* REARM_DATA_PROGRESS */
};

struct rearm_arm {
	const char *label;
	int method;
	unsigned attempted, progress_ok, reenum, trigger_failed;
	struct rearm_cycle c[REARM_MAX_CYCLES];
};

struct rearm_pf {
	bool performed;
	unsigned cycles, probe_len, timeout_ms;
	struct rearm_cycle baseline;
	struct rearm_arm none, reset;
	const char *verdict;
	bool discriminating;
	int method_in_use;
};

/*
 * Derived, never asserted -- the same rule is re-implemented in
 * r1a_manifest.py, which recomputes it from the per-arm counts and ignores
 * the string in the file, exactly as it already does for sensitivity.verdict
 * and B_valid. Total by construction: every (N, R) pair lands somewhere.
 *
 * Only REARM_RESET_REQUIRED and REARM_NO_RESET_NEEDED let a campaign start.
 * REARM_NO_RESET_NEEDED is an honest non-result: it says this host controller
 * showed no desync, so the reset is kept as a precaution but the pre-flight
 * proves nothing about it and must not be cited as if it did.
 */
static const char *rearm_verdict(const struct rearm_pf *pf, bool *disc)
{
	unsigned C = pf->cycles;
	unsigned N = pf->none.progress_ok;
	unsigned R = pf->reset.progress_ok;

	*disc = false;
	if (!pf->performed)
		return "REARM_NOT_TESTED";
	if (!pf->baseline.progress)
		return "REARM_BASELINE_FAILED";
	if (C < 3)
		return "REARM_INDETERMINATE";
	if (R == C) {
		if (N == 0) {
			*disc = true;
			return "REARM_RESET_REQUIRED";
		}
		if (N == C)
			return "REARM_NO_RESET_NEEDED";
		return "REARM_INDETERMINATE";
	}
	if (N == C)
		return "REARM_RESET_HARMFUL";
	return "REARM_BROKEN";
}

static bool rearm_verdict_admits_campaign(const char *v)
{
	return !strcmp(v, "REARM_RESET_REQUIRED") ||
	       !strcmp(v, "REARM_NO_RESET_NEEDED");
}

/* ------------------------------------------- the measured denominator */

struct kwindow {
	bool enabled;
	const char *field_name;
	unsigned field_idx;
	const char *setup_field_name;
	unsigned setup_field_idx;
	struct r1_snapshot s0, s1, s2;   /* pre-sens, pre-campaign, post */
	bool consistent;
	const char *problem;             /* NULL while nothing is wrong */
	unsigned long delta_sens, delta_camp, expected;
	unsigned k;
	bool k_exact, relation_ok;
	/*
	 * A stable token beside the sentence. The sentence is for the
	 * operator; the token is what r1a_manifest.py compares against, so
	 * rewording a message can never silently change a verdict.
	 */
	const char *code;
};

/*
 * Everything below is a difference between two reads of the same counter, and
 * every read is authenticated by its own sha256. The absolute value is never
 * used, because it contains the sensitivity burst, the re-arm pre-flight, and
 * -- in cfgn mode -- one classified SETUP per restore.
 *
 * k is measured, not assumed: the sensitivity burst runs exactly the same
 * unit of work as a campaign attempt (do_attempt() then resync()), so
 * candidates-per-attempt measured there transfers to the campaign. It is only
 * meaningful if every sensitivity attempt was valid, otherwise the divisor
 * counts fewer attempts than the window contains.
 */
static void kwindow_derive(struct kwindow *kw, unsigned sens_issued,
			   unsigned sens_attempted, unsigned b_valid,
			   unsigned b_invalid)
{
	const struct r1_snapshot *a = &kw->s0, *b = &kw->s1, *c = &kw->s2;
	unsigned i;

	kw->code = "OK";
	kw->consistent = false;
	kw->relation_ok = false;
	kw->k_exact = false;
	kw->k = 0;
	kw->delta_sens = kw->delta_camp = kw->expected = 0;

	if (!kw->enabled) {
		kw->code = "NO_SNAPSHOTS";
		kw->problem = "no dump snapshots were taken";
		return;
	}
	if (!a->ok || !b->ok || !c->ok) {
		kw->code = "SNAPSHOT_PARSE";
		kw->problem = "at least one snapshot did not parse";
		return;
	}
	/* Same silicon, same observer instance, in all three. */
	for (i = R1H_GSNPSID; i <= R1H_GHWCFG4; i++)
		if (a->w[i] != b->w[i] || b->w[i] != c->w[i]) {
			kw->code = "TARGET_CHANGED";
		kw->problem = "the target changed between snapshots";
			return;
		}
	if (a->w[R1H_CAPS_FLAGS] != b->w[R1H_CAPS_FLAGS] ||
	    b->w[R1H_CAPS_FLAGS] != c->w[R1H_CAPS_FLAGS]) {
		kw->code = "CAPS_CHANGED";
		kw->problem = "caps_flags changed between snapshots";
		return;
	}
	if (a->w[R1H_RESET_GENERATION] != b->w[R1H_RESET_GENERATION] ||
	    b->w[R1H_RESET_GENERATION] != c->w[R1H_RESET_GENERATION]) {
		kw->code = "OBSERVER_RESET";
		kw->problem = "the observer was reset mid-session, so the "
			      "differences do not describe one run";
		return;
	}
	if (a->w[R1H_LOST] || b->w[R1H_LOST] || c->w[R1H_LOST]) {
		kw->code = "RECORDS_LOST";
		kw->problem = "the observer dropped records during the session";
		return;
	}
	if (a->w[R1H_SNAPSHOT_ATOMIC] != 1 || b->w[R1H_SNAPSHOT_ATOMIC] != 1 || c->w[R1H_SNAPSHOT_ATOMIC] != 1) {
		kw->code = "NOT_ATOMIC";
		kw->problem = "one or more S0/S1/S2 snapshots are not atomic";
		return;
	}
	if (b->w[kw->field_idx] < a->w[kw->field_idx] ||
	    c->w[kw->field_idx] < b->w[kw->field_idx]) {
		kw->code = "COUNTER_BACKWARDS";
		kw->problem = "the counter went backwards between snapshots";
		return;
	}
	kw->consistent = true;

	kw->delta_sens = b->w[kw->field_idx] - a->w[kw->field_idx];
	kw->delta_camp = c->w[kw->field_idx] - b->w[kw->field_idx];

	if (sens_issued == 0) {
		kw->code = "NO_SENS_ATTEMPT";
		kw->problem = "no sensitivity attempt to measure k from";
		return;
	}
	if (sens_attempted != sens_issued) {
		kw->code = "SENS_INVALID";
		kw->problem = "some sensitivity attempt was invalid, so the "
			      "window holds more work than the divisor counts";
		return;
	}
	if (kw->delta_sens % sens_issued) {
		kw->code = "K_NOT_INTEGRAL";
		kw->problem = "candidates per attempt is not a whole number, "
			      "so the two windows are not the same unit of work";
		return;
	}
	kw->k = (unsigned)(kw->delta_sens / sens_issued);
	if (kw->k < 1) {
		kw->code = "K_ZERO";
		kw->problem = "the sensitivity burst produced no candidates";
		return;
	}
	kw->k_exact = true;

	/*
	 * B = 0 first, and not as a formality: with no valid attempt the
	 * relation reads 0 == k x 0, which is true and means nothing. A
	 * negative result quoted against an empty denominator is the one
	 * failure this whole file exists to prevent.
	 */
	if (b_valid == 0) {
		kw->code = "NO_VALID_ATTEMPT";
		kw->problem = "no valid attempt, so there is no denominator";
		return;
	}

	kw->expected = (unsigned long)kw->k * b_valid;
	kw->relation_ok = (kw->delta_camp == kw->expected);
	if (!kw->relation_ok) {
		/*
		 * This is the defence against subtracting an attempt from B
		 * that the kernel still counted. The host can drop an attempt;
		 * nothing can drop the candidates it left in an aggregate
		 * counter. Rather than deciding by rule which invalid attempts
		 * are harmless -- it depends on the branch, since in cfgn mode
		 * even the restore of a non-firing attempt is a classified
		 * SETUP -- the arithmetic decides, per run.
		 */
		kw->code = "RELATION_BROKEN";
		kw->problem = b_invalid
			? "the campaign delta does not equal k x B_valid, and "
			  "the batch has invalid attempts: the counter kept "
			  "what B dropped"
			: "the campaign delta does not equal k x B_valid";
		return;
	}
	kw->code = "OK";
	kw->problem = NULL;
}

/* -------------------------------------------------------------- run state */

struct attempt {
	unsigned n;
	unsigned usb_bus, usb_device, bulk_ep;
	char t_arm[TSLEN], t_trigger[TSLEN];
	bool checked;
	unsigned inflight_at_trigger;
	bool trigger_attempted;     /* the control ioctl was actually issued */
	bool urb_completed;         /* transfer had already finished: invalid */
	bool valid;
	const char *invalid_reason; /* NULL when valid */
	int trigger_rc, trigger_errno;
};

struct window { const char *reason; char t0[TSLEN], t1[TSLEN]; };

struct run {
	/* configuration */
	const char *mode;
	unsigned depth, xfer_len, attempts_wanted, settle_ms, sens_triggers;
	int rearm_method;
	unsigned rearm_cycles, rearm_probe_len, rearm_timeout_ms;
	uint16_t trig_wvalue, trig_windex;
	uint8_t trig_type, trig_request;
	uint8_t restore_cfg;

	/* identity, supplied by the operator and copied into the manifest */
	const char *epoch_id, *session_id, *boot_id;
	const char *h_image, *h_patch, *h_parser, *h_gate, *h_gate91, *h_harness, *h_val;
	const char *h_usbmon_verify, *h_holder_merge, *h_verdict;
	const char *dump_path, *dump_sha, *usbmon_path, *usbmon_sha;
	const char *target_kernel, *target_udc, *target_gadget;
	unsigned usbmon_bus;

	/* results */
	struct attempt att[MAX_ATTEMPTS];
	unsigned n_att;
	struct window win[MAX_WINDOWS];
	unsigned n_win;
	unsigned sens_issued, sens_attempted, sens_observed;
	char t_start[TSLEN], t_end[TSLEN];
	unsigned peak_inflight;
	struct rearm_pf rearm;
	struct kwindow kw;
	const char *snapshot_cmd, *usbmon_start_cmd, *usbmon_stop_cmd, *snapshot_dir;
	bool batch_void;
	const char *void_reason;
};

static void load_epoch_json(const char *path, struct run *r)
{
	static const struct {
		const char *json_key;
		const char *label;
	} hashes[] = {
		{ "image", "image" },
		{ "observer_patch", "observer_patch" },
		{ "dwc2_r1_v9", "dwc2_r1_v9" },
		{ "r1_gate_v9", "r1_gate_v9" },
		{ "r1_gate_v9_1", "r1_gate_v9_1" },
		{ "harness", "harness" },
		{ "manifest_validator", "manifest_validator" },
		{ "usbmon_verifier", "usbmon_verifier" },
		{ "holder_merger", "holder_merger" },
		{ "verdict_generator", "verdict_generator" },
	};
	const char **dst[] = {
		&r->h_image, &r->h_patch, &r->h_parser, &r->h_gate, &r->h_gate91,
		&r->h_harness, &r->h_val, &r->h_usbmon_verify,
		&r->h_holder_merge, &r->h_verdict,
	};
	char *json = read_small_text_file(path);
	char tmp[256];
	unsigned i;

	if (json_unique_plain_string(json, "epoch_id", tmp, sizeof(tmp)) < 0 ||
	    !*tmp)
		die("epoch JSON must contain exactly one plain-string epoch_id");
	r->epoch_id = owned_copy(tmp);

	for (i = 0; i < sizeof(hashes) / sizeof(hashes[0]); i++) {
		if (json_unique_plain_string(json, hashes[i].json_key,
					     tmp, sizeof(tmp)) < 0)
			die("epoch JSON must contain exactly one plain-string artifacts.%s",
			    hashes[i].label);
		if (!sha256_text_ok(tmp))
			die("epoch JSON artifacts.%s is not lowercase sha256",
			    hashes[i].label);
		*dst[i] = owned_copy(tmp);
	}
	free(json);
}

static void add_window(struct run *r, const char *reason,
		       const char *t0, const char *t1)
{
	if (r->n_win >= MAX_WINDOWS)
		return;
	r->win[r->n_win].reason = reason;
	snprintf(r->win[r->n_win].t0, TSLEN, "%s", t0);
	snprintf(r->win[r->n_win].t1, TSLEN, "%s", t1);
	r->n_win++;
}

/*
 * Put the device back where the next attempt expects it. The restore MUST go
 * through raw_ctrl: USBDEVFS_SETCONFIGURATION would call the convenience path
 * on a device the host still believes is configured, which is undefined and
 * would also tear down anything still queued.
 *
 * Returns 0 if the device is usable again, -1 if it went away and the caller
 * should reopen it and record an enumeration window.
 */
static int resync_ex(struct target *t, struct pool *p, const struct run *r,
		     int reset_method)
{
	unsigned intf = (unsigned)t->intf;

	pool_discard_all(t->fd, p);
	ioctl(t->fd, USBDEVFS_RELEASEINTERFACE, &intf);

	if (raw_ctrl(t->fd, 0x00, USB_REQ_SET_CONFIGURATION,
		     r->restore_cfg, 0, 1000) < 0)
		return -1;
	msleep(20);
	if (ioctl(t->fd, USBDEVFS_CLAIMINTERFACE, &intf) < 0)
		return -1;

	/*
	 * The gadget put the endpoint back on DATA0 (gadget.c:5164); usbcore
	 * never saw the request, so the host did not. Repair the host side
	 * here, after the claim, while nothing is outstanding. A failure is
	 * not fatal on its own -- the re-arm pre-flight is what decides
	 * whether this call is load-bearing -- but it is not hidden either.
	 */
	if (reset_method != REARM_NONE &&
	    rearm_reset_apply(t->fd, t->ep_out, reset_method) < 0)
		return -1;
	return 0;
}

static int resync(struct target *t, struct pool *p, const struct run *r)
{
	return resync_ex(t, p, r, r->rearm_method);
}

static int reopen_target(struct target *t, uint16_t vid, uint16_t pid,
			 unsigned timeout_ms)
{
	unsigned waited = 0;

	if (t->fd >= 0)
		close(t->fd);
	t->fd = -1;
	while (waited < timeout_ms) {
		struct target n;

		if (find_target(&n, vid, pid) == 0) {
			unsigned intf = (unsigned)n.intf;

			if (ioctl(n.fd, USBDEVFS_CLAIMINTERFACE, &intf) == 0) {
				*t = n;
				return 0;
			}
			close(n.fd);
		}
		msleep(100);
		waited += 100;
	}
	return -1;
}

/*
 * One attempt.
 *
 * The order is load-bearing and must not acquire anything between the check
 * and the trigger: reap what finished, read how many are genuinely still
 * outstanding, then fire. A delay in between would make the check describe a
 * different instant than the one the trigger lands in.
 */
static void do_attempt(struct target *t, struct pool *p, struct run *r,
		       struct attempt *a, unsigned n)
{
	int drained;

	memset(a, 0, sizeof(*a));
	a->n = n;
	a->usb_bus = t->busnum; a->usb_device = t->devnum; a->bulk_ep = t->ep_out;

	pool_arm(t->fd, p, t->ep_out);
	iso_now(a->t_arm);

	drained = pool_drain(t->fd, p);
	if (drained < 0) {
		a->valid = false;
		a->invalid_reason = "device_gone";
		iso_now(a->t_trigger);
		return;
	}

	a->checked = true;
	a->inflight_at_trigger = p->inflight;
	a->urb_completed = (p->inflight == 0);
	if (p->inflight > r->peak_inflight)
		r->peak_inflight = p->inflight;

	if (p->inflight < 1) {
		/* Nothing outstanding: firing now would measure nothing. */
		a->valid = false;
		a->invalid_reason = "not_outstanding";
		iso_now(a->t_trigger);
		return;
	}

	iso_now(a->t_trigger);
	a->trigger_attempted = true;
	a->trigger_rc = raw_ctrl(t->fd, r->trig_type, r->trig_request,
				 r->trig_wvalue, r->trig_windex, 1000);
	if (a->trigger_rc < 0) {
		a->trigger_errno = errno;
		a->valid = false;
		a->invalid_reason = "trigger_failed";
		return;
	}

	msleep(r->settle_ms);
	pool_drain(t->fd, p);          /* status of the survivors is expected
					* to be EPIPE/ESHUTDOWN/ENODEV */
	a->valid = true;
	a->invalid_reason = NULL;
}

/* ------------------------------------------------ re-arm pre-flight */

/*
 * One Bulk OUT of probe_len bytes, reaped under a bound.
 *
 * PROGRESS means the URB came back with status 0 and the whole payload
 * moved. "Submitted without error" is deliberately not enough: a submit
 * succeeds against a stalled toggle just as happily as against a working
 * one, and that indistinguishability is the exact failure this exists to
 * catch.
 *
 * The URB is static, not automatic. processcompl() (devio.c) writes back
 * through the pointer the caller submitted --
 *
 *   put_user(as->status, &userurb->status);
 *   put_user(urb->actual_length, &userurb->actual_length);
 *
 * -- at reap time, so an on-stack URB that outlived its frame would be
 * written into a dead frame. One probe is in flight at a time and the
 * program is single-threaded, so file scope removes the hazard rather than
 * making it unlikely.
 */
static struct usbdevfs_urb probe_urb;

static void probe_bulk_once(int fd, uint8_t ep, unsigned len,
			    unsigned timeout_ms, unsigned char *buf,
			    struct rearm_cycle *c)
{
	struct usbdevfs_urb *done;
	unsigned waited;

	memset(&probe_urb, 0, sizeof(probe_urb));
	probe_urb.type = USBDEVFS_URB_TYPE_BULK;
	probe_urb.endpoint = ep;
	probe_urb.buffer = buf;
	probe_urb.buffer_length = (int)len;
	probe_urb.usercontext = REARM_PROBE_TAG;

	if (ioctl(fd, USBDEVFS_SUBMITURB, &probe_urb) < 0) {
		c->submitted = false;
		c->status = -errno;
		return;
	}
	c->submitted = true;

	for (waited = 0; waited < timeout_ms; waited += 2) {
		if (ioctl(fd, USBDEVFS_REAPURBNDELAY, &done) == 0) {
			if (done->usercontext != REARM_PROBE_TAG)
				continue;      /* not ours; keep waiting */
			c->reaped = true;
			c->status = done->status;
			c->actual_length = done->actual_length;
			c->progress = (done->status == 0 &&
				       done->actual_length >= 0 &&
				       (unsigned)done->actual_length == len);
			return;
		}
		if (errno != EAGAIN) {
			c->status = -errno;
			break;
		}
		msleep(2);
	}

	/*
	 * It never completed. Take the slot back before returning: the kernel
	 * still owns probe_urb until it is reaped, and the next cycle submits
	 * the same object.
	 */
	ioctl(fd, USBDEVFS_DISCARDURB, &probe_urb);
	for (waited = 0; waited < 400; waited += 2) {
		if (ioctl(fd, USBDEVFS_REAPURBNDELAY, &done) == 0) {
			if (done->usercontext == REARM_PROBE_TAG)
				return;
			continue;
		}
		if (errno != EAGAIN)
			return;
		msleep(2);
	}
}

/*
 * One re-arm cycle: the campaign's own trigger, the campaign's own restore,
 * then the arm's reset policy, then a probe. Running the real path rather
 * than a simplified stand-in is the point -- a stand-in could pass while the
 * path the attempts take does not.
 */
static int rearm_cycle_once(struct target *t, struct pool *p, struct run *r,
			    struct rearm_arm *arm, unsigned n,
			    unsigned char *buf, uint16_t vid, uint16_t pid)
{
	struct rearm_cycle *c = &arm->c[n];

	memset(c, 0, sizeof(*c));
	c->n = n + 1;
	iso_now(c->t0);

	/*
	 * The trigger's return code is load-bearing here. If it fails, no
	 * teardown happened, so the restore and the probe that follow test
	 * nothing -- and they would both succeed, pushing the verdict toward
	 * REARM_NO_RESET_NEEDED, which is the permissive answer. A cycle that
	 * did not run is counted as no progress, never as success.
	 */
	c->trigger_rc = raw_ctrl(t->fd, r->trig_type, r->trig_request,
				 r->trig_wvalue, r->trig_windex, 1000);
	if (c->trigger_rc < 0) {
		c->trigger_failed = true;
		arm->trigger_failed++;
		arm->attempted++;
		iso_now(c->t1);
		return 0;
	}

	if (resync_ex(t, p, r, arm->method) < 0) {
		/*
		 * The device left the bus. Reopening gets a host that has just
		 * enumerated the device through the normal path, so its
		 * endpoint state is fresh for reasons that have nothing to do
		 * with the arm under test. The cycle is counted as no progress
		 * rather than dropped: a restore path that loses the device is
		 * a failure of the thing being measured.
		 */
		c->reenum = true;
		arm->reenum++;
		arm->attempted++;
		iso_now(c->t1);
		if (reopen_target(t, vid, pid, 5000) < 0)
			return -1;
		return 0;
	}

	probe_bulk_once(t->fd, t->ep_out, r->rearm_probe_len,
			r->rearm_timeout_ms, buf, c);
	iso_now(c->t1);
	arm->attempted++;
	if (c->progress)
		arm->progress_ok++;
	return 0;
}

/*
 * Two arms, interleaved cycle by cycle rather than run one after the other,
 * so drift in the device side cannot masquerade as an arm effect. The control
 * arm applies no reset; the treatment arm applies the one the run is
 * configured for. Interleaving is also self-correcting: a control cycle that
 * leaves the toggle mismatched is cleared by the treatment cycle that follows
 * it, which is precisely the difference being measured.
 */
static void rearm_preflight(struct target *t, struct pool *p, struct run *r,
			    uint16_t vid, uint16_t pid)
{
	struct rearm_pf *pf = &r->rearm;
	unsigned char *buf;
	unsigned k;

	pf->cycles = 0;
	pf->probe_len = r->rearm_probe_len;
	pf->timeout_ms = r->rearm_timeout_ms;
	pf->method_in_use = r->rearm_method;
	pf->none.label = "none";
	pf->none.method = REARM_NONE;
	pf->reset.label = rearm_method_name(r->rearm_method);
	pf->reset.method = r->rearm_method;

	if (r->rearm_cycles == 0) {
		pf->performed = false;
		pf->verdict = rearm_verdict(pf, &pf->discriminating);
		return;
	}

	buf = calloc(1, r->rearm_probe_len);
	if (!buf)
		die("out of memory for the re-arm probe buffer");

	/*
	 * The probe reaps with REAPURBNDELAY, which hands back whichever URB
	 * finished first on this fd. Anything of the pool's still in flight
	 * would be consumed here and dropped, silently desynchronising
	 * p->inflight -- the very counter every attempt's validity rests on.
	 * So the pool must be empty, and "must" is checked rather than
	 * assumed.
	 */
	pool_discard_all(t->fd, p);
	if (p->inflight != 0) {
		free(buf);
		die("%u URB(s) still in flight entering the re-arm pre-flight; "
		    "the probe would consume their completions and corrupt the "
		    "inflight count the validity check depends on",
		    p->inflight);
	}

	/*
	 * Baseline first. If the device side is not reading, every cycle below
	 * would fail for a reason that has nothing to do with re-arm, and the
	 * verdict has to say which of the two happened.
	 */
	printf("rearm preflight: baseline probe, %u bytes on ep 0x%02x\n",
	       r->rearm_probe_len, t->ep_out);
	memset(&pf->baseline, 0, sizeof(pf->baseline));
	pf->baseline.n = 0;
	iso_now(pf->baseline.t0);
	probe_bulk_once(t->fd, t->ep_out, r->rearm_probe_len,
			r->rearm_timeout_ms, buf, &pf->baseline);
	iso_now(pf->baseline.t1);
	pf->performed = true;

	if (!pf->baseline.progress) {
		pf->verdict = rearm_verdict(pf, &pf->discriminating);
		free(buf);
		return;
	}

	printf("rearm preflight: %u cycles x 2 arms (none, %s)\n",
	       r->rearm_cycles, pf->reset.label);
	for (k = 0; k < r->rearm_cycles && k < REARM_MAX_CYCLES &&
	     !stop_flag; k++) {
		if (rearm_cycle_once(t, p, r, &pf->none, k, buf,
				     vid, pid) < 0) {
			free(buf);
			die("device did not return during the re-arm "
			    "pre-flight (control arm, cycle %u)", k + 1);
		}
		if (rearm_cycle_once(t, p, r, &pf->reset, k, buf,
				     vid, pid) < 0) {
			free(buf);
			die("device did not return during the re-arm "
			    "pre-flight (%s arm, cycle %u)",
			    pf->reset.label, k + 1);
		}
	}
	free(buf);

	/* An interrupted run has unequal arms; the shorter one is the only
	 * length at which both were measured. */
	pf->cycles = pf->none.attempted < pf->reset.attempted
		   ? pf->none.attempted : pf->reset.attempted;
	pf->verdict = rearm_verdict(pf, &pf->discriminating);
	printf("rearm preflight: none %u/%u, %s %u/%u -> %s%s\n",
	       pf->none.progress_ok, pf->cycles, pf->reset.label,
	       pf->reset.progress_ok, pf->cycles, pf->verdict,
	       pf->discriminating ? " (discriminating)"
				  : " (NOT discriminating)");
}

/* ---------------------------------------------------------- preflight */

/*
 * Paired positive control. Every trigger issued here must appear in the
 * observer dump as a CAUSE_SYNC_OWNER candidate. Equality proves the whole
 * chain carries a trigger -- harness, wire, UDC, observer, dump -- without
 * waiting for the phenomenon under study to occur.
 *
 * The observed count cannot be read from here: it lives in the device's
 * debugfs. It is supplied by --observed-cmd (run after this burst) or by
 * --sync-owner-observed. With neither, the run stops: sensitivity would be
 * an assertion, and the manifest validator derives it rather than believing
 * it, so the session would be rejected downstream anyway.
 */
static void preflight_burst(struct target *t, struct pool *p, struct run *r,
			    uint16_t vid, uint16_t pid)
{
	char t0[TSLEN], t1[TSLEN];
	unsigned i;

	printf("preflight: issuing %u paired control triggers\n",
	       r->sens_triggers);
	iso_now(t0);

	for (i = 0; i < r->sens_triggers && !stop_flag; i++) {
		struct attempt a;

		do_attempt(t, p, r, &a, i + 1);
		r->sens_attempted++;
		if (!a.valid)
			printf("  preflight trigger %u not counted (%s)\n",
			       i + 1, a.invalid_reason);
		else
			r->sens_issued++;
		if (resync(t, p, r) < 0) {
			iso_now(t1);
			if (reopen_target(t, vid, pid, 5000) < 0)
				die("device did not come back during preflight");
			add_window(r, "enumeration", t0, t1);
			iso_now(t0);
		}
	}
	printf("preflight: %u triggers issued and counted\n", r->sens_issued);
}

/* ----------------------------------------------------------- manifest */

static const char *REASONS[] = {
	"not_checked", "not_outstanding", "submit_failed", "in_excluded_window",
	"trigger_failed", "device_gone", "operator_aborted", NULL,
};

/*
 * Field names here are the ones the protocol fixed -- REARM_DATA_PROGRESS,
 * bytes_after_rearm, first_bulk_completion_status -- spelled exactly, so the
 * manifest, the spec and the review all say the same word for the same thing.
 * t0/t1 bound each cycle so an externally captured usbmon trace can be sliced
 * to it without guessing.
 */
static void emit_rearm_cycle(FILE *f, const struct rearm_cycle *c,
			     const char *pad)
{
	fprintf(f, "%s{\"n\": %u, \"t0\": \"%s\", \"t1\": \"%s\", "
		"\"reenum\": %s, \"submitted\": %s, \"reaped\": %s,\n"
		"%s \"first_bulk_completion_status\": %d, "
		"\"bytes_after_rearm\": %d, \"REARM_DATA_PROGRESS\": %s}",
		pad, c->n, c->t0, c->t1,
		c->reenum ? "true" : "false",
		c->submitted ? "true" : "false",
		c->reaped ? "true" : "false",
		pad, c->status, c->actual_length,
		c->progress ? "true" : "false");
}

static void emit_rearm_arm(FILE *f, const struct rearm_arm *a, unsigned cycles)
{
	unsigned i;

	fprintf(f, "        {\"label\": \"%s\", \"method\": \"%s\", "
		"\"attempted\": %u, \"progress_ok\": %u, \"reenum\": %u,\n"
		"         \"cycles\": [", a->label, rearm_method_name(a->method),
		a->attempted, a->progress_ok, a->reenum);
	for (i = 0; i < cycles && i < REARM_MAX_CYCLES; i++) {
		fputs(i ? ",\n" : "\n", f);
		emit_rearm_cycle(f, &a->c[i], "           ");
	}
	fprintf(f, "%s]}", cycles ? "\n         " : "");
}

static void emit_rearm(FILE *f, const struct run *r)
{
	const struct rearm_pf *pf = &r->rearm;
	bool disc = false;
	const char *v = rearm_verdict(pf, &disc);

	fprintf(f, "    \"rearm\": {\n");
	fprintf(f, "      \"protocol\": \"two_arm_payload_progress\",\n");
	fprintf(f, "      \"performed\": %s,\n",
		pf->performed ? "true" : "false");
	fprintf(f, "      \"cycles\": %u,\n", pf->cycles);
	fprintf(f, "      \"probe_len\": %u,\n", pf->probe_len);
	fprintf(f, "      \"timeout_ms\": %u,\n", pf->timeout_ms);
	fprintf(f, "      \"reset_method_in_use\": \"%s\",\n",
		rearm_method_name(pf->method_in_use));
	fprintf(f, "      \"baseline\":\n");
	emit_rearm_cycle(f, &pf->baseline, "        ");
	fprintf(f, ",\n      \"arms\": [\n");
	emit_rearm_arm(f, &pf->none, pf->cycles);
	fputs(",\n", f);
	emit_rearm_arm(f, &pf->reset, pf->cycles);
	fprintf(f, "\n      ],\n");
	fprintf(f, "      \"discriminating\": %s,\n",
		disc ? "true" : "false");
	fprintf(f, "      \"verdict\": \"%s\"\n    },\n", v);
}

static void emit_snapshot(FILE *f, const struct r1_snapshot *sn,
			  unsigned field_idx, const char *setup_name, unsigned setup_idx)
{
	fprintf(f, "      {\"label\": \"%s\", \"when\": \"%s\", "
		"\"utc\": \"%s\", \"ok\": %s,\n"
		"       \"path\": ", sn->label ? sn->label : "",
		sn->when ? sn->when : "", sn->utc,
		sn->ok ? "true" : "false");
	jstr(f, sn->path);
	fprintf(f, ", \"sha256\": \"%s\",\n"
		"       \"field_value\": %u, \"reset_generation\": %u, "
		"\"lost\": %u, \"caps_flags\": %u,\n"
		"       \"snapshot_atomic\": %u, \"count\": %u, "
		"\"causal_sync_count\": %u, \"setup_field\": \"%s\", \"setup_value\": %u, "
		"\"target\": [%u, %u, %u, %u]}",
		sn->sha, sn->ok ? sn->w[field_idx] : 0,
		sn->ok ? sn->w[R1H_RESET_GENERATION] : 0,
		sn->ok ? sn->w[R1H_LOST] : 0,
		sn->ok ? sn->w[R1H_CAPS_FLAGS] : 0,
		sn->ok ? sn->w[R1H_SNAPSHOT_ATOMIC] : 0,
		sn->ok ? sn->w[R1H_COUNT] : 0,
		sn->ok ? sn->w[R1H_CAUSAL_SYNC] : 0, setup_name ? setup_name : "",
		sn->ok ? sn->w[setup_idx] : 0,
		sn->ok ? sn->w[R1H_GSNPSID] : 0,
		sn->ok ? sn->w[R1H_GHWCFG2] : 0,
		sn->ok ? sn->w[R1H_GHWCFG3] : 0,
		sn->ok ? sn->w[R1H_GHWCFG4] : 0);
}

/*
 * The denominator, and how it was arrived at. Absolute counters never appear
 * as a denominator here: they carry the sensitivity burst, the re-arm
 * pre-flight, and in cfgn mode one classified SETUP per restore.
 */
static void emit_kernel_window(FILE *f, const struct run *r)
{
	const struct kwindow *kw = &r->kw;

	fprintf(f, "  \"kernel_window\": {\n");
	fprintf(f, "    \"unit\": \"endpoint_stop_opportunities\",\n");
	fprintf(f, "    \"field\": ");
	jstr(f, kw->field_name);
	fprintf(f, ",\n    \"snapshots\": [\n");
	emit_snapshot(f, &kw->s0, kw->field_idx, kw->setup_field_name, kw->setup_field_idx);
	fputs(",\n", f);
	emit_snapshot(f, &kw->s1, kw->field_idx, kw->setup_field_name, kw->setup_field_idx);
	fputs(",\n", f);
	emit_snapshot(f, &kw->s2, kw->field_idx, kw->setup_field_name, kw->setup_field_idx);
	fprintf(f, "\n    ],\n");
	fprintf(f, "    \"record_slice\": {\"start\": %u, \"end\": %u},\n", kw->s1.ok ? kw->s1.w[R1H_COUNT] : 0, kw->s2.ok ? kw->s2.w[R1H_COUNT] : 0);
	fprintf(f, "    \"consistent\": %s,\n",
		kw->consistent ? "true" : "false");
	fprintf(f, "    \"k\": {\"measured_from\": \"sensitivity_burst\", "
		"\"attempts\": %u, \"delta\": %lu, \"k\": %u, "
		"\"exact\": %s},\n",
		r->sens_attempted, kw->delta_sens, kw->k,
		kw->k_exact ? "true" : "false");
	fprintf(f, "    \"campaign\": {\"delta\": %lu, \"expected\": %lu, "
		"\"relation_ok\": %s},\n",
		kw->delta_camp, kw->expected,
		kw->relation_ok ? "true" : "false");
	fprintf(f, "    \"code\": \"%s\",\n", kw->code ? kw->code : "OK");
	fprintf(f, "    \"problem\": ");
	if (kw->problem)
		jstr(f, kw->problem);
	else
		fputs("null", f);
	fprintf(f, "\n  },\n");
}

static void write_manifest(const struct run *r, const struct target *t,
			   const char *path, const char *log_sha)
{
	unsigned i, j, b_valid = 0, b_invalid = 0;
	unsigned tally[8] = {0};
	struct utsname un;
	FILE *f;

	uname(&un);

	for (i = 0; i < r->n_att; i++) {
		if (r->att[i].valid) {
			b_valid++;
			continue;
		}
		b_invalid++;
		for (j = 0; REASONS[j]; j++)
			if (r->att[i].invalid_reason &&
			    !strcmp(r->att[i].invalid_reason, REASONS[j]))
				tally[j]++;
	}

	f = fopen(path, "w");
	if (!f)
		die("cannot write manifest %s: %s", path, strerror(errno));

	fprintf(f, "{\n  \"manifest_version\": 2,\n");

	fprintf(f, "  \"epoch\": {\n    \"epoch_id\": ");
	jstr(f, r->epoch_id);
	fprintf(f, ",\n    \"artifacts\": {\n");
	fprintf(f, "      \"image\": \"%s\",\n", r->h_image);
	fprintf(f, "      \"observer_patch\": \"%s\",\n", r->h_patch);
	fprintf(f, "      \"dwc2_r1_v9\": \"%s\",\n", r->h_parser);
	fprintf(f, "      \"r1_gate_v9\": \"%s\",\n", r->h_gate);
	fprintf(f, "      \"r1_gate_v9_1\": \"%s\",\n", r->h_gate91);
	fprintf(f, "      \"harness\": \"%s\",\n", r->h_harness);
	fprintf(f, "      \"manifest_validator\": \"%s\",\n", r->h_val);
	fprintf(f, "      \"usbmon_verifier\": \"%s\",\n", r->h_usbmon_verify);
	fprintf(f, "      \"holder_merger\": \"%s\",\n", r->h_holder_merge);
	fprintf(f, "      \"verdict_generator\": \"%s\"\n", r->h_verdict);
	fprintf(f, "    }\n  },\n");

	fprintf(f, "  \"session\": {\n    \"session_id\": ");
	jstr(f, r->session_id);
	fprintf(f, ",\n    \"boot_id\": ");
	jstr(f, r->boot_id);
	fprintf(f, ",\n    \"started_utc\": \"%s\",\n", r->t_start);
	fprintf(f, "    \"ended_utc\": \"%s\",\n", r->t_end);
	fprintf(f, "    \"mode\": ");
	jstr(f, r->mode);
	fprintf(f, ",\n    \"target\": {\n      \"kernel_release\": ");
	jstr(f, r->target_kernel);
	fprintf(f, ",\n      \"udc\": ");
	jstr(f, r->target_udc);
	fprintf(f, ",\n      \"gadget_config\": ");
	jstr(f, r->target_gadget);
	fprintf(f, "\n    },\n    \"host\": {\n      \"kernel\": ");
	jstr(f, un.release);
	fprintf(f, ",\n      \"usbmon_bus\": %u\n    },\n", r->usbmon_bus);
	fprintf(f, "    \"trigger\": {\"bmRequestType\": %u, \"bRequest\": %u, \"wValue\": %u, \"wIndex\": %u, \"wLength\": 0},\n", r->trig_type, r->trig_request, r->trig_wvalue, r->trig_windex);
	fprintf(f, "    \"restore_cfg\": %u\n  },\n", r->restore_cfg);

	fprintf(f, "  \"preflight\": {\n");
	{
		/* Sourced, not asserted. Every number below is a word out of
		 * the final dump header; "source" says dump_header only
		 * because a header was actually parsed. */
		const struct r1_snapshot *sn = &r->kw.s2;
		const uint32_t *w = sn->w;

		fprintf(f, "    \"caps\": {\"g_dma\": %d, "
			"\"g_dma_desc\": %d, \"caps_flags\": %u, "
			"\"source\": \"%s\", \"from_sha256\": \"%s\"},\n",
			sn->ok && (w[R1H_CAPS_FLAGS] & R1_CAP_DMA) ? 1 : 0,
			sn->ok && (w[R1H_CAPS_FLAGS] & R1_CAP_DDMA) ? 1 : 0,
			sn->ok ? w[R1H_CAPS_FLAGS] : 0,
			sn->ok ? "dump_header" : "unavailable",
			sn->ok ? sn->sha : "");
		fprintf(f, "    \"abi\": {\"version\": %u, "
			"\"header_size\": %u, \"record_size\": %u},\n",
			sn->ok ? w[R1H_VERSION] : 0,
			sn->ok ? w[R1H_HEADER_SIZE] : 0,
			sn->ok ? w[R1H_RECORD_SIZE] : 0);
		fprintf(f, "    \"snapshot_atomic\": %u,\n    \"lost\": %u,\n",
			sn->ok ? w[R1H_SNAPSHOT_ATOMIC] : 0,
			sn->ok ? w[R1H_LOST] : 1);
		fprintf(f, "    \"overlap_count\": %u,\n",
			sn->ok ? w[R1H_OVERLAP_COUNT] : 0);
	}
	emit_rearm(f, r);
	fprintf(f, "    \"sensitivity\": {\n");
	fprintf(f, "      \"protocol\": \"paired_positive_control\",\n");
	fprintf(f, "      \"source\": \"S0_S1_dump_headers\",\n");
	fprintf(f, "      \"triggers_issued\": %u,\n", r->sens_issued);
	fprintf(f, "      \"sync_owner_candidates_observed\": %u,\n", r->sens_observed);
	fprintf(f, "      \"setup_triggers_observed\": %u,\n", r->kw.s1.ok && r->kw.s0.ok ? r->kw.s1.w[r->kw.setup_field_idx] - r->kw.s0.w[r->kw.setup_field_idx] : 0);
	fprintf(f, "      \"verdict\": \"%s\",\n",
		(r->sens_issued >= 1 && r->sens_issued == r->sens_observed)
		? "SENSITIVE" : "INSENSITIVE");
	fprintf(f, "      \"excluded_windows\": [");
	for (i = 0; i < r->n_win; i++)
		fprintf(f, "%s\n        {\"reason\": \"%s\", \"t0\": \"%s\", "
			"\"t1\": \"%s\"}", i ? "," : "", r->win[i].reason,
			r->win[i].t0, r->win[i].t1);
	fprintf(f, "%s]\n    }\n  },\n", r->n_win ? "\n      " : "");

	emit_kernel_window(f, r);

	fprintf(f, "  \"attempts\": [");
	for (i = 0; i < r->n_att; i++) {
		const struct attempt *a = &r->att[i];

		fprintf(f, "%s\n    {\"n\": %u, \"t_arm_utc\": \"%s\", "
			"\"t_trigger_utc\": \"%s\",\n"
			"     \"outstanding\": {\"checked\": %s, "
			"\"method\": \"urb_status_pending\", "
			"\"inflight_at_trigger\": %u, \"urb_completed\": %s},\n"
			"     \"trigger_attempted\": %s, \"trigger_rc\": %d,\n"
			"     \"usb_bus\": %u, \"usb_device\": %u, \"bulk_ep\": %u,\n"
			"     \"valid\": %s, \"invalid_reason\": ",
			i ? "," : "", a->n, a->t_arm, a->t_trigger,
			a->checked ? "true" : "false", a->inflight_at_trigger,
			a->urb_completed ? "true" : "false",
			a->trigger_attempted ? "true" : "false",
			a->trigger_rc, a->usb_bus, a->usb_device, a->bulk_ep,
			a->valid ? "true" : "false");
		if (a->invalid_reason)
			jstr(f, a->invalid_reason);
		else
			fputs("null", f);
		fputc('}', f);
	}
	fprintf(f, "\n  ],\n");

	fprintf(f, "  \"denominator\": {\"unit\": \"host_attempts\", "
		"\"B_valid\": %u, \"B_invalid\": %u,\n"
		"    \"batch_void\": %s, \"batch_void_reason\": ",
		b_valid, b_invalid, r->batch_void ? "true" : "false");
	if (r->void_reason)
		jstr(f, r->void_reason);
	else
		fputs("null", f);
	fprintf(f, ",\n    \"kernel_delta\": %lu, \"k\": %u, "
		"\"relation_ok\": %s,\n"
		"    \"invalid_reasons\": {",
		r->kw.delta_camp, r->kw.k,
		r->kw.relation_ok ? "true" : "false");
	{
		bool first = true;

		for (j = 0; REASONS[j]; j++)
			if (tally[j]) {
				fprintf(f, "%s\"%s\": %u", first ? "" : ", ",
					REASONS[j], tally[j]);
				first = false;
			}
	}
	fprintf(f, "}},\n");

	fprintf(f, "  \"artifacts\": {\n");
	fprintf(f, "    \"dump\": {\"path\": ");
	jstr(f, r->dump_path);
	fprintf(f, ", \"sha256\": \"%s\"},\n", r->dump_sha);
	fprintf(f, "    \"usbmon\": {\"path\": ");
	jstr(f, r->usbmon_path);
	fprintf(f, ", \"sha256\": \"%s\", \"scope\": \"campaign_only\"},\n", r->usbmon_sha);
	fprintf(f, "    \"harness_log\": {\"path\": ");
	jstr(f, "harness.log");
	fprintf(f, ", \"sha256\": \"%s\"}\n  }\n}\n", log_sha);
	fclose(f);

	printf("manifest: %s  (B_valid=%u B_invalid=%u, peak inflight %u, ep 0x%02x)\n",
	       path, b_valid, b_invalid, r->peak_inflight, t->ep_out);
}

/* --------------------------------------------- snapshot / window tests */

/*
 * The header parser and the denominator rule are new and load-bearing, and
 * neither needs a device to be wrong. These run against files this function
 * writes, so a corrupt header is tested by producing one rather than by
 * trusting that the check would fire.
 */
static void wr32(uint8_t *p, uint32_t v)
{
	p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
	p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static int write_hdr(const char *path, uint32_t magic, uint32_t ver,
		     size_t bytes)
{
	uint8_t h[R1_HDR_BYTES];
	FILE *f = fopen(path, "wb");

	if (!f)
		return -1;
	memset(h, 0, sizeof(h));
	wr32(h + 4 * R1H_MAGIC, magic);
	wr32(h + 4 * R1H_VERSION, ver);
	wr32(h + 4 * R1H_HEADER_SIZE, R1_HDR_BYTES);
	wr32(h + 4 * R1H_RECORD_SIZE, 80);
	wr32(h + 4 * R1H_CAPS_FLAGS, R1_CAP_DMA);
	wr32(h + 4 * R1H_SNAPSHOT_ATOMIC, 1);
	fwrite(h, 1, bytes, f);
	fclose(f);
	return 0;
}

struct wcase {
	const char *name;
	uint32_t gen[3], lost[3], field[3];
	unsigned sens_issued, sens_attempted, b_valid, b_invalid;
	bool want_ok;
};

static int selftest_snapshot(void)
{
	static const char *DIR = "/tmp";
	char src[256], cmd[512];
	struct r1_snapshot sn;
	int fails = 0, i;

	struct { const char *name; uint32_t magic, ver; size_t bytes;
		 bool want_ok; } P[] = {
	 {"well-formed v9 header",     R1_HDR_MAGIC, 9, R1_HDR_BYTES, true},
	 {"wrong magic",               0xdeadbeef,   9, R1_HDR_BYTES, false},
	 {"ABI v8 dump",               R1_HDR_MAGIC, 8, R1_HDR_BYTES, false},
	 {"truncated header",          R1_HDR_MAGIC, 9, 100,          false},
	};

	printf("== dump header parser ==\n");
	for (i = 0; i < (int)(sizeof(P) / sizeof(P[0])); i++) {
		bool got;

		snprintf(src, sizeof(src), "%s/r1-hdr-src-%d.bin", DIR, i);
		if (write_hdr(src, P[i].magic, P[i].ver, P[i].bytes))
			die("cannot write %s", src);
		snprintf(cmd, sizeof(cmd), "cp '%s' '%%s'", src);
		memset(&sn, 0, sizeof(sn));
		sn.label = "T";
		got = snapshot_take(&sn, cmd, DIR, (unsigned)i);
		printf("%s %-42s %s\n", got == P[i].want_ok ? "ok  " : "FAIL",
		       P[i].name, got ? "parsed" : sn.err);
		fails += got != P[i].want_ok;
		remove(src);
	}
	memset(&sn, 0, sizeof(sn));
	sn.label = "T";
	if (snapshot_take(&sn, "false", DIR, 90)) {
		printf("FAIL %-42s\n", "fetch command that fails");
		fails++;
	} else {
		printf("ok   %-42s %s\n", "fetch command that fails", sn.err);
	}
	memset(&sn, 0, sizeof(sn));
	sn.label = "T";
	if (snapshot_take(&sn, "true %s", DIR, 91)) {
		printf("FAIL %-42s\n", "fetch command that writes nothing");
		fails++;
	} else {
		printf("ok   %-42s %s\n", "fetch command that writes nothing",
		       sn.err);
	}

	printf("\n== denominator window ==\n");
	{
	struct wcase W[] = {
	 {"clean run, k=2",        {7,7,7}, {0,0,0}, {100,140,146},
	  20, 20, 3, 0, true},
	 {"observer reset midway", {7,8,8}, {0,0,0}, {100,140,146},
	  20, 20, 3, 0, false},
	 {"records were dropped",  {7,7,7}, {0,0,1}, {100,140,146},
	  20, 20, 3, 0, false},
	 {"counter went backwards",{7,7,7}, {0,0,0}, {100,140,139},
	  20, 20, 3, 0, false},
	 {"k is not a whole number",{7,7,7},{0,0,0}, {100,141,146},
	  20, 20, 3, 0, false},
	 {"a sensitivity attempt was invalid", {7,7,7}, {0,0,0},
	  {100,140,146}, 20, 21, 3, 0, false},
	 {"campaign delta too large", {7,7,7}, {0,0,0}, {100,140,150},
	  20, 20, 3, 1, false},
	 {"no valid attempt at all",  {7,7,7}, {0,0,0}, {100,140,140},
	  20, 20, 0, 4, false},
	 {"invalid attempts that cost nothing", {7,7,7}, {0,0,0},
	  {100,140,146}, 20, 20, 3, 1, true},
	};
	for (i = 0; i < (int)(sizeof(W) / sizeof(W[0])); i++) {
		static struct kwindow kw;
		struct r1_snapshot *sp[3];
		int j;
		bool got;

		memset(&kw, 0, sizeof(kw));
		kw.enabled = true;
		kw.field_idx = R1H_CAND_CFG0;
		kw.field_name = "candidate_cfg0_seen";
		sp[0] = &kw.s0; sp[1] = &kw.s1; sp[2] = &kw.s2;
		for (j = 0; j < 3; j++) {
			sp[j]->ok = true;
			sp[j]->w[R1H_MAGIC] = R1_HDR_MAGIC;
			sp[j]->w[R1H_VERSION] = 9;
			sp[j]->w[R1H_CAPS_FLAGS] = R1_CAP_DMA;
			sp[j]->w[R1H_SNAPSHOT_ATOMIC] = 1;
			sp[j]->w[R1H_RESET_GENERATION] = W[i].gen[j];
			sp[j]->w[R1H_LOST] = W[i].lost[j];
			sp[j]->w[R1H_CAND_CFG0] = W[i].field[j];
		}
		kwindow_derive(&kw, W[i].sens_issued, W[i].sens_attempted,
			       W[i].b_valid, W[i].b_invalid);
		got = (kw.problem == NULL);
		printf("%s %-42s %s\n", got == W[i].want_ok ? "ok  " : "FAIL",
		       W[i].name, kw.problem ? kw.problem : "usable");
		fails += got != W[i].want_ok;
	}
	}

	printf("\nSNAPSHOT SELFTEST: %s\n", fails ? "FAILED" : "all passed");
	return fails ? 1 : 0;
}

/* ---------------------------------------------------------------- main */

static void usage(const char *p)
{
	fprintf(stderr,
"usage: %s --vid X --pid Y | --dev /dev/bus/usb/BBB/DDD\n"
"\n"
"  target and traffic\n"
"    --intf N              interface to claim (default: the one owning the\n"
"                          bulk OUT endpoint found in the descriptors)\n"
"    --expect-ep 0xNN      abort unless the descriptors give this endpoint;\n"
"                          must match what the device side confirmed with\n"
"                          FUNCTIONFS_ENDPOINT_DESC\n"
"    --depth N             outstanding Bulk OUT URBs (default 8)\n"
"    --xfer-len N          bytes per URB (default 16384)\n"
"    --settle-ms N         wait after the trigger before reaping (default 200)\n"
"\n"
"  observer dump snapshots (required: the denominator and every target fact\n"
"  are read from the dump, not from this command line)\n"
"    --snapshot-cmd CMD    fetch the observer dump. \"%%s\" in CMD is the\n"
"                          destination path; without it CMD's stdout is\n"
"                          redirected there. Run three times: after the\n"
"                          re-arm pre-flight, after the sensitivity burst,\n"
"                          and after the campaign. Only differences are used\n"
"    --snapshot-dir DIR    where the three snapshots are written (default .)\n"
"    --usbmon-start-cmd CMD start/truncate the campaign-only capture after S1\n"
"    --usbmon-stop-cmd CMD  stop AND wait for the capture writer before hashing\n"
"\n"
"  host endpoint re-arm (fail-closed: the campaign does not start without a\n"
"  usable verdict)\n"
"    --rearm-reset M       none|resetep|clear-halt (default resetep). The raw\n"
"                          restore bypasses usb_set_configuration(), so the\n"
"                          host keeps its old toggle while the gadget resets\n"
"                          to DATA0 (gadget.c:5164). resetep is USBDEVFS_RESETEP\n"
"                          (U,3), host-side only, no configuration change.\n"
"    --rearm-cycles N      pre-flight cycles per arm (default 8, minimum 3;\n"
"                          0 records a refusal instead of running one)\n"
"    --rearm-probe-len N   probe payload bytes (default: --xfer-len)\n"
"    --rearm-timeout-ms N  bound on one probe (default 2000)\n"
"\n"
"  trigger\n"
"    --mode cfg0|cfgn|interface-sync   (default cfg0)\n"
"    --cfgn-value N        configuration number for cfgn\n"
"    --alt-intf N          interface index for interface-sync\n"
"    --restore-cfg N       configuration to restore between attempts\n"
"    --attempts N          campaign attempts after preflight\n"
"\n"
"  sensitivity (derived from S0/S1 dump headers; no observed-count CLI)\n"
"    --sens-triggers N     paired positive controls to issue (default 20)\n"
"\n"
"  target-side EXPECTATIONS. The dump is what the manifest reports; these\n"
"  say what you expect it to say, and a mismatch aborts\n"
"    --g-dma 1 --g-dma-desc 0 --abi-version 9 --abi-header 112\n"
"    --abi-record 80 --snapshot-atomic 1 --lost 0 --overlap-count 0\n"
"\n"
"  identity for the manifest\n"
"    --epoch-json PATH     preferred: consume freeze_epoch.py output directly\n"
"    --session-id S --boot-id S\n"
"    legacy manual epoch fields (cannot be mixed with --epoch-json):\n"
"    --epoch-id S\n"
"    --sha-image H --sha-patch H --sha-parser H --sha-gate H\n"
"    --sha-gate-v9-1 H --sha-harness H --sha-validator H\n"
"    --sha-usbmon-verifier H --sha-holder-merger H --sha-verdict H\n"
"    --target-kernel S --target-udc S --target-gadget S\n"
"    --usbmon PATH --usbmon-bus N   (the dump is the S2 snapshot)\n"
"    --log PATH            harness log (default harness.log)\n"
"    --manifest PATH       output (default session.json)\n", p);
}

#define ARG(name) (!strcmp(argv[i], name) && i + 1 < (unsigned)argc)

int main(int argc, char **argv)
{
	/*
	 * static, not automatic: the attempt array makes this struct about
	 * 17 MB at MAX_ATTEMPTS, which overflows the default 8 MB stack and
	 * faults before the first ioctl. main() runs once, so .bss is the
	 * right home for it.
	 */
	static struct run r;
	struct target t;
	struct pool p;
	const char *dev_path = NULL;
	const char *epoch_json_path = NULL;
	const char *log_path = "harness.log", *man_path = "session.json";
		int vid = -1, pid = -1, want_intf = -1, expect_ep = -1;
	bool selftest = false, selftest_sha = false, manual_epoch = false;
	int g_dma = -1, g_dma_desc = -1, abi_v = -1, abi_h = -1, abi_r = -1;
	int snap = -1, lost = -1, overlap = -1;
	int cfgn_value = 1, alt_intf = 0;
	char log_sha[65] = {0}, dump_sha[65] = {0}, usbmon_sha[65] = {0}, self_sha[65] = {0};
	unsigned i;
	FILE *log;

	memset(&r, 0, sizeof(r));
	r.mode = "cfg0";
	r.depth = 8;
	r.xfer_len = 16384;
	r.settle_ms = 200;
	r.sens_triggers = 20;
	r.rearm_method = REARM_RESETEP;
	r.rearm_cycles = 8;
	r.rearm_probe_len = 0;          /* 0 means "same as --xfer-len" */
	r.rearm_timeout_ms = 2000;
	r.attempts_wanted = 50;
	r.restore_cfg = 1;
	r.usbmon_bus = 0;
	r.dump_path = "";
	r.dump_sha = "";
	r.snapshot_cmd = NULL;
	r.usbmon_start_cmd = NULL;
	r.usbmon_stop_cmd = NULL;
	r.snapshot_dir = ".";
	r.kw.field_name = "";
	r.usbmon_path = "";
	r.usbmon_sha = "";
	r.target_kernel = r.target_udc = r.target_gadget = "";
	r.epoch_id = r.session_id = r.boot_id = "";
	r.h_image = r.h_patch = r.h_parser = "";
	r.h_gate = r.h_gate91 = r.h_harness = r.h_val = "";
	r.h_usbmon_verify = r.h_holder_merge = r.h_verdict = "";

	for (i = 1; i < (unsigned)argc; i++) {
		if (ARG("--dev")) dev_path = argv[++i];
		else if (ARG("--vid")) vid = (int)strtol(argv[++i], NULL, 0);
		else if (ARG("--pid")) pid = (int)strtol(argv[++i], NULL, 0);
		else if (ARG("--intf")) want_intf = atoi(argv[++i]);
		else if (ARG("--expect-ep")) expect_ep = (int)strtol(argv[++i], NULL, 0);
		else if (ARG("--depth")) r.depth = (unsigned)atoi(argv[++i]);
		else if (ARG("--xfer-len")) r.xfer_len = (unsigned)atoi(argv[++i]);
		else if (ARG("--settle-ms")) r.settle_ms = (unsigned)atoi(argv[++i]);
		else if (ARG("--rearm-reset")) {
			const char *m = argv[++i];

			if (!strcmp(m, "none"))
				r.rearm_method = REARM_NONE;
			else if (!strcmp(m, "resetep"))
				r.rearm_method = REARM_RESETEP;
			else if (!strcmp(m, "clear-halt"))
				r.rearm_method = REARM_CLEAR_HALT;
			else
				die("--rearm-reset must be none, resetep or "
				    "clear-halt");
		}
		else if (ARG("--rearm-cycles"))
			r.rearm_cycles = (unsigned)atoi(argv[++i]);
		else if (ARG("--rearm-probe-len"))
			r.rearm_probe_len = (unsigned)atoi(argv[++i]);
		else if (ARG("--rearm-timeout-ms"))
			r.rearm_timeout_ms = (unsigned)atoi(argv[++i]);
		else if (ARG("--mode")) r.mode = argv[++i];
		else if (ARG("--cfgn-value")) cfgn_value = atoi(argv[++i]);
		else if (ARG("--alt-intf")) alt_intf = atoi(argv[++i]);
		else if (ARG("--restore-cfg")) r.restore_cfg = (uint8_t)atoi(argv[++i]);
		else if (ARG("--attempts")) r.attempts_wanted = (unsigned)atoi(argv[++i]);
		else if (ARG("--sens-triggers")) r.sens_triggers = (unsigned)atoi(argv[++i]);
				else if (ARG("--g-dma")) g_dma = atoi(argv[++i]);
		else if (ARG("--g-dma-desc")) g_dma_desc = atoi(argv[++i]);
		else if (ARG("--abi-version")) abi_v = atoi(argv[++i]);
		else if (ARG("--abi-header")) abi_h = atoi(argv[++i]);
		else if (ARG("--abi-record")) abi_r = atoi(argv[++i]);
		else if (ARG("--snapshot-atomic")) snap = atoi(argv[++i]);
		else if (ARG("--lost")) lost = atoi(argv[++i]);
		else if (ARG("--overlap-count")) overlap = atoi(argv[++i]);
		else if (ARG("--epoch-json")) epoch_json_path = argv[++i];
		else if (ARG("--epoch-id")) { r.epoch_id = argv[++i]; manual_epoch = true; }
		else if (ARG("--session-id")) r.session_id = argv[++i];
		else if (ARG("--boot-id")) r.boot_id = argv[++i];
		else if (ARG("--sha-image")) { r.h_image = argv[++i]; manual_epoch = true; }
		else if (ARG("--sha-patch")) { r.h_patch = argv[++i]; manual_epoch = true; }
		else if (ARG("--sha-parser")) { r.h_parser = argv[++i]; manual_epoch = true; }
		else if (ARG("--sha-gate")) { r.h_gate = argv[++i]; manual_epoch = true; }
		else if (ARG("--sha-gate-v9-1")) { r.h_gate91 = argv[++i]; manual_epoch = true; }
		else if (ARG("--sha-harness")) { r.h_harness = argv[++i]; manual_epoch = true; }
		else if (ARG("--sha-validator")) { r.h_val = argv[++i]; manual_epoch = true; }
		else if (ARG("--sha-usbmon-verifier")) { r.h_usbmon_verify = argv[++i]; manual_epoch = true; }
		else if (ARG("--sha-holder-merger")) { r.h_holder_merge = argv[++i]; manual_epoch = true; }
		else if (ARG("--sha-verdict")) { r.h_verdict = argv[++i]; manual_epoch = true; }
		else if (ARG("--target-kernel")) r.target_kernel = argv[++i];
		else if (ARG("--target-udc")) r.target_udc = argv[++i];
		else if (ARG("--target-gadget")) r.target_gadget = argv[++i];
		else if (ARG("--snapshot-cmd")) r.snapshot_cmd = argv[++i];
		else if (ARG("--snapshot-dir")) r.snapshot_dir = argv[++i];
		else if (ARG("--usbmon-start-cmd")) r.usbmon_start_cmd = argv[++i];
		else if (ARG("--usbmon-stop-cmd")) r.usbmon_stop_cmd = argv[++i];
		else if (ARG("--usbmon")) r.usbmon_path = argv[++i];
		else if (ARG("--usbmon-bus")) r.usbmon_bus = (unsigned)atoi(argv[++i]);
		else if (ARG("--log")) log_path = argv[++i];
		else if (ARG("--manifest")) man_path = argv[++i];
		else if (!strcmp(argv[i], "--selftest")) selftest = true;
		else if (!strcmp(argv[i], "--selftest-sha")) selftest_sha = true;
		else if (!strcmp(argv[i], "--dump-window-table")) {
			/* Same purpose as --dump-rearm-table: the denominator
			 * rule is written twice, and drift between the copies
			 * would accept a session this program refused. */
			static struct kwindow kw;
			static const uint32_t F[6][3] = {
				{100, 140, 146}, {100, 140, 139},
				{100, 141, 146}, {100, 140, 150},
				{100, 140, 140}, {100, 100, 100},
			};
			int g, lo, at, fi, si, sa, bv, bi, j;

			for (g = 0; g <= 1; g++)
			 for (lo = 0; lo <= 1; lo++)
			  for (at = 0; at <= 1; at++)
			   for (fi = 0; fi < 6; fi++)
			    for (si = 0; si <= 1; si++)
			     for (sa = 0; sa <= 1; sa++)
			      for (bv = 0; bv <= 1; bv++)
			       for (bi = 0; bi <= 1; bi++) {
				struct r1_snapshot *sp[3];
				unsigned sens_i = si ? 20 : 0;
				unsigned sens_a = sa ? 21 : 20;
				unsigned nvalid = bv ? 3 : 0;
				unsigned ninval = bi ? 1 : 0;

				memset(&kw, 0, sizeof(kw));
				kw.enabled = true;
				kw.field_idx = R1H_CAND_CFG0;
				sp[0] = &kw.s0; sp[1] = &kw.s1; sp[2] = &kw.s2;
				for (j = 0; j < 3; j++) {
					sp[j]->ok = true;
					sp[j]->w[R1H_CAPS_FLAGS] = R1_CAP_DMA;
					sp[j]->w[R1H_SNAPSHOT_ATOMIC] =
						(j == 2) ? (uint32_t)at : 1u;
					sp[j]->w[R1H_RESET_GENERATION] =
						(g && j == 1) ? 8u : 7u;
					sp[j]->w[R1H_LOST] =
						(lo && j == 2) ? 1u : 0u;
					sp[j]->w[R1H_CAND_CFG0] = F[fi][j];
				}
				kwindow_derive(&kw, sens_i, sens_a,
					       nvalid, ninval);
				printf("%d %d %d %d %u %u %u %u %s\n",
				       g, lo, at, fi, sens_i, sens_a,
				       nvalid, ninval, kw.code);
			       }
			return 0;
		}
		else if (!strcmp(argv[i], "--selftest-snapshot")) {
			return selftest_snapshot();
		}
		else if (!strcmp(argv[i], "--dump-rearm-table")) {
			/*
			 * The verdict rule lives twice: here and in
			 * r1a_manifest.py. Two copies that drift would let a
			 * session be accepted downstream that this program
			 * refused to run, so the table is emitted rather than
			 * described and the validator's selftest diffs it
			 * against its own. Not a mode anyone runs by hand.
			 */
			static struct rearm_pf pf;
			unsigned c, n_, r_;
			int perf, base;

			for (perf = 0; perf <= 1; perf++)
			 for (base = 0; base <= 1; base++)
			  for (c = 0; c <= 6; c++)
			   for (n_ = 0; n_ <= c; n_++)
			    for (r_ = 0; r_ <= c; r_++) {
				bool d = false;
				const char *v;

				memset(&pf, 0, sizeof(pf));
				pf.performed = perf;
				pf.baseline.progress = base;
				pf.cycles = c;
				pf.none.progress_ok = n_;
				pf.reset.progress_ok = r_;
				v = rearm_verdict(&pf, &d);
				printf("%d %d %u %u %u %s %d\n",
				       perf, base, c, n_, r_, v, d ? 1 : 0);
			    }
			return 0;
		}
		else { usage(argv[0]); return 2; }
	}

	if (epoch_json_path) {
		if (manual_epoch)
			die("--epoch-json cannot be mixed with --epoch-id or --sha-* epoch fields");
		load_epoch_json(epoch_json_path, &r);
	}


	/* ---- abort conditions, spec section 11. None of these degrade. ---- */
	if (selftest_sha)
		goto sha_only;
	if (!selftest && !dev_path && (vid < 0 || pid < 0)) {
		usage(argv[0]);
		return 2;
	}
	if (r.depth < 1 || r.depth > MAX_DEPTH)
		die("depth must be 1..%d", MAX_DEPTH);
	if (r.attempts_wanted > MAX_ATTEMPTS)
		die("attempts must be <= %d", MAX_ATTEMPTS);
	if (!r.rearm_probe_len)
		r.rearm_probe_len = r.xfer_len;
	if (r.rearm_cycles &&
	    (r.rearm_cycles < 3 || r.rearm_cycles > REARM_MAX_CYCLES))
		die("--rearm-cycles must be 0 or 3..%d: below three cycles the "
		    "two arms cannot separate a toggle mismatch from one bad "
		    "transfer", REARM_MAX_CYCLES);
	if (r.rearm_method == REARM_NONE && r.rearm_cycles)
		die("--rearm-reset none makes both pre-flight arms identical, "
		    "so the test has no discriminating power by construction. "
		    "Use --rearm-cycles 0 if the intent is to record that no "
		    "re-arm evidence exists");
	if (r.rearm_timeout_ms < 50)
		die("--rearm-timeout-ms must be at least 50");
	/*
	 * These are EXPECTATIONS from here on. They say what the operator
	 * believes the target is; the dump says what it is, and a mismatch
	 * aborts. Nothing in the manifest is sourced from them.
	 */
	if (g_dma != 1)
		die("--g-dma must be 1: buffer DMA is the frozen scope");
	if (g_dma_desc != 0)
		die("--g-dma-desc must be 0: descriptor DMA is out of scope");
	if (abi_v != 9 || abi_h != 112 || abi_r != 80)
		die("observer ABI must be v9 / header 112 / record 80");
	if (snap != 1)
		die("--snapshot-atomic must be 1");
	if (lost != 0)
		die("--lost must be 0: a session that dropped records cannot "
		    "support a negative result");
	if (overlap != 0 && (!strcmp(r.mode, "delayed-disable") ||
			     !strcmp(r.mode, "delayed-dequeue")))
		die("delayed modes require --overlap-count 0");
	if (!selftest && !r.snapshot_cmd)
		die("--snapshot-cmd is required. Target facts and the "
		    "denominator are read from the observer dump, not from "
		    "this command line; without a way to fetch the dump the "
		    "run cannot produce a manifest that says where its "
		    "numbers came from");
	if (!selftest && *r.usbmon_path && (!r.usbmon_start_cmd || !r.usbmon_stop_cmd))
		die("--usbmon requires both --usbmon-start-cmd and --usbmon-stop-cmd: capture is campaign-scoped and must have an explicit close barrier");
	if (!selftest) {
		const char *hv[] = { r.h_image, r.h_patch, r.h_parser, r.h_gate, r.h_gate91,
			r.h_val, r.h_usbmon_verify, r.h_holder_merge, r.h_verdict };
		unsigned hi;
		for (hi = 0; hi < sizeof(hv)/sizeof(hv[0]); hi++)
			if (!sha256_text_ok(hv[hi]))
				die("all epoch tool/image hashes except the harness self-hash must be lowercase sha256 before the run starts");
	}
	if (!selftest || epoch_json_path) {
		if (sha256_file("/proc/self/exe", self_sha) < 0)
			die("cannot hash running harness binary via /proc/self/exe");
		if (r.h_harness && *r.h_harness && strcmp(r.h_harness, self_sha))
			die("--sha-harness does not match the running binary (expected %s actual %s)", r.h_harness, self_sha);
		r.h_harness = self_sha;
	}
	
	/* Trigger shape. wLength is always zero; dwc2_r1_classify_setup()
	 * requires !w_length, and a non-zero wIndex on SET_CONFIGURATION
	 * yields TRIG_NONE -- no denominator and a silently lost attempt. */
	if (!strcmp(r.mode, "cfg0")) {
		r.trig_type = 0x00;
		r.trig_request = USB_REQ_SET_CONFIGURATION;
		r.trig_wvalue = 0;
		r.trig_windex = 0;
	} else if (!strcmp(r.mode, "cfgn")) {
		r.trig_type = 0x00;
		r.trig_request = USB_REQ_SET_CONFIGURATION;
		r.trig_wvalue = (uint16_t)cfgn_value;
		r.trig_windex = 0;
	} else if (!strcmp(r.mode, "interface-sync")) {
		r.trig_type = 0x01;                    /* RECIP_INTERFACE */
		r.trig_request = USB_REQ_SET_INTERFACE;
		r.trig_wvalue = 0;                     /* alternate setting 0 */
		r.trig_windex = (uint16_t)alt_intf;
	} else {
		die("--mode must be cfg0, cfgn or interface-sync");
	}
	if (r.trig_type == 0x00 && r.trig_windex != 0)
		die("SET_CONFIGURATION with non-zero wIndex classifies as "
		    "TRIG_NONE in the observer");

	/* The counter P4 will use as this branch's denominator. Named here so
	 * the manifest says which field the differences were taken from. */
	if (!strcmp(r.mode, "cfg0")) {
		r.kw.field_idx = R1H_CAND_CFG0;
		r.kw.field_name = "candidate_cfg0_seen";
		r.kw.setup_field_idx = R1H_SETUP_CFG0; r.kw.setup_field_name = "setup_cfg0_seen";
	} else if (!strcmp(r.mode, "cfgn")) {
		r.kw.field_idx = R1H_CAND_CFGN;
		r.kw.field_name = "candidate_cfgn_seen";
		r.kw.setup_field_idx = R1H_SETUP_CFGN; r.kw.setup_field_name = "setup_cfgn_seen";
	} else {
		r.kw.field_idx = R1H_CAND_INTF;
		r.kw.field_name = "candidate_intf_seen";
		r.kw.setup_field_idx = R1H_SETUP_INTF; r.kw.setup_field_name = "setup_intf_seen";
	}
	r.kw.s0.label = "S0"; r.kw.s0.when = "after_rearm_before_sensitivity";
	r.kw.s1.label = "S1"; r.kw.s1.when = "after_sensitivity_before_campaign";
	r.kw.s2.label = "S2"; r.kw.s2.when = "after_campaign";

sha_only:
	signal(SIGINT, on_sig);
	signal(SIGTERM, on_sig);

	/*
	 * Hash the artifacts the operator supplied before either path needs
	 * them. r.dump_sha points at a literal until a real digest exists, so
	 * it is repointed here rather than written through.
	 */
	/*
	 * ONLY the selftest hashes here. On a real run the dump does not exist
	 * yet -- it is fetched after the campaign -- and the usbmon capture is
	 * still being written. Hashing either one now would pin a prefix of
	 * the evidence and record it as the evidence.
	 */
	if (selftest) {
		if (*r.dump_path && sha256_file(r.dump_path, dump_sha) == 0)
			r.dump_sha = dump_sha;
		if (*r.usbmon_path &&
		    sha256_file(r.usbmon_path, usbmon_sha) == 0)
			r.usbmon_sha = usbmon_sha;
	}

	if (selftest_sha) {
		/* Everything in the campaign hangs on these digests: the epoch
		 * identity, the duplicate-trace check in P4, the artifact
		 * manifest. A wrong implementation would agree with itself and
		 * nothing else, so it is checked against the published NIST
		 * vectors rather than against sha256sum, which may not be on
		 * the target. */
		static const struct { const char *in, *want; } v[] = {
		 {"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934c"
		      "a495991b7852b855"},
		 {"abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9c"
			 "b410ff61f20015ad"},
		 {"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
		  "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167"
		  "f6ecedd419db06c1"},
		};
		unsigned k, bad = 0;

		for (k = 0; k < sizeof(v) / sizeof(v[0]); k++) {
			char got[65];
			sha256_t sc;

			sha256_init(&sc);
			sha256_update(&sc, v[k].in, strlen(v[k].in));
			sha256_final(&sc, got);
			printf("  %-8s %s %s\n",
			       *v[k].in ? "vector" : "empty",
			       strcmp(got, v[k].want) ? "FAIL" : "ok  ", got);
			if (strcmp(got, v[k].want))
				bad++;
		}
		/*
		 * The standard one-million-'a' vector, fed in small chunks so
		 * the streaming path and the length encoding are exercised
		 * rather than just the single-shot case.
		 */
		{
			static const char *want =
				"cdc76e5c9914fb9281a1c7e284d73e67"
				"f1809a48a497200e046d39ccc7112cd0";
			char chunk[1000], got[65];
			sha256_t sc;
			unsigned q;

			memset(chunk, 'a', sizeof(chunk));
			sha256_init(&sc);
			for (q = 0; q < 1000; q++)
				sha256_update(&sc, chunk, sizeof(chunk));
			sha256_final(&sc, got);
			printf("  %-8s %s %s\n", "1M 'a'",
			       strcmp(got, want) ? "FAIL" : "ok  ", got);
			if (strcmp(got, want))
				bad++;
		}
		printf("SHA256 SELFTEST: %s\n", bad ? "FAIL" : "PASS");
		return bad ? 1 : 0;
	}

	if (selftest) {
		/* No device. Fabricate a plausible session and emit its
		 * manifest, so the JSON this program writes can be checked
		 * against r1a_manifest.py without hardware. The numbers are
		 * synthetic; the SHAPE is the thing under test. */
		struct target st;
		unsigned k;

		memset(&st, 0, sizeof(st));
		st.ep_out = 0x02;
		st.intf = 0; st.busnum = 1; st.devnum = 5;
		r.sens_issued = r.sens_observed = 20;
		iso_now(r.t_start);
		for (k = 0; k < 4; k++) {
			struct attempt *a = &r.att[r.n_att++];

			memset(a, 0, sizeof(*a));
			a->n = k + 1; a->usb_bus = 1; a->usb_device = 5; a->bulk_ep = 2;
			iso_now(a->t_arm);
			iso_now(a->t_trigger);
			a->checked = true;
			a->inflight_at_trigger = (k == 3) ? 0 : 8;
			a->urb_completed = (k == 3);
			a->trigger_attempted = (k != 3);
			a->valid = (k != 3);
			a->invalid_reason = (k == 3) ? "not_outstanding" : NULL;
		}
		r.peak_inflight = 8;

		/* A synthetic re-arm pre-flight, so the shape the validator
		 * has to accept is exercised without hardware: control arm
		 * dead, treatment arm clean, which is the discriminating
		 * outcome. */
		r.rearm.performed = true;
		r.rearm.cycles = 4;
		r.rearm.probe_len = r.rearm_probe_len;
		r.rearm.timeout_ms = r.rearm_timeout_ms;
		r.rearm.method_in_use = REARM_RESETEP;
		r.rearm.none.label = "none";
		r.rearm.none.method = REARM_NONE;
		r.rearm.reset.label = "resetep";
		r.rearm.reset.method = REARM_RESETEP;
		iso_now(r.rearm.baseline.t0);
		iso_now(r.rearm.baseline.t1);
		r.rearm.baseline.submitted = true;
		r.rearm.baseline.reaped = true;
		r.rearm.baseline.actual_length = (int)r.rearm_probe_len;
		r.rearm.baseline.progress = true;
		for (k = 0; k < 4; k++) {
			struct rearm_cycle *cn = &r.rearm.none.c[k];
			struct rearm_cycle *cr = &r.rearm.reset.c[k];

			memset(cn, 0, sizeof(*cn));
			memset(cr, 0, sizeof(*cr));
			cn->n = cr->n = k + 1;
			iso_now(cn->t0); iso_now(cn->t1);
			iso_now(cr->t0); iso_now(cr->t1);
			cn->submitted = cr->submitted = true;
			cn->reaped = false;
			cn->status = -110;              /* ETIMEDOUT */
			cn->actual_length = 0;
			cn->progress = false;
			cr->reaped = true;
			cr->status = 0;
			cr->actual_length = (int)r.rearm_probe_len;
			cr->progress = true;
			r.rearm.none.attempted++;
			r.rearm.reset.attempted++;
			r.rearm.reset.progress_ok++;
		}
		r.rearm.verdict = rearm_verdict(&r.rearm,
						&r.rearm.discriminating);

		/* Three synthetic snapshots, so the denominator shape the
		 * validator must accept is exercised without a target. k = 2
		 * deliberately: one SETUP can stop more than one endpoint, and
		 * a fixture that only ever shows k = 1 would hide the fact
		 * that k is measured. */
		r.sens_attempted = r.sens_issued;
		r.kw.enabled = true;
		{
			struct r1_snapshot *sn[3] = {
				&r.kw.s0, &r.kw.s1, &r.kw.s2 };
			static const char *WHEN[3] = {
				"after_rearm_before_sensitivity",
				"after_sensitivity_before_campaign",
				"after_campaign" };
			static const char *LBL[3] = { "S0", "S1", "S2" };
			unsigned base[3] = { 100, 140, 146 };

			for (k = 0; k < 3; k++) {
				memset(sn[k], 0, sizeof(*sn[k]));
				sn[k]->label = LBL[k];
				sn[k]->when = WHEN[k];
				sn[k]->ok = true;
				iso_now(sn[k]->utc);
				snprintf(sn[k]->path, sizeof(sn[k]->path),
					 "r1-snapshot-%u-%s.bin", k, LBL[k]);
				snprintf(sn[k]->sha, sizeof(sn[k]->sha),
					 "%064u", k + 1);
				sn[k]->w[R1H_MAGIC] = R1_HDR_MAGIC;
				sn[k]->w[R1H_VERSION] = 9;
				sn[k]->w[R1H_HEADER_SIZE] = R1_HDR_BYTES;
				sn[k]->w[R1H_RECORD_SIZE] = 80;
				sn[k]->w[R1H_CAPS_FLAGS] = R1_CAP_DMA;
				sn[k]->w[R1H_SNAPSHOT_ATOMIC] = 1;
				sn[k]->w[R1H_RESET_GENERATION] = 7;
				sn[k]->w[R1H_GSNPSID] = 0x4F54300A;
				sn[k]->w[R1H_COUNT] = 0;
				sn[k]->w[R1H_CAUSAL_SYNC] = (k == 0) ? 10 : (k == 1 ? 30 : 33);
				sn[k]->w[r.kw.setup_field_idx] = (k == 0) ? 50 : (k == 1 ? 70 : 73);
				sn[k]->w[r.kw.field_idx] = base[k];
			}
		}
		kwindow_derive(&r.kw, r.sens_issued, r.sens_attempted, 3, 1);
		/* Same rule as a real run: the shipped dump IS S2. */
		r.dump_path = r.kw.s2.path;
		r.dump_sha = r.kw.s2.sha;
		add_window(&r, "enumeration", r.t_start, r.t_start);
		iso_now(r.t_end);
		write_manifest(&r, &st, man_path,
			       "cafebabecafebabecafebabecafebabe"
			       "cafebabecafebabecafebabecafebabe");
		return 0;
	}

	/* ---------------------------------------------------- open target */
	t.fd = -1;
	if (dev_path) {
		if (open_target(&t, dev_path) < 0)
			die("cannot open %s: %s", dev_path, strerror(errno));
	} else if (find_target(&t, (uint16_t)vid, (uint16_t)pid) < 0) {
		die("no device %04x:%04x under /dev/bus/usb", vid, pid);
	}
	if (want_intf >= 0)
		t.intf = want_intf;
	if (t.intf < 0)
		die("no interface owns a bulk OUT endpoint on this device");
	if (expect_ep >= 0 && t.ep_out != (uint8_t)expect_ep)
		die("descriptors give endpoint 0x%02x but --expect-ep is "
		    "0x%02x; the two sides disagree about which endpoint is "
		    "under test", t.ep_out, (unsigned)expect_ep);

	printf("target %s  %04x:%04x  intf %d  ep 0x%02x  mps %u  cfg %u\n",
	       t.path, t.vid, t.pid, t.intf, t.ep_out, t.ep_mps, t.cfg_value);

	{
		unsigned intf = (unsigned)t.intf;

		if (ioctl(t.fd, USBDEVFS_CLAIMINTERFACE, &intf) < 0)
			die("cannot claim interface %u: %s (a host driver may "
			    "be bound)", intf, strerror(errno));
	}
	if (pool_init(&p, r.depth, r.xfer_len) < 0)
		die("out of memory for the URB pool");

	iso_now(r.t_start);
	log = fopen(log_path, "w");
	if (!log)
		die("cannot write %s: %s", log_path, strerror(errno));
	fprintf(log, "r1a_host session start %s\ntarget %s %04x:%04x intf %d "
		"ep 0x%02x mode %s depth %u xfer %u\n",
		r.t_start, t.path, t.vid, t.pid, t.intf, t.ep_out,
		r.mode, r.depth, r.xfer_len);

	/* -------------------------------------------- re-arm pre-flight */
	/*
	 * Before the sensitivity burst, because that burst itself resyncs:
	 * if the restore path cannot hand back a working endpoint, every
	 * count downstream of it describes a broken instrument.
	 */
	rearm_preflight(&t, &p, &r, t.vid, t.pid);
	fprintf(log, "rearm performed=%d baseline_progress=%d cycles=%u "
		"none=%u %s=%u reenum=%u/%u verdict=%s discriminating=%d\n",
		r.rearm.performed, r.rearm.baseline.progress, r.rearm.cycles,
		r.rearm.none.progress_ok, r.rearm.reset.label,
		r.rearm.reset.progress_ok, r.rearm.none.reenum,
		r.rearm.reset.reenum, r.rearm.verdict,
		r.rearm.discriminating);

	if (!rearm_verdict_admits_campaign(r.rearm.verdict)) {
		fclose(log);
		iso_now(r.t_end);
		sha256_file(log_path, log_sha);
		write_manifest(&r, &t, man_path, log_sha);
		die("re-arm verdict is %s, so the campaign does not start. A "
		    "manifest recording exactly this was written to %s. The "
		    "designated fallback is one destructive attempt per fresh "
		    "enumeration epoch: --attempts 1 with the device "
		    "re-enumerated between attempts, which costs throughput "
		    "and makes B the number of epochs, not the number of "
		    "attempts, but needs no working re-arm at all.",
		    r.rearm.verdict, man_path);
	}
	if (!r.rearm.discriminating)
		printf("note: the re-arm pre-flight passed in BOTH arms, so it "
		       "did not discriminate. The reset stays enabled as a "
		       "precaution, but this session carries no evidence that "
		       "it is what makes the restore work.\n");

	/*
	 * S0 -- after the re-arm pre-flight, before the sensitivity burst.
	 * Deliberately here and not earlier: the re-arm cycles fire real
	 * triggers, and counting them would inflate k.
	 */
	r.kw.enabled = true;
	if (!snapshot_take(&r.kw.s0, r.snapshot_cmd, r.snapshot_dir, 0))
		die("could not take the S0 dump snapshot: %s", r.kw.s0.err);
	if ((r.kw.s0.w[R1H_CAPS_FLAGS] & R1_CAP_DMA) == 0 ||
	    (r.kw.s0.w[R1H_CAPS_FLAGS] & R1_CAP_DDMA) != 0)
		die("the dump says caps_flags=0x%x: this target is not "
		    "buffer-DMA-only, whatever --g-dma said",
		    r.kw.s0.w[R1H_CAPS_FLAGS]);
	if (r.kw.s0.w[R1H_LOST])
		die("the dump says lost=%u before the campaign even started",
		    r.kw.s0.w[R1H_LOST]);
	printf("S0  %s  %s=%u  reset_gen=%u  caps=0x%x\n", r.kw.s0.sha,
	       r.kw.field_name, r.kw.s0.w[r.kw.field_idx],
	       r.kw.s0.w[R1H_RESET_GENERATION], r.kw.s0.w[R1H_CAPS_FLAGS]);

	/* ------------------------------------------------------ preflight */
	preflight_burst(&t, &p, &r, (uint16_t)t.vid, (uint16_t)t.pid);

	/* S1 closes sensitivity. Both reachability counts are derived from the
	 * authenticated dump headers: no operator-provided observed count exists. */
	if (!snapshot_take(&r.kw.s1, r.snapshot_cmd, r.snapshot_dir, 1))
		die("could not take the S1 dump snapshot: %s", r.kw.s1.err);
	if (r.kw.s1.w[R1H_CAUSAL_SYNC] < r.kw.s0.w[R1H_CAUSAL_SYNC] ||
	    r.kw.s1.w[r.kw.setup_field_idx] < r.kw.s0.w[r.kw.setup_field_idx])
		die("sensitivity counters went backwards between S0 and S1");
	r.sens_observed = r.kw.s1.w[R1H_CAUSAL_SYNC] - r.kw.s0.w[R1H_CAUSAL_SYNC];
	{
		unsigned setup_seen = r.kw.s1.w[r.kw.setup_field_idx] - r.kw.s0.w[r.kw.setup_field_idx];
		fprintf(log, "preflight issued=%u causal_sync=%u setup=%u\n", r.sens_issued, r.sens_observed, setup_seen);
		if (!(r.sens_issued >= 1 && r.sens_issued == r.sens_observed && r.sens_issued == setup_seen))
			die("sensitivity is not SENSITIVE: issued=%u causal_sync_delta=%u setup_delta=%u", r.sens_issued, r.sens_observed, setup_seen);
	}
	printf("sensitivity: SENSITIVE (%u issued == causal_sync == setup)\n", r.sens_issued);
	printf("S1  %s  %s=%u  (k window delta %u over %u attempts)\n",
	       r.kw.s1.sha, r.kw.field_name, r.kw.s1.w[r.kw.field_idx],
	       r.kw.s1.w[r.kw.field_idx] - r.kw.s0.w[r.kw.field_idx],
	       r.sens_attempted);

	/* The usbmon witness is campaign-only. Starting it here prevents re-arm
	 * and sensitivity controls from becoming unattributable extra traffic. */
	if (r.usbmon_start_cmd && system(r.usbmon_start_cmd) != 0)
		die("--usbmon-start-cmd failed: campaign wire evidence did not start");

	/* ------------------------------------------------------- campaign */
	for (i = 0; i < r.attempts_wanted && !stop_flag; i++) {
		struct attempt *a = &r.att[r.n_att];
		char t0[TSLEN], t1[TSLEN];

		do_attempt(&t, &p, &r, a, i + 1);
		r.n_att++;
		fprintf(log, "attempt %u valid=%d inflight=%u reason=%s "
			"trigger_rc=%d errno=%d\n", a->n, a->valid,
			a->inflight_at_trigger,
			a->invalid_reason ? a->invalid_reason : "-",
			a->trigger_rc, a->trigger_errno);

		if (a->trigger_attempted && !a->valid) {
			/*
			 * The control request went out and the attempt still
			 * did not qualify. Whatever candidates it left are in
			 * an aggregate counter with no way to subtract them,
			 * so the batch stops here and is marked void rather
			 * than being quietly shortened by one.
			 */
			r.batch_void = true;
			r.void_reason = a->invalid_reason;
			fprintf(log, "batch VOID at attempt %u (%s): the "
				"trigger reached the wire\n", a->n,
				a->invalid_reason ? a->invalid_reason : "-");
			break;
		}

		iso_now(t0);
		if (resync(&t, &p, &r) < 0) {
			iso_now(t1);
			if (reopen_target(&t, (uint16_t)t.vid,
					  (uint16_t)t.pid, 5000) < 0) {
				fprintf(log, "device did not return after "
					"attempt %u\n", a->n);
				add_window(&r, "enumeration", t0, t1);
				break;
			}
			add_window(&r, "enumeration", t0, t1);
		}
		if ((i + 1) % 10 == 0)
			printf("  %u/%u attempts\n", i + 1, r.attempts_wanted);
	}
	if (stop_flag)
		printf("interrupted after %u attempts\n", r.n_att);

	/* --------------------------------------------------------- close */
	{
		unsigned intf = (unsigned)t.intf;

		pool_discard_all(t.fd, &p);
		ioctl(t.fd, USBDEVFS_RELEASEINTERFACE, &intf);
	}
	/*
	 * Order is the whole content of this block. Stop the capture, fetch
	 * the final dump, and only then hash either of them. An artifact
	 * hashed while it is still being written has a digest that pins a
	 * prefix of the evidence.
	 */
	if (r.usbmon_stop_cmd && system(r.usbmon_stop_cmd) != 0)
		die("--usbmon-stop-cmd failed: capture closure is an evidence barrier, not a warning");
	if (!snapshot_take(&r.kw.s2, r.snapshot_cmd, r.snapshot_dir, 2))
		die("could not take the S2 dump snapshot: %s", r.kw.s2.err);
	r.dump_path = r.kw.s2.path;
	r.dump_sha = r.kw.s2.sha;
	if (*r.usbmon_path) {
		if (sha256_file(r.usbmon_path, usbmon_sha) < 0)
			die("cannot hash closed usbmon capture %s", r.usbmon_path);
		r.usbmon_sha = usbmon_sha;
	}

	{
		unsigned bv = 0, bi = 0, j;

		for (j = 0; j < r.n_att; j++)
			r.att[j].valid ? bv++ : bi++;
		kwindow_derive(&r.kw, r.sens_issued, r.sens_attempted, bv, bi);
		printf("S2  %s  %s=%u  campaign delta %lu, k=%u, expected %lu"
		       " -> %s\n", r.kw.s2.sha, r.kw.field_name,
		       r.kw.s2.w[r.kw.field_idx], r.kw.delta_camp, r.kw.k,
		       r.kw.expected,
		       r.kw.problem ? r.kw.problem : "relation holds");
	}

	iso_now(r.t_end);
	fprintf(log, "session end %s attempts=%u peak_inflight=%u "
		"delta_sens=%lu delta_camp=%lu k=%u relation=%d void=%d\n",
		r.t_end, r.n_att, r.peak_inflight, r.kw.delta_sens,
		r.kw.delta_camp, r.kw.k, r.kw.relation_ok, r.batch_void);
	fclose(log);

	if (sha256_file(log_path, log_sha) < 0)
		die("cannot hash %s", log_path);
	write_manifest(&r, &t, man_path, log_sha);

	if (r.batch_void)
		die("batch VOID (%s): a trigger reached the wire on an "
		    "attempt that did not qualify, and the candidates it left "
		    "cannot be subtracted from an aggregate counter. The "
		    "manifest records it; run another batch",
		    r.void_reason ? r.void_reason : "unknown");
	if (r.kw.problem)
		die("the measured denominator is not usable: %s. The manifest "
		    "records the three snapshots and their differences",
		    r.kw.problem);

	pool_free(&p);
	close(t.fd);
	return 0;
}
