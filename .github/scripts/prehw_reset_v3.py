from pathlib import Path

root = Path('linux/drivers/usb/dwc2')
coreh = root / 'core.h'
gadget = root / 'gadget.c'
trace = root / 'trace-r1.h'


def once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, got {n}')
    return text.replace(old, new, 1)


s = coreh.read_text()
s = once(
    s,
    '\tu64 r1_req_id;\n\tu64 r1_map_id;\n\tu64 r1_program_id;\n\tdma_addr_t r1_dma;',
    '\tu64 r1_req_id;\n\tu64 r1_map_id;\n\tu64 r1_program_id;\n\tu64 r1_reset_id;\n\tdma_addr_t r1_dma;',
    'core.h reset lineage',
)
coreh.write_text(s)

s = gadget.read_text()
s = once(
    s,
    '''enum dwc2_r1_lifetime_stage {
\tDWC2_R1_MAP = 1,
\tDWC2_R1_PROGRAMMED = 2,
\tDWC2_R1_XFERCOMPL_PATH = 3,
\tDWC2_R1_EPDIS_ASSERT = 4,
\tDWC2_R1_WAIT_RETURN = 5,
\tDWC2_R1_PRE_U = 6,
\tDWC2_R1_UNMAP_BEGIN = 7,
\tDWC2_R1_UNMAP_DONE = 8,
};''',
    '''enum dwc2_r1_lifetime_stage {
\tDWC2_R1_MAP = 1,
\tDWC2_R1_PROGRAMMED = 2,
\tDWC2_R1_XFERCOMPL_PATH = 3,
\tDWC2_R1_EPDIS_ASSERT = 4,
\tDWC2_R1_WAIT_RETURN = 5,
\tDWC2_R1_PRE_U = 6,
\tDWC2_R1_UNMAP_BEGIN = 7,
\tDWC2_R1_UNMAP_DONE = 8,
\tDWC2_R1_RESET_ENTRY = 9,
};''',
    'stage enum reset entry',
)
s = once(
    s,
    '''static atomic64_t dwc2_r1_req_seq = ATOMIC64_INIT(0);
static atomic64_t dwc2_r1_map_seq = ATOMIC64_INIT(0);''',
    '''static atomic64_t dwc2_r1_req_seq = ATOMIC64_INIT(0);
static atomic64_t dwc2_r1_map_seq = ATOMIC64_INIT(0);
static atomic64_t dwc2_r1_reset_seq = ATOMIC64_INIT(0);''',
    'reset sequence counter',
)
s = once(
    s,
    '''\ths_req->r1_req_id = 0;
\ths_req->r1_map_id = 0;
\ths_req->r1_program_id = 0;
\ths_req->r1_dma = 0;''',
    '''\ths_req->r1_req_id = 0;
\ths_req->r1_map_id = 0;
\ths_req->r1_program_id = 0;
\ths_req->r1_reset_id = 0;
\ths_req->r1_dma = 0;''',
    'reset request reset-id',
)
s = once(
    s,
    '''\tu32 epctl = 0, epint = 0, epsiz = 0;
\tu64 epint_seq = 0;

\tif (!hs_req || !hs_req->r1_linear)
\t\treturn;

\tif (snapshot_regs && !hs_ep->dir_in) {
\t\tepctl = dwc2_readl(hsotg, DOEPCTL(hs_ep->index));
\t\tepint = dwc2_readl(hsotg, DOEPINT(hs_ep->index));
\t\tepsiz = dwc2_readl(hsotg, DOEPTSIZ(hs_ep->index));
\t\tepint_seq = hs_ep->r1_epint_seq;
\t}

\ttrace_dwc2_r1_lifetime(stage, hs_req->r1_req_id,
\t\t\t       hs_req->r1_map_id, hs_req->r1_program_id,
\t\t\t       hs_ep->index, hs_req->r1_dma, program_dma,''',
    '''\tu32 epctl = 0, epint = 0, epsiz = 0;
\tu64 epint_seq = 0;

\tif (!hs_req || !hs_req->r1_linear)
\t\treturn;

\tif (!hs_ep->dir_in) {
\t\tepint_seq = hs_ep->r1_epint_seq;
\t\tif (snapshot_regs) {
\t\t\tepctl = dwc2_readl(hsotg, DOEPCTL(hs_ep->index));
\t\t\tepint = dwc2_readl(hsotg, DOEPINT(hs_ep->index));
\t\t\tepsiz = dwc2_readl(hsotg, DOEPTSIZ(hs_ep->index));
\t\t}
\t}

\ttrace_dwc2_r1_lifetime(stage, hs_req->r1_req_id,
\t\t\t       hs_req->r1_map_id, hs_req->r1_program_id,
\t\t\t       hs_req->r1_reset_id, hs_ep->index,
\t\t\t       hs_req->r1_dma, program_dma,''',
    'emit reset-id and unconditional epint generation',
)
s = once(
    s,
    '''\ths_req->r1_req_id = atomic64_inc_return(&dwc2_r1_req_seq);
\ths_req->r1_map_id = atomic64_inc_return(&dwc2_r1_map_seq);
\ths_req->r1_program_id = 0;
\ths_req->r1_dma = hs_req->req.dma;''',
    '''\ths_req->r1_req_id = atomic64_inc_return(&dwc2_r1_req_seq);
\ths_req->r1_map_id = atomic64_inc_return(&dwc2_r1_map_seq);
\ths_req->r1_program_id = 0;
\ths_req->r1_reset_id = 0;
\ths_req->r1_dma = hs_req->req.dma;''',
    'map clears reset-id',
)
needle = '''static void dwc2_r1_measure_epint_enter(struct dwc2_hsotg_ep *hs_ep)
{
\tif (hs_ep && !hs_ep->dir_in)
\t\ths_ep->r1_epint_seq++;
}
#else'''
replacement = '''static void dwc2_r1_measure_epint_enter(struct dwc2_hsotg_ep *hs_ep)
{
\tif (hs_ep && !hs_ep->dir_in)
\t\ths_ep->r1_epint_seq++;
}

static void dwc2_r1_measure_reset_entry(struct dwc2_hsotg *hsotg,
\t\t\t\t\tu32 gintsts)
{
\tu64 reset_id = atomic64_inc_return(&dwc2_r1_reset_seq);
\tu8 flags = 0;
\tunsigned int idx;

\tif (gintsts & GINTSTS_USBRST)
\t\tflags |= BIT(0);
\tif (gintsts & GINTSTS_RESETDET)
\t\tflags |= BIT(1);

\tfor (idx = 1; idx < hsotg->num_of_eps; idx++) {
\t\tstruct dwc2_hsotg_ep *hs_ep = hsotg->eps_out[idx];
\t\tstruct dwc2_hsotg_req *hs_req;

\t\tif (!hs_ep)
\t\t\tcontinue;
\t\ths_req = hs_ep->req;
\t\tif (!hs_req || !hs_req->r1_linear)
\t\t\tcontinue;

\t\ths_req->r1_reset_id = reset_id;
\t\tdwc2_r1_emit(hsotg, hs_ep, hs_req, DWC2_R1_RESET_ENTRY,
\t\t\t     0, true, 0, flags);
\t}
}
#else'''
s = once(s, needle, replacement, 'reset-entry helper')
s = once(
    s,
    '''static inline void dwc2_r1_measure_epint_enter(struct dwc2_hsotg_ep *hs_ep) { }
#endif''',
    '''static inline void dwc2_r1_measure_epint_enter(struct dwc2_hsotg_ep *hs_ep) { }
static inline void dwc2_r1_measure_reset_entry(struct dwc2_hsotg *hsotg,
\t\t\t\t\t       u32 gintsts) { }
#endif''',
    'reset-entry disabled stub',
)
s = once(
    s,
    '''\t\t/* Report disconnection if it is not already done. */
\t\tdwc2_hsotg_disconnect(hsotg);''',
    '''\t\t/* Preserve active reset lineage before disconnect retires it. */
\t\tdwc2_r1_measure_reset_entry(hsotg, gintsts);

\t\t/* Report disconnection if it is not already done. */
\t\tdwc2_hsotg_disconnect(hsotg);''',
    'reset IRQ pre-disconnect hook',
)
s = once(
    s,
    '''\t\tdwc2_r1_measure_event(hsotg, hs_ep, hs_req,
\t\t\t\t       DWC2_R1_UNMAP_DONE, result, false);''',
    '''\t\tdwc2_r1_measure_event(hsotg, hs_ep, hs_req,
\t\t\t\t       DWC2_R1_UNMAP_DONE, result,
\t\t\t\t       hs_req->r1_reset_id != 0);''',
    'reset-safe post-unmap snapshot',
)
gadget.write_text(s)

