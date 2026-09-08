/*
 * r1a_ffs_out_v2 -- FunctionFS async Bulk-OUT harness for the DWC2 R1A campaign.
 * TEST-ONLY.
 *
 * WHY THIS EXISTS
 * ---------------
 * The previous harness used N blocking pthread readers on one endpoint file and
 * was treated as "N outstanding requests".  It is not.  From the pinned tree:
 *
 *   drivers/usb/gadget/function/f_fs.c:1026
 *       ret = ffs_mutex_lock(&epfile->mutex, file->f_flags & O_NONBLOCK);
 *   drivers/usb/gadget/function/f_fs.c:1106
 *       } else if (!io_data->aio) {
 *   drivers/usb/gadget/function/f_fs.c:1109
 *               req = ep->req;
 *   drivers/usb/gadget/function/f_fs.c:1126
 *               ret = usb_ep_queue(ep->ep, req, GFP_ATOMIC);
 *   drivers/usb/gadget/function/f_fs.c:1130
 *               spin_unlock_irq(&epfile->ffs->eps_lock);
 *   drivers/usb/gadget/function/f_fs.c:1132
 *               if (wait_for_completion_interruptible(&io_data->done)) {
 *   drivers/usb/gadget/function/f_fs.c:1157
 *               goto error_mutex;
 *
 * epfile->mutex is released at exactly one place, f_fs.c:1197.  The synchronous
 * branch queues the request and then waits for completion WITH THAT MUTEX STILL
 * HELD, so reader 2..N never reach usb_ep_queue() at all.  Independently, the
 * sync branch reuses the single preallocated ep->req, so there is only one
 * usb_request object to be outstanding in the first place.
 *
 *   => blocking readers on one epfile give a hard ceiling of ONE outstanding
 *      USB request, no matter how many threads exist.
 *
 * The asynchronous branch (f_fs.c:1158) instead does
 *       usb_ep_alloc_request(ep->ep, GFP_ATOMIC)
 * per submission, which is what actually produces queue depth.  So this harness
 * uses Linux AIO (io_submit) and nothing else.
 *
 * It does not assert its own preconditions, it measures them:
 *   - ready=1 comes from an observed FUNCTIONFS_ENABLE event, not from a sleep
 *   - the OUT endpoint is confirmed with FUNCTIONFS_ENDPOINT_DESC, not assumed
 *   - queue depth is reported as a measured peak, not as the configured value
 *   - bytes actually received prove host traffic reached the endpoint
 *
 * That last group is what makes a null result interpretable.  A run that sees
 * no timeout is only evidence of absence if the harness is shown to have been
 * sensitive: real depth, real traffic, real duration.
 *
 * Raw AIO syscalls are used rather than libaio so the binary can be built
 * static for a board whose rootfs contents are unknown.
 *
 *   cc -O2 -Wall -o r1a_ffs_out_v2 r1a_ffs_out_v2.c
 *   ./r1a_ffs_out_v2 --ffs /dev/ffs-r1a --depth 8 --seconds 30 \
 *                    --artifact batch_1.json
 */
#define _GNU_SOURCE

#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <sys/eventfd.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>

#include <linux/aio_abi.h>
#include <linux/usb/functionfs.h>

/*
 * CPU_TO_LE32()/CPU_TO_LE16() from glibc's <endian.h> expand to a static inline
 * (__uint32_identity), which is not a constant expression, so they cannot
 * initialise a static descriptor blob.  These are constant-foldable in both
 * byte orders: __builtin_bswap* is a constant expression for constant input.
 */
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
#define CPU_TO_LE32(x)	((__u32)(x))
#define CPU_TO_LE16(x)	((__u16)(x))
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
#define CPU_TO_LE32(x)	((__u32)__builtin_bswap32((__u32)(x)))
#define CPU_TO_LE16(x)	((__u16)__builtin_bswap16((__u16)(x)))
#else
#error unsupported byte order
#endif

#define MAX_DEPTH	256
#define DEF_DEPTH	8
#define DEF_BUFLEN	16384
#define DEF_SECONDS	30

/* ------------------------------------------------------------ AIO syscalls */

static long sys_io_setup(unsigned n, aio_context_t *ctx)
{
	return syscall(__NR_io_setup, n, ctx);
}

