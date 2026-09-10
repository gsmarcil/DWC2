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
s = once(s,
'''\tu64 r1_req_id;
\tu64 r1_map_id;
\tdma_addr_t r1_dma;
\tu32 r1_length;
\tbool r1_linear;''',
'''\tu64 r1_req_id;
\tu64 r1_map_id;
\tu64 r1_program_id;
\tdma_addr_t r1_dma;
\tu32 r1_length;
\tbool r1_linear;''',
'core.h request lineage')
s = once(s,
'''\tstruct dwc2_hsotg_req    *req;
\tstruct dentry           *debugfs;

\tunsigned long           total_data;''',
'''\tstruct dwc2_hsotg_req    *req;
\tstruct dentry           *debugfs;
#ifdef CONFIG_USB_DWC2_R1_MEASURE
\tu64                     r1_epint_seq;
#endif

\tunsigned long           total_data;''',
'core.h epint generation')
coreh.write_text(s)

s = gadget.read_text()
s = once(s,
'''enum dwc2_r1_lifetime_stage {
\tDWC2_R1_MAP = 1,
\tDWC2_R1_PROGRAMMED = 2,
\tDWC2_R1_UNMAP_BEGIN = 3,
\tDWC2_R1_UNMAP_DONE = 4,
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
};''',
'stage enum')

start = s.index('static void dwc2_r1_measure_reset(struct dwc2_hsotg_req *hs_req)')
end = s.index('/**\n * dwc2_gadget_incr_frame_num', start)
helper = r'''static void dwc2_r1_measure_reset(struct dwc2_hsotg_req *hs_req)
{
\ths_req->r1_req_id = 0;
\ths_req->r1_map_id = 0;
\ths_req->r1_program_id = 0;
\ths_req->r1_dma = 0;
\ths_req->r1_length = 0;
\ths_req->r1_linear = false;
}

static bool dwc2_r1_measure_eligible(struct dwc2_hsotg *hsotg,
\t\t\t\t     struct dwc2_hsotg_ep *hs_ep,
\t\t\t\t     struct dwc2_hsotg_req *hs_req)
{
\tstruct usb_request *req = &hs_req->req;

\treturn using_dma(hsotg) && !using_desc_dma(hsotg) && hs_ep->index &&
\t       !hs_ep->dir_in && hs_ep->ep.desc &&
\t       usb_endpoint_xfer_bulk(hs_ep->ep.desc) && req->length &&
\t       !req->sg_was_mapped && !req->num_sgs && req->dma_mapped &&
\t       !hs_req->saved_req_buf;
}

static void dwc2_r1_emit(struct dwc2_hsotg *hsotg,
\t\t\t struct dwc2_hsotg_ep *hs_ep,
\t\t\t struct dwc2_hsotg_req *hs_req,
\t\t\t u8 stage, int result, bool snapshot_regs,
\t\t\t dma_addr_t program_dma, u8 flags)
{
\tu32 epctl = 0, epint = 0, epsiz = 0;
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
\t\t\t       hs_ep->index, hs_req->r1_dma, program_dma,
\t\t\t       hs_req->r1_length, hs_req->req.actual,
\t\t\t       result, hs_req->req.status,
\t\t\t       hs_req->req.dma_mapped, epctl, epint, epsiz,
\t\t\t       epint_seq, flags);
}

static void dwc2_r1_measure_mapped(struct dwc2_hsotg *hsotg,
\t\t\t\t   struct dwc2_hsotg_ep *hs_ep,
\t\t\t\t   struct dwc2_hsotg_req *hs_req)
{
\tif (!dwc2_r1_measure_eligible(hsotg, hs_ep, hs_req))
\t\treturn;

\ths_req->r1_req_id = atomic64_inc_return(&dwc2_r1_req_seq);
\ths_req->r1_map_id = atomic64_inc_return(&dwc2_r1_map_seq);
\ths_req->r1_program_id = 0;
\ths_req->r1_dma = hs_req->req.dma;
\ths_req->r1_length = hs_req->req.length;
\ths_req->r1_linear = true;
\tdwc2_r1_emit(hsotg, hs_ep, hs_req, DWC2_R1_MAP, 0, false, 0, 0);
}

static void dwc2_r1_measure_programmed(struct dwc2_hsotg *hsotg,
\t\t\t\t       struct dwc2_hsotg_ep *hs_ep,
\t\t\t\t       struct dwc2_hsotg_req *hs_req,
\t\t\t\t       bool dma_written)
{
\tdma_addr_t program_dma = 0;

\tif (!hs_req || !hs_req->r1_linear || hs_ep->dir_in)
\t\treturn;

\ths_req->r1_program_id++;
\tif (dma_written)
\t\tprogram_dma = hs_req->req.dma;
\tdwc2_r1_emit(hsotg, hs_ep, hs_req, DWC2_R1_PROGRAMMED, 0,
\t\t     false, program_dma, dma_written ? 1 : 0);
}

static void dwc2_r1_measure_event(struct dwc2_hsotg *hsotg,
\t\t\t\t  struct dwc2_hsotg_ep *hs_ep,
\t\t\t\t  struct dwc2_hsotg_req *hs_req,
\t\t\t\t  u8 stage, int result, bool snapshot_regs)
{
\tdwc2_r1_emit(hsotg, hs_ep, hs_req, stage, result,
\t\t     snapshot_regs, 0, 0);
}

static void dwc2_r1_measure_epint_enter(struct dwc2_hsotg_ep *hs_ep)
{
\tif (hs_ep && !hs_ep->dir_in)
\t\ths_ep->r1_epint_seq++;
}
#else
static inline void dwc2_r1_measure_reset(struct dwc2_hsotg_req *hs_req) { }
static inline void dwc2_r1_measure_mapped(struct dwc2_hsotg *hsotg,
\t\t\t\t\t  struct dwc2_hsotg_ep *hs_ep,
\t\t\t\t\t  struct dwc2_hsotg_req *hs_req) { }
static inline void dwc2_r1_measure_programmed(struct dwc2_hsotg *hsotg,
\t\t\t\t\t      struct dwc2_hsotg_ep *hs_ep,
\t\t\t\t\t      struct dwc2_hsotg_req *hs_req,
\t\t\t\t\t      bool dma_written) { }
static inline void dwc2_r1_measure_event(struct dwc2_hsotg *hsotg,
\t\t\t\t\t struct dwc2_hsotg_ep *hs_ep,
\t\t\t\t\t struct dwc2_hsotg_req *hs_req,
\t\t\t\t\t u8 stage, int result,
\t\t\t\t\t bool snapshot_regs) { }
static inline void dwc2_r1_measure_epint_enter(struct dwc2_hsotg_ep *hs_ep) { }
#endif

'''
s = s[:start] + helper + s[end:]

