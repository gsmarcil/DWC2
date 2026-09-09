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
 *
 * THE HOLDER WITNESS (--event-log)
 * --------------------------------
 * pipeline/holder_merge.py consumes a JSONL log and pairs one
 * {"event":"R1A_HOLDER","phase":"campaign",...} record with each host attempt,
 * by order.  The load-bearing field is pending_reads, which the pipeline reads
 * as "the gadget's own queue depth at teardown" and tests as >= floor.  A >=
 * test is only sound on a LOWER bound, so what this harness counts has to be
 * requests the function driver provably still owned when the endpoint was
 * disabled -- not requests this process had merely not reaped yet.
 *
 * Three facts from the pinned tree decide the design:
 *
 *   drivers/usb/gadget/function/f_fs.c:3805  ffs_func_eps_disable(ffs->func);
 *   drivers/usb/gadget/function/f_fs.c:3818  ffs_event_add(ffs, FUNCTIONFS_DISABLE);
 *
 *     The endpoints are torn down BEFORE the event is queued.  By the time
 *     userspace dequeues FUNCTIONFS_DISABLE the kill has already run, so
 *     "cur_inflight sampled at the DISABLE event" is a race artifact: it
 *     depends on how much of the completion workqueue has already drained.
 *     It is an upper bound, and an upper bound cannot support >= floor.
 *
 *   drivers/usb/dwc2/gadget.c:5259           kill_all_requests(hsotg, hs_ep, -ESHUTDOWN);
 *   drivers/usb/gadget/function/f_fs.c:894   io_data->status = req->status ? req->status : req->actual;
 *
 *     dwc2_hsotg_ep_disable() completes everything still on ep->queue with
 *     -ESHUTDOWN, and f_fs propagates req->status verbatim to the AIO result.
 *     So an AIO read that returns -ESHUTDOWN WAS on the endpoint queue when
 *     the kill ran.  That is the lower bound the pipeline needs.
 *
 *   drivers/usb/gadget/function/f_fs.c:3229  case FUNCTIONFS_DISABLE:
 *   drivers/usb/gadget/function/f_fs.c:3234          neg = 1;
 *
 *     __ffs_event_add() purges every queued event except SUSPEND/RESUME when
 *     it adds BIND/UNBIND/ENABLE/DISABLE.  A DISABLE immediately followed by an
 *     ENABLE -- which is exactly what SET_CONFIGURATION(nonzero) produces, via
 *     composite.c:966 reset_config() then ffs_func_set_alt() -- can therefore
 *     erase the DISABLE before this process ever reads it.  A witness keyed
 *     only on the DISABLE event would silently under-count in the cfgn branch.
 *     USB_REQ_SET_INTERFACE is worse: composite.c:1915 reaches
 *     ffs_func_set_alt() only, which nukes pending requests at f_fs.c:3775 and
 *     emits ENABLE alone -- there is no DISABLE to key on at all.
 *
 * So a teardown episode here opens on EITHER the FUNCTIONFS_DISABLE event OR
 * the first -ESHUTDOWN completion, whichever arrives first, and the record
 * names which one opened it.  pending_reads is then exactly one term:
 *
 *     reads that completed -ESHUTDOWN during the episode, were not immediate
 *     submission failures, and were submitted at or before the episode cutoff
 *     (the submission count as it stood when the episode opened)
 *
 * and nothing else.  A read that completed with data is excluded, because it
 * may have completed before the teardown and merely sat unreaped.  A read that
 * has NOT completed is excluded too, which is the less obvious one: the driver
 * still owns it, so it is tempting to count it, but "has not completed" is the
 * absence of a fact rather than a fact -- the request may be held, may be lost,
 * may never have been queued.  Those are reported as unresolved_reads, for
 * diagnosis, and they do not raise the count.  A read killed after the cutoff
 * is reported as kills_after_cutoff and does not raise it either.
 *
 * One more subtraction is needed for that to be true.  f_fs.c:1087 returns
 * -ESHUTDOWN from ffs_epfile_io() when epfile->ep is already NULL, so a read
 * submitted after the teardown and before this process noticed comes back with
 * the same status as a kill without ever having been queued.  The two separate
 * in time rather than in status: the early return happens inside io_submit(),
 * so its completion is already in the ring when io_submit() returns and is
 * handed back by the very next io_getevents() call, while a real kill is
 * completed later by the ffs workqueue (f_fs.c:896).  Each slot therefore
 * records the io_getevents() count at submission, and an -ESHUTDOWN returned
 * by the immediately following call is recorded as sync_submit_failures and
 * kept out of pending_reads.  A real kill that the workqueue delivers that
 * fast is discarded with them, which makes the count too small; that direction
 * costs a usable negative, the other direction would manufacture one.
 *
 * WHAT THIS DOES NOT DO.  It does not decide which teardown is the campaign.
 * phase comes from --phase-file, is checked against a fixed vocabulary, and is
 * "unknown" when no file is given.  This harness never writes "campaign" on its
 * own initiative, because holder_merge.py refuses to guess an unmarked
 * teardown and that refusal is the point.
 *
 * THE FIXTURE IS NOT IN THE CAMPAIGN NAMESPACE.  --selftest-holder drives the
 * same slot table and the same writer, so the record shape it produces is the
 * real one, but its records are written as event "R1A_HOLDER_SELFTEST" with
 * phase "selftest".  holder_merge.py selects on event and phase and ignores
 * every other field, so a "synthetic":true flag alone would not stop a fixture
 * from merging to HOLDER_CONFIRMED -- it has to be outside the namespace the
 * merger reads, and it is.  The flag remains as a second marker on the header
 * line and on every record.
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

