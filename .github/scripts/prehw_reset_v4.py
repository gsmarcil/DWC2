from pathlib import Path

p = Path('linux/drivers/usb/dwc2/gadget.c')
s = p.read_text()

old = '''static void dwc2_r1_emit(struct dwc2_hsotg *hsotg,
\t\t\t struct dwc2_hsotg_ep *hs_ep,
\t\t\t struct dwc2_hsotg_req *hs_req,
\t\t\t u8 stage, int result, bool snapshot_regs,
\t\t\t dma_addr_t program_dma, u8 flags)
{
\tu32 epctl = 0, epint = 0, epsiz = 0;
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
\t\t\t       hs_req->r1_dma, program_dma,
\t\t\t       hs_req->r1_length, hs_req->req.actual,
\t\t\t       result, hs_req->req.status,
\t\t\t       hs_req->req.dma_mapped, epctl, epint, epsiz,
\t\t\t       epint_seq, flags);
}'''

new = '''static void dwc2_r1_emit(struct dwc2_hsotg *hsotg,
\t\t\t struct dwc2_hsotg_ep *hs_ep,
\t\t\t struct dwc2_hsotg_req *hs_req,
\t\t\t u8 stage, int result, bool snapshot_regs,
\t\t\t dma_addr_t program_dma, u8 flags)
{
\tdma_addr_t event_dma = 0, event_program_dma = 0;
\tu32 event_length = 0, event_actual = 0;
\tint event_result = 0, event_status = 0;
\tbool event_dma_mapped = false;
\tu32 epctl = 0, epint = 0, epsiz = 0;
\tu64 epint_seq = 0;

\tif (!hs_req || !hs_req->r1_linear)
\t\treturn;

\t/*
\t * UNMAP_DONE is intentionally post-lifetime. Keep that event free of
\t * retired-mapping/request-payload reads: only stable lineage metadata
\t * and raw endpoint MMIO are emitted after U. Mapping/payload fields
\t * are zero sentinels for this stage.
\t */
\tif (stage != DWC2_R1_UNMAP_DONE) {
\t\tevent_dma = hs_req->r1_dma;
\t\tevent_program_dma = program_dma;
\t\tevent_length = hs_req->r1_length;
\t\tevent_actual = hs_req->req.actual;
\t\tevent_result = result;
\t\tevent_status = hs_req->req.status;
\t\tevent_dma_mapped = hs_req->req.dma_mapped;
\t}

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
\t\t\t       event_dma, event_program_dma,
\t\t\t       event_length, event_actual,
\t\t\t       event_result, event_status,
\t\t\t       event_dma_mapped, epctl, epint, epsiz,
\t\t\t       epint_seq, flags);
}'''

count = s.count(old)
if count != 1:
    raise SystemExit(f'dwc2_r1_emit: expected 1 match, got {count}')

p.write_text(s.replace(old, new, 1))