s = once(s,
'''
\t\t\tdwc2_r1_measure_event(hs_ep, hs_req,
\t\t\t\t\t       DWC2_R1_PROGRAMMED, 0);
''',
'\n',
'old programmed event')

s = once(s,
'''\tdev_dbg(hsotg->dev, "%s: DxEPCTL=0x%08x\\n", __func__, ctrl);
\tdwc2_writel(hsotg, ctrl, epctrl_reg);

\t/*
\t * set these, it seems that DMA support increments past the end''',
'''\tdev_dbg(hsotg->dev, "%s: DxEPCTL=0x%08x\\n", __func__, ctrl);
\tdwc2_writel(hsotg, ctrl, epctrl_reg);
\tdwc2_r1_measure_programmed(hsotg, hs_ep, hs_req,
\t\t\t\t   using_dma(hsotg) && !continuing && length != 0);

\t/*
\t * set these, it seems that DMA support increments past the end''',
'EPENA handoff')

s = once(s,
'''\tu32 ints;

\tints = dwc2_gadget_read_ep_interrupts(hsotg, idx, dir_in);''',
'''\tu32 ints;

\tdwc2_r1_measure_epint_enter(hs_ep);
\tints = dwc2_gadget_read_ep_interrupts(hsotg, idx, dir_in);''',
'epint entry sequence')

s = once(s,
'''\tif (ints & DXEPINT_XFERCOMPL) {
\t\tdev_dbg(hsotg->dev,''',
'''\tif (ints & DXEPINT_XFERCOMPL) {
\t\tdwc2_r1_measure_event(hsotg, hs_ep, hs_ep->req,
\t\t\t\t       DWC2_R1_XFERCOMPL_PATH, 0, false);
\t\tdev_dbg(hsotg->dev,''',
'completion path witness')

s = once(s,
'''static void dwc2_hsotg_ep_stop_xfr(struct dwc2_hsotg *hsotg,
\t\t\t\t   struct dwc2_hsotg_ep *hs_ep)
{
\tu32 epctrl_reg;
\tu32 epint_reg;''',
'''static void dwc2_hsotg_ep_stop_xfr(struct dwc2_hsotg *hsotg,
\t\t\t\t   struct dwc2_hsotg_ep *hs_ep)
{
\tu32 epctrl_reg;
\tu32 epint_reg;
\tint epdis_wait;''',
'epdis wait local')