static long sys_io_destroy(aio_context_t ctx)
{
	return syscall(__NR_io_destroy, ctx);
}

static long sys_io_submit(aio_context_t ctx, long n, struct iocb **cb)
{
	return syscall(__NR_io_submit, ctx, n, cb);
}

static long sys_io_getevents(aio_context_t ctx, long min, long max,
			     struct io_event *ev, struct timespec *to)
{
	return syscall(__NR_io_getevents, ctx, min, max, ev, to);
}

/* ----------------------------------------------------- descriptors/strings */
/*
 * Endpoint ORDER defines the epN file names: the first endpoint descriptor
 * becomes ep1, the second ep2.  IN is declared first so that ep2 is the OUT
 * endpoint, matching the campaign's requirement.  This is still verified at
 * runtime rather than trusted.
 */
static const struct {
	struct usb_functionfs_descs_head_v2 header;
	__le32 fs_count;
	__le32 hs_count;
	struct {
		struct usb_interface_descriptor intf;
		struct usb_endpoint_descriptor_no_audio bulk_in;
		struct usb_endpoint_descriptor_no_audio bulk_out;
	} __attribute__((packed)) fs_descs, hs_descs;
} __attribute__((packed)) descriptors = {
	.header = {
		.magic = CPU_TO_LE32(FUNCTIONFS_DESCRIPTORS_MAGIC_V2),
		.flags = CPU_TO_LE32(FUNCTIONFS_HAS_FS_DESC |
				 FUNCTIONFS_HAS_HS_DESC),
		.length = CPU_TO_LE32(sizeof(descriptors)),
	},
	.fs_count = CPU_TO_LE32(3),
	.fs_descs = {
		.intf = {
			.bLength = sizeof(descriptors.fs_descs.intf),
			.bDescriptorType = USB_DT_INTERFACE,
			.bNumEndpoints = 2,
			.bInterfaceClass = USB_CLASS_VENDOR_SPEC,
			.iInterface = 1,
		},
		.bulk_in = {
			.bLength = sizeof(descriptors.fs_descs.bulk_in),
			.bDescriptorType = USB_DT_ENDPOINT,
			.bEndpointAddress = 1 | USB_DIR_IN,
			.bmAttributes = USB_ENDPOINT_XFER_BULK,
		},
		.bulk_out = {
			.bLength = sizeof(descriptors.fs_descs.bulk_out),
			.bDescriptorType = USB_DT_ENDPOINT,
			.bEndpointAddress = 2 | USB_DIR_OUT,
			.bmAttributes = USB_ENDPOINT_XFER_BULK,
		},
	},
	.hs_count = CPU_TO_LE32(3),
	.hs_descs = {
		.intf = {
			.bLength = sizeof(descriptors.hs_descs.intf),
			.bDescriptorType = USB_DT_INTERFACE,
			.bNumEndpoints = 2,
			.bInterfaceClass = USB_CLASS_VENDOR_SPEC,
			.iInterface = 1,
		},
		.bulk_in = {
			.bLength = sizeof(descriptors.hs_descs.bulk_in),
			.bDescriptorType = USB_DT_ENDPOINT,
			.bEndpointAddress = 1 | USB_DIR_IN,
			.bmAttributes = USB_ENDPOINT_XFER_BULK,
			.wMaxPacketSize = CPU_TO_LE16(512),
		},
		.bulk_out = {
			.bLength = sizeof(descriptors.hs_descs.bulk_out),
			.bDescriptorType = USB_DT_ENDPOINT,
			.bEndpointAddress = 2 | USB_DIR_OUT,
			.bmAttributes = USB_ENDPOINT_XFER_BULK,
			.wMaxPacketSize = CPU_TO_LE16(512),
		},
	},
};

#define STR_INTERFACE "DWC2 R1A OUT"

static const struct {
	struct usb_functionfs_strings_head header;
	struct {
		__le16 code;
		const char str1[sizeof(STR_INTERFACE)];
	} __attribute__((packed)) lang0;
} __attribute__((packed)) strings = {
	.header = {
		.magic = CPU_TO_LE32(FUNCTIONFS_STRINGS_MAGIC),
		.length = CPU_TO_LE32(sizeof(strings)),
		.str_count = CPU_TO_LE32(1),
		.lang_count = CPU_TO_LE32(1),
	},
	.lang0 = { CPU_TO_LE16(0x0409), STR_INTERFACE },
};