/*
 * How long an open teardown episode waits for further -ESHUTDOWN completions
 * before it is closed and written out.  ffs_epfile_async_io_complete() hands
 * the completion to a workqueue (f_fs.c:896), so the kills do not all land in
 * the AIO ring in the same instant; closing too early would truncate the
 * count.  The value is recorded in every record, because it is part of what
 * the number means.
 */
#define DEF_SETTLE_MS	500
#define BOOT_ID_PATH	"/proc/sys/kernel/random/boot_id"
#define PHASE_MAX	32

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
	/* io_getevents() call count at the moment this slot was submitted */
	unsigned long long submit_ge;
	/* monotonic submission number, compared against the episode cutoff */
	unsigned long long submit_seq;
};

struct run {
	/* configuration */
	const char *ffs_dir;
	unsigned depth;
	unsigned buflen;
	unsigned seconds;
	const char *artifact;
	const char *dump_desc;

	/* holder witness configuration */
	const char *event_log;
	const char *session_id;
	const char *phase_file;
	bool log_append;
	bool synthetic;
	unsigned settle_ms;

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

	/*
	 * Holder witness accounting.  submitted_total and reaped_total are
	 * monotonic for the life of the process; their difference is the
	 * number of reads this process has handed the kernel and not yet
	 * collected.  reaped_shutdown is the only one of the three that
	 * carries a claim about the driver, because -ESHUTDOWN on a Bulk OUT
	 * read can only be produced by kill_all_requests() and therefore
	 * proves the request was on ep->queue when the kill ran.
	 */
	FILE *evlog;
	unsigned long long ge_calls;
	char boot_id[64];
	char phase[PHASE_MAX];
	const char *phase_source;
	unsigned phase_change_seq;
	unsigned device_seq;
	unsigned long long submitted_total, reaped_total;
	unsigned long long reaped_shutdown, reaped_ok, reaped_other_err;
	unsigned long long reaped_sync_fail;

	/* open teardown episode */
	bool td_open;
	const char *td_trigger;
	unsigned long long td_cutoff;
	unsigned long long td_kills, td_kills_after_cutoff;
	unsigned long long td_sync_fail_at_open;
	unsigned td_inflight_at_open;
	double td_open_t, td_last_esd_t;
};