s = once(s,
'''\t/* Disable ep */
\tdwc2_set_bit(hsotg, epctrl_reg, DXEPCTL_EPDIS | DXEPCTL_SNAK);

\t/* Wait for ep to be disabled */
\tif (dwc2_hsotg_wait_bit_set(hsotg, epint_reg, DXEPINT_EPDISBLD, 100))
\t\tdev_warn(hsotg->dev,
\t\t\t "%s: timeout DOEPCTL.EPDisable\\n", __func__);''',
'''\t/* Disable ep */
\tdwc2_r1_measure_event(hsotg, hs_ep, hs_ep->req,
\t\t\t       DWC2_R1_EPDIS_ASSERT, 0, true);
\tdwc2_set_bit(hsotg, epctrl_reg, DXEPCTL_EPDIS | DXEPCTL_SNAK);

\t/* Wait for ep to be disabled. Keep the natural polling loop untouched. */
\tepdis_wait = dwc2_hsotg_wait_bit_set(hsotg, epint_reg,
\t\t\t\t\t     DXEPINT_EPDISBLD, 100);
\tdwc2_r1_measure_event(hsotg, hs_ep, hs_ep->req,
\t\t\t       DWC2_R1_WAIT_RETURN, epdis_wait, true);
\tif (epdis_wait)
\t\tdev_warn(hsotg->dev,
\t\t\t "%s: timeout DOEPCTL.EPDisable\\n", __func__);''',
'EPDIS assert/wait-return')

s = once(s,
'''\tif (using_dma(hsotg)) {
\t\tdwc2_r1_measure_event(hs_ep, hs_req,
\t\t\t\t       DWC2_R1_UNMAP_BEGIN, result);
\t\tdwc2_hsotg_unmap_dma(hsotg, hs_ep, hs_req);
\t\tdwc2_r1_measure_event(hs_ep, hs_req,
\t\t\t\t       DWC2_R1_UNMAP_DONE, result);
\t}''',
'''\tif (using_dma(hsotg)) {
\t\tdwc2_r1_measure_event(hsotg, hs_ep, hs_req,
\t\t\t\t       DWC2_R1_PRE_U, 0, true);
\t\tdwc2_r1_measure_event(hsotg, hs_ep, hs_req,
\t\t\t\t       DWC2_R1_UNMAP_BEGIN, result, false);
\t\tdwc2_hsotg_unmap_dma(hsotg, hs_ep, hs_req);
\t\tdwc2_r1_measure_event(hsotg, hs_ep, hs_req,
\t\t\t\t       DWC2_R1_UNMAP_DONE, result, false);
\t}''',
'PRE_U/unmap lineage')
gadget.write_text(s)

trace.write_text(r'''/* SPDX-License-Identifier: GPL-2.0 */
#undef TRACE_SYSTEM
#define TRACE_SYSTEM dwc2_r1

#if !defined(_TRACE_DWC2_R1_H) || defined(TRACE_HEADER_MULTI_READ)
#define _TRACE_DWC2_R1_H

#include <linux/tracepoint.h>

TRACE_EVENT(dwc2_r1_lifetime,
\tTP_PROTO(u8 stage, u64 req_id, u64 map_id, u64 program_id,
\t\t u8 ep_index, u64 dma_addr, u64 program_dma, u32 length,
\t\t u32 actual, int result, int status, bool dma_mapped,
\t\t u32 epctl, u32 epint, u32 epsiz, u64 epint_seq, u8 flags),

\tTP_ARGS(stage, req_id, map_id, program_id, ep_index, dma_addr,
\t\tprogram_dma, length, actual, result, status, dma_mapped,
\t\tepctl, epint, epsiz, epint_seq, flags),

\tTP_STRUCT__entry(
\t\t__field(u8, stage)
\t\t__field(u64, req_id)
\t\t__field(u64, map_id)
\t\t__field(u64, program_id)
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

\tTP_printk("stage=%u req=%llu map=%llu program=%llu ep=%u dma=0x%llx program_dma=0x%llx len=%u actual=%u result=%d status=%d dma_mapped=%u epctl=0x%08x epint=0x%08x epsiz=0x%08x epint_seq=%llu flags=0x%x",
\t\t  __entry->stage,
\t\t  (unsigned long long)__entry->req_id,
\t\t  (unsigned long long)__entry->map_id,
\t\t  (unsigned long long)__entry->program_id,
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