/* --------------------------------------------------------------- run state */

struct slot {
	struct iocb cb;
	unsigned char *buf;
	bool inflight;
};

struct run {
	/* configuration */
	const char *ffs_dir;
	unsigned depth;
	unsigned buflen;
	unsigned seconds;
	const char *artifact;
	const char *dump_desc;

	/* endpoint identity, as read back from the kernel */
	int ep_addr;
	int ep_xfer;
	int ep_mps;
	bool ep_verified;

	/* lifecycle */
	bool bound, ready, ever_ready;
	double t_start, t_bind, t_enable, t_disable, t_end;
	unsigned n_enable, n_disable, n_setup, n_suspend, n_resume;

	/* traffic */
	unsigned long long completions, bytes, errors, short_reads;
	unsigned long long post_disable_completions;
	unsigned peak_inflight, cur_inflight;
	double t_first_byte, t_last_byte;
	int last_errno;
};

static volatile sig_atomic_t stop_flag;

static void on_sigint(int s) { (void)s; stop_flag = 1; }

static double now_s(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

static const char *xfer_name(int a)
{
	switch (a & USB_ENDPOINT_XFERTYPE_MASK) {
	case USB_ENDPOINT_XFER_CONTROL: return "control";
	case USB_ENDPOINT_XFER_ISOC:    return "isoc";
	case USB_ENDPOINT_XFER_BULK:    return "bulk";
	case USB_ENDPOINT_XFER_INT:     return "interrupt";
	}
	return "unknown";
}

/* ------------------------------------------------------- endpoint identity */
/*
 * The campaign requires that ep2 IS the Bulk OUT endpoint, proven rather than
 * assumed.  FUNCTIONFS_ENDPOINT_DESC returns the descriptor the gadget core
 * actually bound, so a mismatch here is a hard stop, not a warning.
 */
static int verify_out_ep(int fd, struct run *r)
{
	struct usb_endpoint_descriptor d;
	int rev;

	memset(&d, 0, sizeof(d));
	if (ioctl(fd, FUNCTIONFS_ENDPOINT_DESC, &d) < 0) {
		fprintf(stderr, "FUNCTIONFS_ENDPOINT_DESC: %s\n",
			strerror(errno));
		return -1;
	}

	r->ep_addr = d.bEndpointAddress;
	r->ep_xfer = d.bmAttributes & USB_ENDPOINT_XFERTYPE_MASK;
	r->ep_mps = le16toh(d.wMaxPacketSize);

	rev = ioctl(fd, FUNCTIONFS_ENDPOINT_REVMAP);
	printf("  endpoint: bEndpointAddress=0x%02x dir=%s type=%s mps=%d "
	       "revmap=%d\n", d.bEndpointAddress,
	       (d.bEndpointAddress & USB_DIR_IN) ? "IN" : "OUT",
	       xfer_name(d.bmAttributes), r->ep_mps, rev);

	if (d.bEndpointAddress & USB_DIR_IN) {
		fprintf(stderr, "  FATAL: endpoint is IN, campaign needs OUT\n");
		return -1;
	}
	if (r->ep_xfer != USB_ENDPOINT_XFER_BULK) {
		fprintf(stderr, "  FATAL: endpoint is %s, campaign needs bulk\n",
			xfer_name(d.bmAttributes));
		return -1;
	}
	if (r->ep_mps <= 0) {
		fprintf(stderr, "  FATAL: wMaxPacketSize is %d\n", r->ep_mps);
		return -1;
	}

	r->ep_verified = true;
	return 0;
}

/* ------------------------------------------------------------- ep0 events */

static void handle_ep0(int ep0, struct run *r)
{
	struct usb_functionfs_event e;
	ssize_t n;

	n = read(ep0, &e, sizeof(e));
	if (n < 0) {
		if (errno != EAGAIN && errno != EINTR)
			fprintf(stderr, "ep0 read: %s\n", strerror(errno));
		return;
	}
	if (n != sizeof(e))
		return;

	switch (e.type) {
	case FUNCTIONFS_BIND:
		r->bound = true;
		r->t_bind = now_s();
		printf("  [ep0] BIND\n");
		break;
	case FUNCTIONFS_UNBIND:
		r->bound = false;
		printf("  [ep0] UNBIND\n");
		break;
	case FUNCTIONFS_ENABLE:
		r->ready = true;
		r->ever_ready = true;
		r->n_enable++;
		if (r->t_enable == 0)
			r->t_enable = now_s();
		printf("  [ep0] ENABLE  (ready=1)\n");
		break;
	case FUNCTIONFS_DISABLE:
		r->ready = false;
		r->n_disable++;
		r->t_disable = now_s();
		printf("  [ep0] DISABLE (ready=0)  <-- R1 window opens\n");
		break;
	case FUNCTIONFS_SETUP:
		r->n_setup++;
		/* ack the status stage so the host is not left hanging */
		if (e.u.setup.bRequestType & USB_DIR_IN) {
			if (write(ep0, NULL, 0) < 0)
				r->last_errno = errno;
		} else {
			if (read(ep0, NULL, 0) < 0)
				r->last_errno = errno;
		}
		break;
	case FUNCTIONFS_SUSPEND:
		r->n_suspend++;
		break;
	case FUNCTIONFS_RESUME:
		r->n_resume++;
		break;
	default:
		break;
	}
}

/* ----------------------------------------------------------- AIO plumbing */

static int submit_slot(aio_context_t ctx, struct slot *s, int epfd, int evfd,
		       unsigned buflen, unsigned idx, struct run *r)
{
	struct iocb *p = &s->cb;

	memset(p, 0, sizeof(*p));
	p->aio_data = idx;
	p->aio_lio_opcode = IOCB_CMD_PREAD;
	p->aio_fildes = epfd;
	p->aio_buf = (uintptr_t)s->buf;
	p->aio_nbytes = buflen;
	p->aio_offset = 0;
	p->aio_flags = IOCB_FLAG_RESFD;
	p->aio_resfd = evfd;

	if (sys_io_submit(ctx, 1, &p) != 1) {
		r->last_errno = errno;
		return -1;
	}
	s->inflight = true;
	r->cur_inflight++;
	if (r->cur_inflight > r->peak_inflight)
		r->peak_inflight = r->cur_inflight;
	return 0;
}

static void drain(aio_context_t ctx, struct slot *slots, int epfd, int evfd,
		  struct run *r)
{
	struct io_event ev[MAX_DEPTH];
	struct timespec zero = { 0, 0 };
	long n, i;

	for (;;) {
		n = sys_io_getevents(ctx, 0, r->depth, ev, &zero);
		if (n <= 0)
			return;

		for (i = 0; i < n; i++) {
			unsigned idx = (unsigned)ev[i].data;
			long res = (long)ev[i].res;
			double t = now_s();

			if (idx >= r->depth)
				continue;
			slots[idx].inflight = false;
			if (r->cur_inflight)
				r->cur_inflight--;
			r->completions++;

			if (res > 0) {
				r->bytes += (unsigned long long)res;
				if (r->t_first_byte == 0)
					r->t_first_byte = t;
				r->t_last_byte = t;
				if ((unsigned long)res < r->buflen)
					r->short_reads++;
			} else if (res < 0) {
				r->errors++;
				r->last_errno = (int)-res;
			}
			if (r->n_disable && t >= r->t_disable)
				r->post_disable_completions++;

			/* keep the pipe full while the function is enabled */
			if (r->ready && !stop_flag)
				submit_slot(ctx, &slots[idx], epfd, evfd,
					    r->buflen, idx, r);
		}
	}
}

/* ---------------------------------------------------------- AIO self-test */
/*
 * Validates the raw-syscall AIO path for the architecture this binary was
 * built for: syscall numbers, struct iocb layout, IOCB_FLAG_RESFD/eventfd
 * wiring, and the drain loop.  It uses a regular file, so it needs no gadget
 * and no board.
 *
 * SCOPE, stated plainly: this proves the harness's AIO plumbing works here.
 * It does NOT prove anything about USB queue depth on the target -- that comes
 * from measured_peak_inflight in a real run.
 */
static int selftest_aio(unsigned depth, unsigned buflen)
{
	aio_context_t ctx = 0;
	struct iocb *cbv[MAX_DEPTH];
	struct iocb cbs[MAX_DEPTH];
	unsigned char *bufs[MAX_DEPTH];
	struct io_event ev[MAX_DEPTH];
	unsigned char *src = NULL;
	char tmpl[] = "/tmp/r1a_aio_selftest_XXXXXX";
	struct timespec to = { 5, 0 };
	int fd = -1, evfd = -1, rc = 1;
	unsigned i, done = 0, peak = 0, inflight = 0;
	long n;

	printf("aio selftest: depth=%u buflen=%u\n", depth, buflen);

	memset(bufs, 0, sizeof(bufs));
	src = malloc((size_t)depth * buflen);
	if (!src)
		goto out;
	for (i = 0; i < depth * buflen; i++)
		src[i] = (unsigned char)(i * 7 + 13);

	fd = mkstemp(tmpl);
	if (fd < 0) {
		perror("mkstemp");
		goto out;
	}
	unlink(tmpl);
	if (write(fd, src, (size_t)depth * buflen) != (ssize_t)(depth * buflen)) {
		perror("write");
		goto out;
	}

	evfd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
	if (evfd < 0) {
		perror("eventfd");
		goto out;
	}
	if (sys_io_setup(depth, &ctx) < 0) {
		perror("io_setup");
		goto out;
	}

	for (i = 0; i < depth; i++) {
		bufs[i] = calloc(1, buflen);
		if (!bufs[i])
			goto out;
		memset(&cbs[i], 0, sizeof(cbs[i]));
		cbs[i].aio_data = i;
		cbs[i].aio_lio_opcode = IOCB_CMD_PREAD;
		cbs[i].aio_fildes = fd;
		cbs[i].aio_buf = (uintptr_t)bufs[i];
		cbs[i].aio_nbytes = buflen;
		cbs[i].aio_offset = (long long)i * buflen;
		cbs[i].aio_flags = IOCB_FLAG_RESFD;
		cbs[i].aio_resfd = evfd;
		cbv[i] = &cbs[i];
	}

	n = sys_io_submit(ctx, depth, cbv);
	if (n < 0) {
		perror("io_submit");
		goto out;
	}
	inflight = (unsigned)n;
	peak = inflight;
	printf("  io_submit accepted %ld of %u iocbs\n", n, depth);
	if ((unsigned)n != depth) {
		printf("  FAIL: kernel accepted fewer iocbs than requested\n");
		goto out;
	}

	while (done < depth) {
		uint64_t v;
		struct pollfd p = { evfd, POLLIN, 0 };

		if (poll(&p, 1, 5000) <= 0) {
			printf("  FAIL: timed out waiting for completions "
			       "(%u/%u)\n", done, depth);
			goto out;
		}
		while (read(evfd, &v, sizeof(v)) == sizeof(v))
			;
		n = sys_io_getevents(ctx, 1, depth, ev, &to);
		if (n < 0) {
			perror("io_getevents");
			goto out;
		}
		for (i = 0; i < (unsigned)n; i++) {
			unsigned idx = (unsigned)ev[i].data;
			long res = (long)ev[i].res;

			if (idx >= depth) {
				printf("  FAIL: bogus aio_data %u\n", idx);
				goto out;
			}
			if (res != (long)buflen) {
				printf("  FAIL: slot %u returned %ld, want %u\n",
				       idx, res, buflen);
				goto out;
			}
			if (memcmp(bufs[idx], src + (size_t)idx * buflen,
				   buflen)) {
				printf("  FAIL: slot %u data mismatch\n", idx);
				goto out;
			}
			done++;
			if (inflight)
				inflight--;
		}
	}

	printf("  ok: %u/%u completions, correct data, peak accepted "
	       "inflight=%u\n", done, depth, peak);
	printf("AIO SELFTEST: PASS\n");
	rc = 0;
out:
	if (rc)
		printf("AIO SELFTEST: FAIL\n");
	for (i = 0; i < depth; i++)
		free(bufs[i]);
	free(src);
	if (ctx)
		sys_io_destroy(ctx);
	if (evfd >= 0)
		close(evfd);
	if (fd >= 0)
		close(fd);
	return rc;
}

/* --------------------------------------------------------------- artifact */

static void write_artifact(const struct run *r)
{
	double dur, act;
	FILE *f;

	if (!r->artifact)
		return;
	f = fopen(r->artifact, "w");
	if (!f) {
		fprintf(stderr, "artifact %s: %s\n", r->artifact,
			strerror(errno));
		return;
	}

	dur = r->t_end - r->t_start;
	act = (r->t_last_byte && r->t_first_byte)
		? r->t_last_byte - r->t_first_byte : 0.0;

	fprintf(f, "{\n");
	fprintf(f, "  \"harness\": \"r1a_ffs_out_v2\",\n");
	fprintf(f, "  \"note\": \"TEST-ONLY. Gadget-side observations only. "
		"Nothing here is a dwc2 driver result.\",\n");
	fprintf(f, "  \"config\": {\n");
	fprintf(f, "    \"ffs_dir\": \"%s\",\n", r->ffs_dir);
	fprintf(f, "    \"requested_depth\": %u,\n", r->depth);
	fprintf(f, "    \"buflen\": %u,\n", r->buflen);
	fprintf(f, "    \"seconds\": %u,\n", r->seconds);
	fprintf(f, "    \"io_mode\": \"aio_io_submit\"\n");
	fprintf(f, "  },\n");

	fprintf(f, "  \"preconditions\": {\n");
	fprintf(f, "    \"ready\": %d,\n", r->ever_ready ? 1 : 0);
	fprintf(f, "    \"ready_source\": \"observed FUNCTIONFS_ENABLE\",\n");
	fprintf(f, "    \"ep_verified\": %d,\n", r->ep_verified ? 1 : 0);
	fprintf(f, "    \"ep_bEndpointAddress\": \"0x%02x\",\n", r->ep_addr);
	fprintf(f, "    \"ep_dir\": \"%s\",\n",
		(r->ep_addr & USB_DIR_IN) ? "IN" : "OUT");
	fprintf(f, "    \"ep_type\": \"%s\",\n", xfer_name(r->ep_xfer));
	fprintf(f, "    \"ep_wMaxPacketSize\": %d\n", r->ep_mps);
	fprintf(f, "  },\n");

	fprintf(f, "  \"lifecycle\": {\n");
	fprintf(f, "    \"enable_events\": %u,\n", r->n_enable);
	fprintf(f, "    \"disable_events\": %u,\n", r->n_disable);
	fprintf(f, "    \"setup_events\": %u,\n", r->n_setup);
	fprintf(f, "    \"suspend_events\": %u,\n", r->n_suspend);
	fprintf(f, "    \"resume_events\": %u,\n", r->n_resume);
	fprintf(f, "    \"t_enable_rel\": %.6f,\n",
		r->t_enable ? r->t_enable - r->t_start : -1.0);
	fprintf(f, "    \"t_disable_rel\": %.6f\n",
		r->t_disable ? r->t_disable - r->t_start : -1.0);
	fprintf(f, "  },\n");

	fprintf(f, "  \"traffic\": {\n");
	fprintf(f, "    \"completions\": %llu,\n", r->completions);
	fprintf(f, "    \"bytes\": %llu,\n", r->bytes);
	fprintf(f, "    \"errors\": %llu,\n", r->errors);
	fprintf(f, "    \"short_reads\": %llu,\n", r->short_reads);
	fprintf(f, "    \"post_disable_completions\": %llu,\n",
		r->post_disable_completions);
	fprintf(f, "    \"last_errno\": %d,\n", r->last_errno);
	fprintf(f, "    \"active_seconds\": %.6f,\n", act);
	fprintf(f, "    \"bytes_per_sec\": %.1f\n",
		act > 0 ? r->bytes / act : 0.0);
	fprintf(f, "  },\n");

	/*
	 * Sensitivity is reported so that a run which sees no timeout can be
	 * qualified instead of being read as a negative result.  measured_peak
	 * is the peak number of simultaneously outstanding AIO reads; if it is
	 * 1, this run had no more queue depth than the old harness and proves
	 * nothing about depth-dependent behaviour.
	 */
	fprintf(f, "  \"sensitivity\": {\n");
	fprintf(f, "    \"measured_peak_inflight\": %u,\n", r->peak_inflight);
	fprintf(f, "    \"depth_achieved\": %d,\n",
		r->peak_inflight >= r->depth ? 1 : 0);
	fprintf(f, "    \"host_traffic_proven\": %d,\n", r->bytes > 0 ? 1 : 0);
	fprintf(f, "    \"run_seconds\": %.6f,\n", dur);
	fprintf(f, "    \"verdict\": \"%s\"\n",
		(!r->ever_ready)            ? "INVALID_NEVER_ENABLED" :
		(!r->ep_verified)           ? "INVALID_EP_UNVERIFIED" :
		(r->bytes == 0)             ? "INVALID_NO_HOST_TRAFFIC" :
		(r->peak_inflight < 2)      ? "INVALID_NO_QUEUE_DEPTH" :
		(r->peak_inflight < r->depth) ? "WEAK_DEPTH_BELOW_TARGET" :
					      "SENSITIVE");
	fprintf(f, "  }\n");
	fprintf(f, "}\n");
	fclose(f);
	printf("  artifact written: %s\n", r->artifact);
}

/* ------------------------------------------------------------------- main */

static void usage(const char *p)
{
	fprintf(stderr,
		"usage: %s --ffs DIR [--depth N] [--buflen N] [--seconds N]\n"
		"          [--artifact PATH] [--dump-desc PATH]\n"
		"       %s --selftest-aio [--depth N] [--buflen N]\n"
		"  DIR must be an already-mounted functionfs instance.\n", p, p);
}

int main(int argc, char **argv)
{
	struct run r;
	struct slot *slots = NULL;
	aio_context_t ctx = 0;
	char path[512];
	int ep0 = -1, epfd = -1, evfd = -1, rc = 1;
	struct pollfd pfd[2];
	unsigned i;
	double deadline;
	bool submitted = false;
	bool selftest = false;

	memset(&r, 0, sizeof(r));
	r.depth = DEF_DEPTH;
	r.buflen = DEF_BUFLEN;
	r.seconds = DEF_SECONDS;

	for (i = 1; i < (unsigned)argc; i++) {
		if (!strcmp(argv[i], "--ffs") && i + 1 < (unsigned)argc)
			r.ffs_dir = argv[++i];
		else if (!strcmp(argv[i], "--depth") && i + 1 < (unsigned)argc)
			r.depth = (unsigned)atoi(argv[++i]);
		else if (!strcmp(argv[i], "--buflen") && i + 1 < (unsigned)argc)
			r.buflen = (unsigned)atoi(argv[++i]);
		else if (!strcmp(argv[i], "--seconds") && i + 1 < (unsigned)argc)
			r.seconds = (unsigned)atoi(argv[++i]);
		else if (!strcmp(argv[i], "--artifact") && i + 1 < (unsigned)argc)
			r.artifact = argv[++i];
		else if (!strcmp(argv[i], "--dump-desc") && i + 1 < (unsigned)argc)
			r.dump_desc = argv[++i];
		else if (!strcmp(argv[i], "--selftest-aio"))
			selftest = true;
		else {
			usage(argv[0]);
			return 2;
		}
	}
	if (r.depth < 1 || r.depth > MAX_DEPTH || r.buflen < 1) {
		usage(argv[0]);
		return 2;
	}

	if (selftest)
		return selftest_aio(r.depth, r.buflen);

	/*
	 * --dump-desc writes the exact bytes this binary would hand to ep0, so
	 * the descriptor blob can be decoded and checked off-target, by the
	 * same binary that will later run on the board.  No device needed.
	 */
	if (r.dump_desc) {
		FILE *df = fopen(r.dump_desc, "wb");

		if (!df) {
			perror("dump-desc");
			return 2;
		}
		if (fwrite(&descriptors, 1, sizeof(descriptors), df) !=
		    sizeof(descriptors) ||
		    fwrite(&strings, 1, sizeof(strings), df) !=
		    sizeof(strings)) {
			perror("dump-desc write");
			fclose(df);
			return 2;
		}
		fclose(df);
		printf("descriptor blob: %zu bytes descriptors + %zu bytes "
		       "strings -> %s\n",
		       sizeof(descriptors), sizeof(strings), r.dump_desc);
		if (!r.ffs_dir)
			return 0;
	}

	if (!r.ffs_dir) {
		usage(argv[0]);
		return 2;
	}

	signal(SIGINT, on_sigint);
	signal(SIGTERM, on_sigint);
	r.t_start = now_s();

	printf("r1a_ffs_out_v2  ffs=%s depth=%u buflen=%u seconds=%u\n",
	       r.ffs_dir, r.depth, r.buflen, r.seconds);

	snprintf(path, sizeof(path), "%s/ep0", r.ffs_dir);
	ep0 = open(path, O_RDWR);
	if (ep0 < 0) {
		fprintf(stderr, "open %s: %s\n", path, strerror(errno));
		fprintf(stderr, "  is functionfs mounted there?\n");
		goto out;
	}
	if (write(ep0, &descriptors, sizeof(descriptors)) < 0) {
		fprintf(stderr, "write descriptors: %s\n", strerror(errno));
		goto out;
	}
	if (write(ep0, &strings, sizeof(strings)) < 0) {
		fprintf(stderr, "write strings: %s\n", strerror(errno));
		goto out;
	}
	printf("  descriptors written (%zu bytes), strings written (%zu bytes)\n",
	       sizeof(descriptors), sizeof(strings));

	snprintf(path, sizeof(path), "%s/ep2", r.ffs_dir);
	epfd = open(path, O_RDWR);
	if (epfd < 0) {
		fprintf(stderr, "open %s: %s\n", path, strerror(errno));
		goto out;
	}

	evfd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
	if (evfd < 0) {
		perror("eventfd");
		goto out;
	}
	if (sys_io_setup(r.depth, &ctx) < 0) {
		perror("io_setup");
		goto out;
	}

	slots = calloc(r.depth, sizeof(*slots));
	if (!slots) {
		perror("calloc");
		goto out;
	}
	for (i = 0; i < r.depth; i++) {
		slots[i].buf = malloc(r.buflen);
		if (!slots[i].buf) {
			perror("malloc");
			goto out;
		}
	}

	printf("  waiting for FUNCTIONFS_ENABLE (bind the gadget on the host)\n");
	deadline = r.t_start + r.seconds;

	while (!stop_flag && now_s() < deadline) {
		uint64_t v;
		int n;

		pfd[0].fd = ep0;
		pfd[0].events = POLLIN;
		pfd[0].revents = 0;
		pfd[1].fd = evfd;
		pfd[1].events = POLLIN;
		pfd[1].revents = 0;

		n = poll(pfd, 2, 200);
		if (n < 0) {
			if (errno == EINTR)
				continue;
			perror("poll");
			break;
		}

		if (pfd[0].revents & POLLIN)
			handle_ep0(ep0, &r);

		if (pfd[1].revents & POLLIN) {
			while (read(evfd, &v, sizeof(v)) == sizeof(v))
				;
			drain(ctx, slots, epfd, evfd, &r);
		}

		/*
		 * Fill the queue on the first ENABLE, and refill after a
		 * DISABLE/ENABLE cycle.  Verification of the endpoint happens
		 * once, and only while enabled -- the ioctl is meaningless
		 * before the gadget core has bound the endpoint.
		 */
		if (r.ready && !submitted) {
			if (!r.ep_verified && verify_out_ep(epfd, &r) < 0)
				goto out;
			for (i = 0; i < r.depth; i++)
				if (!slots[i].inflight)
					submit_slot(ctx, &slots[i], epfd, evfd,
						    r.buflen, i, &r);
			submitted = true;
			printf("  submitted %u AIO reads, peak inflight=%u\n",
			       r.depth, r.peak_inflight);
		}
		if (!r.ready && submitted && r.cur_inflight == 0)
			submitted = false;

		/* opportunistic drain in case the eventfd was coalesced */
		drain(ctx, slots, epfd, evfd, &r);
	}

	drain(ctx, slots, epfd, evfd, &r);
	r.t_end = now_s();

	printf("\n  ready=%d ep_verified=%d peak_inflight=%u completions=%llu "
	       "bytes=%llu errors=%llu\n",
	       r.ever_ready, r.ep_verified, r.peak_inflight, r.completions,
	       r.bytes, r.errors);
	if (r.n_disable)
		printf("  post-DISABLE completions: %llu\n",
		       r.post_disable_completions);
	write_artifact(&r);
	rc = r.ever_ready && r.ep_verified && r.bytes > 0 ? 0 : 1;

out:
	if (!r.t_end) {
		r.t_end = now_s();
		write_artifact(&r);
	}
	if (slots) {
		for (i = 0; i < r.depth; i++)
			free(slots[i].buf);
		free(slots);
	}
	if (ctx)
		sys_io_destroy(ctx);
	if (evfd >= 0)
		close(evfd);
	if (epfd >= 0)
		close(epfd);
	if (ep0 >= 0)
		close(ep0);
	return rc;
}