trace.write_text('''/* SPDX-License-Identifier: GPL-2.0 */
#undef TRACE_SYSTEM
#define TRACE_SYSTEM dwc2_r1

#if !defined(_TRACE_DWC2_R1_H) || defined(TRACE_HEADER_MULTI_READ)
#define _TRACE_DWC2_R1_H

#include <linux/tracepoint.h>

TRACE_EVENT(dwc2_r1_lifetime,
\tTP_PROTO(u8 stage, u64 req_id, u64 map_id, u64 program_id,
\t\t u64 reset_id, u8 ep_index, u64 dma_addr, u64 program_dma,
\t\t u32 length, u32 actual, int result, int status,
\t\t bool dma_mapped, u32 epctl, u32 epint, u32 epsiz,
\t\t u64 epint_seq, u8 flags),

\tTP_ARGS(stage, req_id, map_id, program_id, reset_id, ep_index,
\t\tdma_addr, program_dma, length, actual, result, status,
\t\tdma_mapped, epctl, epint, epsiz, epint_seq, flags),

\tTP_STRUCT__entry(
\t\t__field(u8, stage)
\t\t__field(u64, req_id)
\t\t__field(u64, map_id)
\t\t__field(u64, program_id)
\t\t__field(u64, reset_id)
\t\t__field(u8, ep_index)
\t\t__field(u64, dma_addr)
\t\t__field(u64, program_dma)
\t\t__field(u32, length)
\t\t__field(u32, actual)
\t\t__field(int, result)
\t\t__field(int, status)
\t\t__field(bool, dma_mapped)
\t\t__field(u32, epctl)
\t\t__field(u32, epint)
\t\t__field(u32, epsiz)
\t\t__field(u64, epint_seq)
\t\t__field(u8, flags)
\t),

\tTP_fast_assign(
\t\t__entry->stage = stage;
\t\t__entry->req_id = req_id;
\t\t__entry->map_id = map_id;
\t\t__entry->program_id = program_id;
\t\t__entry->reset_id = reset_id;
\t\t__entry->ep_index = ep_index;
\t\t__entry->dma_addr = dma_addr;
\t\t__entry->program_dma = program_dma;
\t\t__entry->length = length;
\t\t__entry->actual = actual;
\t\t__entry->result = result;
\t\t__entry->status = status;
\t\t__entry->dma_mapped = dma_mapped;
\t\t__entry->epctl = epctl;
\t\t__entry->epint = epint;
\t\t__entry->epsiz = epsiz;
\t\t__entry->epint_seq = epint_seq;
\t\t__entry->flags = flags;
\t),

\tTP_printk("stage=%u req=%llu map=%llu program=%llu reset=%llu ep=%u dma=0x%llx program_dma=0x%llx len=%u actual=%u result=%d status=%d dma_mapped=%u epctl=0x%08x epint=0x%08x epsiz=0x%08x epint_seq=%llu flags=0x%x",
\t\t  __entry->stage,
\t\t  (unsigned long long)__entry->req_id,
\t\t  (unsigned long long)__entry->map_id,
\t\t  (unsigned long long)__entry->program_id,
\t\t  (unsigned long long)__entry->reset_id,
\t\t  __entry->ep_index,
\t\t  (unsigned long long)__entry->dma_addr,
\t\t  (unsigned long long)__entry->program_dma,
\t\t  __entry->length, __entry->actual, __entry->result,
\t\t  __entry->status, __entry->dma_mapped, __entry->epctl,
\t\t  __entry->epint, __entry->epsiz,
\t\t  (unsigned long long)__entry->epint_seq, __entry->flags)
);

#endif /* _TRACE_DWC2_R1_H */

#undef TRACE_INCLUDE_PATH
#define TRACE_INCLUDE_PATH ../../drivers/usb/dwc2
#undef TRACE_INCLUDE_FILE
#define TRACE_INCLUDE_FILE trace-r1

#include <trace/define_trace.h>
''')