static volatile sig_atomic_t stop_flag;

static void on_sigint(int s) { (void)s; stop_flag = 1; }

static double now_s(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

/* ------------------------------------------------------- holder witness */
/*
 * The vocabulary is closed on purpose.  holder_merge.py selects records with
 * phase == "campaign" and silently drops everything else, so a phase file
 * holding "Campaign" or "campaign\n" would not fail -- it would produce a log
 * with fewer campaign records than the host fired attempts, which the merger
 * then reports as a depth problem.  Rejecting the token here turns a silent
 * miscount into a visible refusal.
 */
static const char *const PHASES[] = {
	"preflight", "sensitivity", "campaign", "rearm", "unknown",
};

static bool safe_token(const char *s, size_t max)
{
	size_t i;

	if (!s || !*s)
		return false;
	for (i = 0; s[i]; i++) {
		unsigned char c = (unsigned char)s[i];

		if (i >= max)
			return false;
		if (c < 0x20 || c > 0x7e || c == '"' || c == '\\')
			return false;
	}
	return true;
}

/*
 * Read a short file and strip trailing whitespace.  Used for the board's own
 * boot identity and for the phase marker, both of which are single tokens.
 */
static int read_trimmed(const char *path, char *buf, size_t len)
{
	size_t n;
	FILE *f = fopen(path, "r");

	if (!f)
		return -1;
	n = fread(buf, 1, len - 1, f);
	fclose(f);
	buf[n] = '\0';
	while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r' ||
		     buf[n - 1] == ' ' || buf[n - 1] == '\t'))
		buf[--n] = '\0';
	return n ? 0 : -1;
}

