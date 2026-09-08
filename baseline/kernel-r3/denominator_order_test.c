/*
 * Reachability proof for the v6.3/v6.3.1 denominator ordering defect.
 *
 * gadget.c:5213-5216 (v6.3.1) ran
 *      note_disable_candidate();   <- reads r1->stop_causal
 *      stop_enter();               <- the only thing that SETS stop_causal
 *      stop_xfr();
 *      stop_exit();                <- sets stop_causal = NONE
 *
 * The only writers of stop_causal before that read are stop_exit() (NONE) and
 * the zeroed allocation in dwc2_r1_init() (NONE). So the value read is not
 * merely stale -- it is NONE on every single call, and both guarded branches
 * in note_disable_candidate() are unreachable:
 *
 *      if (stop_causal == OVERLAP) return;                  <- never taken
 *      if (stop_causal == DELAYED) { delayed_disable++; }   <- never taken
 *
 * This drives both orders over a scripted episode list and prints the counters.
 * The record path (goutnak_timeout, gadget.c:796) reads stop_causal from inside
 * stop_xfr and was always correct; only the denominator was affected.
 *
 *   cc -O2 -Wall -Wextra -Werror -o denominator_order_test denominator_order_test.c
 */
#include <stdio.h>
#include <string.h>

enum { NONE = 0, SYNC_OWNER, DELAYED, OVERLAP };
enum { PH_NONE = 0, PH_SYNC = 1, PH_DELAYED = 2 };

struct r1 {
	int stop_causal;
	int setup_phase;
	int owner_is_current;
	unsigned cfg0, delayed_disable, overlap_count;
};

/* episode: what the setup window looks like when this disable arrives */
struct ep { int phase; int owner_is_current; const char *label; };

static const struct ep episodes[] = {
	{ PH_SYNC,    1, "sync, same task      -> should credit cfg0" },
	{ PH_SYNC,    1, "sync, same task      -> should credit cfg0" },
	{ PH_SYNC,    0, "sync, foreign task   -> should credit NOTHING" },
	{ PH_SYNC,    0, "sync, foreign task   -> should credit NOTHING" },
	{ PH_DELAYED, 0, "delayed window       -> should credit delayed_disable" },
	{ PH_DELAYED, 0, "delayed window       -> should credit delayed_disable" },
};

static void stop_enter(struct r1 *r)
{
	if (r->setup_phase == PH_SYNC) {
		if (r->owner_is_current) {
			r->stop_causal = SYNC_OWNER;
		} else {
			r->stop_causal = OVERLAP;
			r->overlap_count++;
		}
	} else if (r->setup_phase == PH_DELAYED) {
		r->stop_causal = DELAYED;
	} else {
		r->stop_causal = NONE;
	}
}

static void note_candidate(struct r1 *r)
{
	if (r->stop_causal == OVERLAP)
		return;
	if (r->stop_causal == DELAYED) {
		r->delayed_disable++;
		return;
	}
	r->cfg0++;			/* trigger is SET_CONFIGURATION(0) */
}

static void stop_exit(struct r1 *r) { r->stop_causal = NONE; }

static void run(int fixed, struct r1 *r)
{
	unsigned i;

	memset(r, 0, sizeof(*r));
	for (i = 0; i < sizeof(episodes) / sizeof(episodes[0]); i++) {
		r->setup_phase = episodes[i].phase;
		r->owner_is_current = episodes[i].owner_is_current;
		if (fixed) {
			stop_enter(r);
			note_candidate(r);
		} else {
			note_candidate(r);	/* reads a stale NONE */
			stop_enter(r);
		}
		stop_exit(r);
	}
}

int main(void)
{
	struct r1 old, new;
	int rc = 0;
	unsigned i;

	printf("episodes:\n");
	for (i = 0; i < sizeof(episodes) / sizeof(episodes[0]); i++)
		printf("  %s\n", episodes[i].label);

	run(0, &old);
	run(1, &new);

	printf("\n%-28s %8s %8s\n", "counter", "v6.3.1", "v6.3.2");
	printf("%-28s %8u %8u\n", "cfg0", old.cfg0, new.cfg0);
	printf("%-28s %8u %8u\n", "delayed_disable",
	       old.delayed_disable, new.delayed_disable);
	printf("%-28s %8u %8u\n", "overlap_count",
	       old.overlap_count, new.overlap_count);

	printf("\nexpected v6.3.1: cfg0=6 (all six credited), delayed_disable=0\n");
	printf("expected v6.3.2: cfg0=2, delayed_disable=2, 2 overlaps dropped\n\n");

	if (old.cfg0 != 6 || old.delayed_disable != 0) {
		printf("FAIL: the defect was not reproduced\n");
		rc = 1;
	} else {
		printf("ok  : v6.3.1 credited all 6 stops to cfg0 and never "
		       "incremented delayed_disable\n");
		printf("      -> both guarded branches were unreachable\n");
	}
	if (new.cfg0 != 2 || new.delayed_disable != 2) {
		printf("FAIL: the fixed order is wrong\n");
		rc = 1;
	} else {
		printf("ok  : v6.3.2 credits 2 to cfg0, 2 to delayed_disable, "
		       "and drops 2 overlaps\n");
	}

	printf("\nDENOMINATOR ORDER TEST: %s\n", rc ? "FAIL" : "PASS");
	return rc;
}