static void utc_now(char *buf, size_t len)
{
	struct timespec ts;
	struct tm tm;

	clock_gettime(CLOCK_REALTIME, &ts);
	if (!gmtime_r(&ts.tv_sec, &tm)) {
		snprintf(buf, len, "1970-01-01T00:00:00Z");
		return;
	}
	strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

static void holder_flush(struct run *r)
{
	if (!r->evlog)
		return;
	fflush(r->evlog);
	if (fsync(fileno(r->evlog)) < 0 && errno != EINVAL)
		fprintf(stderr, "event log fsync: %s\n", strerror(errno));
}

/*
 * The phase is re-read at the moment a teardown episode opens, never cached
 * from startup, so the operator can move the run from preflight to campaign
 * without restarting the gadget side.  An unreadable or unknown token is
 * recorded as "unknown" and the reason is kept in phase_source: the record is
 * still written, because a teardown that happened must not vanish from the log
 * just because its label was wrong.
 */
static void holder_read_phase(struct run *r)
{
	char buf[PHASE_MAX];
	const char *prev = r->phase;
	size_t i;

	if (!r->phase_file) {
		r->phase_source = "no_phase_file";
		snprintf(buf, sizeof(buf), "unknown");
	} else if (read_trimmed(r->phase_file, buf, sizeof(buf)) < 0) {
		r->phase_source = "phase_file_unreadable";
		snprintf(buf, sizeof(buf), "unknown");
	} else {
		r->phase_source = "phase_file";
		for (i = 0; i < sizeof(PHASES) / sizeof(PHASES[0]); i++)
			if (!strcmp(buf, PHASES[i]))
				break;
		if (i == sizeof(PHASES) / sizeof(PHASES[0])) {
			fprintf(stderr, "phase file %s holds a token that is "
				"not in the vocabulary; recording \"unknown\"\n",
				r->phase_file);
			r->phase_source = "phase_file_token_rejected";
			snprintf(buf, sizeof(buf), "unknown");
		}
	}

	if (strcmp(prev, buf))
		r->phase_change_seq++;
	snprintf(r->phase, sizeof(r->phase), "%s", buf);
}

static int holder_open(struct run *r)
{
	struct stat st;
	char utc[32];
	int fd;

	if (!r->event_log)
		return 0;

	if (!safe_token(r->event_log, 255)) {
		fprintf(stderr, "--event-log path must be a printable token "
			"without quote or backslash\n");
		return -1;
	}
	if (!r->session_id) {
		fprintf(stderr, "--event-log requires --session-id, and it must "
			"be the same session_id the host writes into the "
			"manifest: holder_merge.py compares them and refuses "
			"the merge when they differ\n");
		return -1;
	}
	if (!safe_token(r->session_id, 63)) {
		fprintf(stderr, "--session-id must be a printable token without "
			"quote or backslash; this one would be escaped into "
			"the JSONL and stop matching the manifest\n");
		return -1;
	}
	/*
	 * The boot identity is read from the kernel here rather than accepted
	 * from the command line.  The host harness takes session.boot_id as an
	 * operator argument, so the merger's equality test is only worth
	 * something if one of the two sides is not operator-typed.
	 */
	if (read_trimmed(BOOT_ID_PATH, r->boot_id, sizeof(r->boot_id)) < 0 ||
	    !safe_token(r->boot_id, sizeof(r->boot_id) - 1)) {
		fprintf(stderr, "cannot read %s\n", BOOT_ID_PATH);
		return -1;
	}
	if (stat(r->event_log, &st) == 0 && st.st_size > 0 && !r->log_append) {
		fprintf(stderr, "%s already holds %lld bytes.  holder_merge.py "
			"aborts the whole merge if the log carries a campaign "
			"record from another session or boot, so a stale log is "
			"refused now rather than after the campaign.  Use a "
			"fresh path, or --event-log-append if this really is a "
			"continuation of the same session.\n",
			r->event_log, (long long)st.st_size);
		return -1;
	}

	fd = open(r->event_log, O_WRONLY | O_CREAT | O_APPEND, 0644);
	if (fd < 0) {
		fprintf(stderr, "open %s: %s\n", r->event_log,
			strerror(errno));
		return -1;
	}
	r->evlog = fdopen(fd, "a");
	if (!r->evlog) {
		fprintf(stderr, "fdopen %s: %s\n", r->event_log,
			strerror(errno));
		close(fd);
		return -1;
	}

	snprintf(r->phase, sizeof(r->phase), "unknown");
	r->phase_source = "not_read_yet";
	utc_now(utc, sizeof(utc));
	/*
	 * holder_merge.py keeps only event == "R1A_HOLDER", so this header is
	 * inert to the merger and visible to a reader.  It is the only place
	 * the synthetic marker can be seen without reading every record.
	 */
	fprintf(r->evlog,
		"{\"event\":\"R1A_HOLDER_SESSION\",\"phase\":\"session\","
		"\"session_id\":\"%s\",\"boot_id\":\"%s\",\"utc\":\"%s\","
		"\"harness\":\"r1a_ffs_out_v2\","
		"\"mode\":\"%s\",\"synthetic\":%s,"
		"\"depth_configured\":%u,\"buflen\":%u,\"settle_ms\":%u}\n",
		r->session_id, r->boot_id, utc,
		r->synthetic ? "selftest_holder" : "run",
		r->synthetic ? "true" : "false",
		r->depth, r->buflen, r->settle_ms);
	holder_flush(r);
	printf("  holder event log: %s (session_id=%s boot_id=%s)\n",
	       r->event_log, r->session_id, r->boot_id);
	return 0;
}

static void teardown_open(struct run *r, const char *trigger)
{
	if (!r->evlog || r->td_open)
		return;
	r->td_open = true;
	r->td_trigger = trigger;
	r->td_sync_fail_at_open = r->reaped_sync_fail;
	/*
	 * The cutoff is the submission count as it stood when the episode
	 * opened.  A read submitted after it cannot have been on the queue the
	 * teardown emptied, whatever status it later returns.
	 */
	r->td_cutoff = r->submitted_total;
	r->td_kills = 0;
	r->td_kills_after_cutoff = 0;
	r->td_inflight_at_open =
		(unsigned)(r->submitted_total - r->reaped_total);
	r->td_open_t = now_s();
	r->td_last_esd_t = r->td_open_t;
	holder_read_phase(r);
}

/*
 * pending_reads counts ONE thing: reads that came back -ESHUTDOWN inside this
 * episode, were not immediate submission failures, and were submitted at or
 * before the episode cutoff.  Only kill_all_requests() produces that status
 * for a Bulk OUT read (dwc2/gadget.c:5259, propagated verbatim at
 * f_fs.c:894), so each one was on the endpoint queue when the endpoint was
 * disabled.  Nothing else is added.
 *
 * In particular a read that has NOT completed is not counted.  It was tempting
 * -- the driver still holds it, so it held it then -- but "has not completed"
 * is not a fact about the queue, it is the absence of one: the request may be
 * held, may be lost, may never have been queued.  Such reads are reported as
 * unresolved_reads so a run that stalls is diagnosable, and they leave
 * pending_reads alone.
 *
 * A read that completed with data is excluded too: it may have completed
 * before the teardown and merely sat unreaped.
 *
 * Every exclusion pushes the number down.  A count that is too small costs a
 * usable negative; a count that is too large would manufacture one.
 */
static void teardown_close(struct run *r, const struct slot *slots)
{
	unsigned long long pending, unresolved = 0;
	char utc[32];
	unsigned i;

	if (!r->evlog || !r->td_open)
		return;

	if (slots)
		for (i = 0; i < r->depth; i++)
			if (slots[i].inflight &&
			    slots[i].submit_seq <= r->td_cutoff)
				unresolved++;

	pending = r->td_kills;
	r->device_seq++;
	utc_now(utc, sizeof(utc));

	/*
	 * A fixture is written OUTSIDE the campaign namespace, not merely
	 * labelled.  holder_merge.py selects on event and phase and ignores
	 * every other field, so "synthetic":true alone would not stop a
	 * fixture from merging to HOLDER_CONFIRMED.  These records are dropped
	 * by the merger's own filter, and the flag stays as a second marker.
	 */
	fprintf(r->evlog,
		"{\"event\":\"%s\",\"phase\":\"%s\","
		"\"session_id\":\"%s\",\"boot_id\":\"%s\","
		"\"device_seq\":%u,\"pending_reads\":%llu,\"utc\":\"%s\","
		"\"synthetic\":%s,"
		"\"pending_definition\":\"eshutdown_kills_at_or_before_"
		"cutoff_excluding_sync_submit_failures\","
		"\"unresolved_reads\":%llu,"
		"\"kills_after_cutoff\":%llu,"
		"\"sync_submit_failures\":%llu,"
		"\"episode_cutoff\":%llu,"
		"\"inflight_at_open\":%u,\"depth_configured\":%u,"
		"\"episode_trigger\":\"%s\",\"phase_marker\":\"%s\","
		"\"phase_source\":\"%s\","
		"\"phase_change_seq\":%u,\"settle_ms\":%u,"
		"\"open_to_close_s\":%.6f,"
		"\"submitted_total\":%llu,\"reaped_total\":%llu,"
		"\"reaped_shutdown_total\":%llu,"
		"\"reaped_ok\":%llu,\"reaped_other_err\":%llu}\n",
		r->synthetic ? "R1A_HOLDER_SELFTEST" : "R1A_HOLDER",
		r->synthetic ? "selftest" : r->phase,
		r->session_id, r->boot_id,
		r->device_seq, pending, utc,
		r->synthetic ? "true" : "false",
		unresolved,
		r->td_kills_after_cutoff,
		r->reaped_sync_fail - r->td_sync_fail_at_open,
		r->td_cutoff,
		r->td_inflight_at_open, r->depth,
		r->td_trigger, r->phase, r->phase_source,
		r->phase_change_seq, r->settle_ms,
		now_s() - r->td_open_t,
		r->submitted_total, r->reaped_total, r->reaped_shutdown,
		r->reaped_ok, r->reaped_other_err);
	holder_flush(r);

	printf("  [holder] seq=%u phase=%s pending_reads=%llu "
	       "(unresolved=%llu after_cutoff=%llu) trigger=%s\n",
	       r->device_seq, r->synthetic ? "selftest" : r->phase, pending,
	       unresolved, r->td_kills_after_cutoff, r->td_trigger);

	r->td_open = false;
	r->td_trigger = NULL;
}

static void holder_close(struct run *r)
{
	if (!r->evlog)
		return;
	holder_flush(r);
	fclose(r->evlog);
	r->evlog = NULL;
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
		teardown_open(r, "functionfs_disable");
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
	s->submit_ge = r->ge_calls;
	r->submitted_total++;
	s->submit_seq = r->submitted_total;
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
		unsigned long long ge;

		r->ge_calls++;
		ge = r->ge_calls;
		n = sys_io_getevents(ctx, 0, r->depth, ev, &zero);
		if (n <= 0)
			return;

		for (i = 0; i < n; i++) {
			unsigned idx = (unsigned)ev[i].data;
			long res = (long)ev[i].res;
			double t = now_s();
			bool first_ge;

			if (idx >= r->depth)
				continue;
			/*
			 * True when this is the first io_getevents() call after
			 * the slot was submitted, which is where a synchronous
			 * ffs_epfile_io() failure always lands.
			 */
			first_ge = slots[idx].submit_ge + 1 == ge;
			slots[idx].inflight = false;
			if (r->cur_inflight)
				r->cur_inflight--;
			r->completions++;
			r->reaped_total++;

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
			/*
			 * -ESHUTDOWN is the teardown signature.  For a Bulk
			 * OUT read it can only come from kill_all_requests()
			 * (dwc2/gadget.c:5259 on ep_disable, :4294/:4297 on
			 * disconnect), and f_fs.c:894 hands req->status
			 * through unchanged, so this read was on ep->queue
			 * when the kill ran.  It also opens an episode by
			 * itself: f_fs.c:3229 lets a following ENABLE purge a
			 * DISABLE that has not been read yet, and
			 * ffs_func_set_alt() nukes requests without ever
			 * queueing a DISABLE, so the event cannot be relied on
			 * as the only opener.
			 */
			if (res == -ESHUTDOWN && first_ge) {
				/*
				 * Returned by io_submit() itself: the endpoint
				 * file had no endpoint, so nothing was ever
				 * queued.  It is not evidence of a held
				 * request and is kept out of pending_reads.
				 */
				r->reaped_sync_fail++;
			} else if (res == -ESHUTDOWN) {
				r->reaped_shutdown++;
				teardown_open(r,
					"shutdown_completion_"
					"without_disable_event");
				/*
				 * A read submitted after the cutoff was not on
				 * the queue the teardown emptied.  It is
				 * recorded separately and never counted.
				 */
				if (slots[idx].submit_seq <= r->td_cutoff)
					r->td_kills++;
				else
					r->td_kills_after_cutoff++;
				r->td_last_esd_t = t;
			} else if (res < 0) {
				r->reaped_other_err++;
			} else {
				r->reaped_ok++;
			}

			if (r->n_disable && t >= r->t_disable)
				r->post_disable_completions++;

			/*
			 * Keep the pipe full while the function is enabled,
			 * but never inside an open teardown episode: the
			 * endpoint is down, and a refill would add reads to a
			 * count whose whole meaning is the queue as it stood
			 * at the kill.
			 */
			if (r->ready && !stop_flag && !r->td_open)
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

/* ------------------------------------------------- holder format self-test */
/*
 * SCOPE, stated plainly: this writes a real event log through the real
 * emitter, so it demonstrates that the record shape round-trips through
 * pipeline/holder_merge.py.  It demonstrates NOTHING about queue depth on a
 * board -- the counters are driven from this function, not from an endpoint.
 * Every record it writes, and the log header, carry "synthetic":true so a
 * fixture can never be mistaken for a campaign artifact.
 */
static int selftest_holder(struct run *r, unsigned n)
{
	struct slot *slots;
	unsigned i, j, kills;

	if (!r->event_log || !r->session_id) {
		fprintf(stderr, "--selftest-holder needs --event-log and "
			"--session-id\n");
		return 2;
	}
	if (r->depth < 2) {
		fprintf(stderr, "--selftest-holder needs --depth >= 2\n");
		return 2;
	}
	r->synthetic = true;
	if (holder_open(r) < 0)
		return 2;

	slots = calloc(r->depth, sizeof(*slots));
	if (!slots) {
		perror("calloc");
		holder_close(r);
		return 2;
	}

	/*
	 * The fixture drives the same slot table and the same close path the
	 * real run uses, so the counting rules are exercised rather than
	 * described.  Each round deliberately produces all three cases:
	 *
	 *   depth-1 reads killed at or before the cutoff   -> counted
	 *   1 read left unresolved, submitted before it    -> NOT counted
	 *   1 re-armed read killed after the cutoff        -> NOT counted
	 *
	 * The mid-episode re-arm is what a DISABLE/ENABLE pair produces
	 * (composite.c:966), and it is the ordering a close that counted fresh
	 * submissions would get wrong.
	 */
	kills = r->depth - 1;
	for (i = 0; i < r->depth; i++) {
		slots[i].inflight = true;
		r->submitted_total++;
		slots[i].submit_seq = r->submitted_total;
	}

	for (i = 0; i < n; i++) {
		teardown_open(r, "functionfs_disable");

		for (j = 0; j < kills; j++) {
			slots[j].inflight = false;
			r->reaped_total++;
			r->reaped_shutdown++;
			if (slots[j].submit_seq <= r->td_cutoff)
				r->td_kills++;
			else
				r->td_kills_after_cutoff++;
		}

		for (j = 0; j < kills; j++) {
			slots[j].inflight = true;
			r->submitted_total++;
			slots[j].submit_seq = r->submitted_total;
		}

		/* one of the re-armed reads is killed after the cutoff */
		slots[0].inflight = false;
		r->reaped_total++;
		r->reaped_shutdown++;
		if (slots[0].submit_seq <= r->td_cutoff)
			r->td_kills++;
		else
			r->td_kills_after_cutoff++;
		slots[0].inflight = true;
		r->submitted_total++;
		slots[0].submit_seq = r->submitted_total;

		teardown_close(r, slots);
	}

	free(slots);
	holder_close(r);
	printf("HOLDER FORMAT SELFTEST: wrote %u synthetic episode(s) to %s\n",
	       n, r->event_log);
	printf("  event=R1A_HOLDER_SELFTEST phase=selftest -- outside the\n"
	       "  campaign namespace, so holder_merge.py drops these records.\n"
	       "  a format fixture, not a measurement\n");
	return 0;
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
	fprintf(f, "  },\n");

	/*
	 * The same totals the event log records, in the one-shot summary, so a
	 * log and an artifact from the same run can be checked against each
	 * other without trusting either alone.
	 */
	fprintf(f, "  \"holder\": {\n");
	if (r->event_log)
		fprintf(f, "    \"event_log\": \"%s\",\n", r->event_log);
	else
		fprintf(f, "    \"event_log\": null,\n");
	if (r->session_id)
		fprintf(f, "    \"session_id\": \"%s\",\n", r->session_id);
	else
		fprintf(f, "    \"session_id\": null,\n");
	fprintf(f, "    \"boot_id\": \"%s\",\n", r->boot_id);
	fprintf(f, "    \"synthetic\": %s,\n",
		r->synthetic ? "true" : "false");
	fprintf(f, "    \"records_written\": %u,\n", r->device_seq);
	fprintf(f, "    \"submitted_total\": %llu,\n", r->submitted_total);
	fprintf(f, "    \"reaped_total\": %llu,\n", r->reaped_total);
	fprintf(f, "    \"reaped_shutdown\": %llu,\n", r->reaped_shutdown);
	fprintf(f, "    \"reaped_ok\": %llu,\n", r->reaped_ok);
	fprintf(f, "    \"reaped_other_err\": %llu,\n",
		r->reaped_other_err);
	fprintf(f, "    \"reaped_sync_fail\": %llu,\n",
		r->reaped_sync_fail);
	fprintf(f, "    \"settle_ms\": %u\n", r->settle_ms);
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
		"          [--event-log PATH --session-id ID"
		" [--phase-file PATH]\n"
		"           [--settle-ms N] [--event-log-append]]\n"
		"       %s --selftest-aio [--depth N] [--buflen N]\n"
		"       %s --selftest-holder N --event-log PATH"
		" --session-id ID\n"
		"  DIR must be an already-mounted functionfs instance.\n"
		"  --event-log writes the holder witness JSONL that\n"
		"  pipeline/holder_merge.py consumes.  --session-id must equal\n"
		"  the session_id in the host manifest; boot_id is read from\n"
		"  " BOOT_ID_PATH " and is never taken from the command line.\n"
		"  --phase-file holds exactly one of: preflight sensitivity\n"
		"  campaign rearm unknown.  Without it every record is\n"
		"  \"unknown\" and the merger finds no campaign events, which\n"
		"  is the intended default: this harness does not decide which\n"
		"  teardown was the campaign.\n", p, p, p);
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
	unsigned holder_selftest = 0;
	bool submitted = false;
	bool selftest = false;

	memset(&r, 0, sizeof(r));
	r.depth = DEF_DEPTH;
	r.buflen = DEF_BUFLEN;
	r.seconds = DEF_SECONDS;
	r.settle_ms = DEF_SETTLE_MS;
	r.phase_source = "not_read_yet";

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
		else if (!strcmp(argv[i], "--event-log") && i + 1 < (unsigned)argc)
			r.event_log = argv[++i];
		else if (!strcmp(argv[i], "--session-id") && i + 1 < (unsigned)argc)
			r.session_id = argv[++i];
		else if (!strcmp(argv[i], "--phase-file") && i + 1 < (unsigned)argc)
			r.phase_file = argv[++i];
		else if (!strcmp(argv[i], "--settle-ms") && i + 1 < (unsigned)argc)
			r.settle_ms = (unsigned)atoi(argv[++i]);
		else if (!strcmp(argv[i], "--event-log-append"))
			r.log_append = true;
		else if (!strcmp(argv[i], "--selftest-holder") && i + 1 < (unsigned)argc)
			holder_selftest = (unsigned)atoi(argv[++i]);
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

	if (holder_selftest)
		return selftest_holder(&r, holder_selftest);

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

	/*
	 * Open the log before touching the gadget.  A stale log, a missing
	 * session id or an unreadable boot id must stop the run while nothing
	 * has happened yet, not after a campaign that cannot be merged.
	 */
	if (holder_open(&r) < 0) {
		rc = 2;
		goto out;
	}

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
		if (r.ready && !submitted && !r.td_open) {
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

		/*
		 * Close an episode once no further -ESHUTDOWN has arrived for
		 * settle_ms.  The poll above bounds this loop at 200 ms, so
		 * the check still runs in a completely silent run.
		 */
		if (r.td_open &&
		    now_s() - r.td_last_esd_t >= r.settle_ms / 1000.0)
			teardown_close(&r, slots);
	}

	drain(ctx, slots, epfd, evfd, &r);
	if (r.td_open)
		teardown_close(&r, slots);
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
		if (r.td_open)
			teardown_close(&r, slots);
		write_artifact(&r);
	}
	holder_close(&r);
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
