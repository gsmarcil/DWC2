#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
DWC2 = ROOT / "drivers/usb/dwc2"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"ANCHOR_FAIL {path}: expected 1 occurrence, found {n}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1))


# Kconfig: measurement-only, default off.
kconfig = DWC2 / "Kconfig"
anchor = '''config USB_DWC2_DEBUG_PERIODIC\n'''
insert = '''config USB_DWC2_R1_MEASURE\n\tbool "Enable DWC2 R1 DMA lifetime tracepoints"\n\tdepends on TRACING\n\tdefault n\n\thelp\n\t  Enable measurement-only tracepoints for the DWC2 R1 DMA lifetime\n\t  experiment. The first campaign admits only non-EP0 Bulk OUT requests\n\t  using address/buffer DMA, a core-owned linear mapping, and no DWC2\n\t  alignment bounce. It records mapping/programming/unmap ordering and\n\t  stable request/map generations; it does not assert a post-unmap DMA\n\t  issue or memory effect. Say N for normal kernels.\n\nconfig USB_DWC2_DEBUG_PERIODIC\n'''
replace_once(kconfig, anchor, insert)

# Per-request measurement identity exists only in instrumented builds.
core = DWC2 / "core.h"
anchor = '''\tstruct list_head        queue;\n\tvoid *saved_req_buf;\n};\n'''
insert = '''\tstruct list_head        queue;\n\tvoid *saved_req_buf;\n#ifdef CONFIG_USB_DWC2_R1_MEASURE\n\tu64 r1_req_id;\n\tu64 r1_map_id;\n\tdma_addr_t r1_dma;\n\tu32 r1_length;\n\tbool r1_linear;\n#endif\n};\n'''
replace_once(core, anchor, insert)

# Tracepoint implementation lives in gadget.c so no normal-build object changes.
gadget = DWC2 / "gadget.c"
anchor = '''#include <linux/slab.h>\n\n#include <linux/usb/ch9.h>\n'''
insert = '''#include <linux/slab.h>\n\n#ifdef CONFIG_USB_DWC2_R1_MEASURE\n#include <linux/atomic.h>\n#define CREATE_TRACE_POINTS\n#include "trace-r1.h"\n#endif\n\n#include <linux/usb/ch9.h>\n'''
replace_once(gadget, anchor, insert)

anchor = '''static inline bool using_desc_dma(struct dwc2_hsotg *hsotg)\n{\n\treturn hsotg->params.g_dma_desc;\n}\n\n'''
insert = anchor + '''#ifdef CONFIG_USB_DWC2_R1_MEASURE\nstatic atomic64_t dwc2_r1_req_seq = ATOMIC64_INIT(0);\nstatic atomic64_t dwc2_r1_map_seq = ATOMIC64_INIT(0);\n\nstatic void dwc2_r1_measure_reset(struct dwc2_hsotg_req *hs_req)\n{\n\ths_req->r1_req_id = 0;\n\ths_req->r1_map_id = 0;\n\ths_req->r1_dma = 0;\n\ths_req->r1_length = 0;\n\ths_req->r1_linear = false;\n}\n\nstatic bool dwc2_r1_measure_eligible(struct dwc2_hsotg *hsotg,\n\t\t\t\t\t     struct dwc2_hsotg_ep *hs_ep,\n\t\t\t\t\t     struct dwc2_hsotg_req *hs_req)\n{\n\tstruct usb_request *req = &hs_req->req;\n\n\treturn using_dma(hsotg) && !using_desc_dma(hsotg) && hs_ep->index &&\n\t       !hs_ep->dir_in && hs_ep->ep.desc &&\n\t       usb_endpoint_xfer_bulk(hs_ep->ep.desc) && req->length &&\n\t       !req->sg_was_mapped && !req->num_sgs && req->dma_mapped &&\n\t       !hs_req->saved_req_buf;\n}\n\nstatic void dwc2_r1_measure_mapped(struct dwc2_hsotg *hsotg,\n\t\t\t\t\t   struct dwc2_hsotg_ep *hs_ep,\n\t\t\t\t\t   struct dwc2_hsotg_req *hs_req)\n{\n\tif (!dwc2_r1_measure_eligible(hsotg, hs_ep, hs_req))\n\t\treturn;\n\n\ths_req->r1_req_id = atomic64_inc_return(&dwc2_r1_req_seq);\n\ths_req->r1_map_id = atomic64_inc_return(&dwc2_r1_map_seq);\n\ths_req->r1_dma = hs_req->req.dma;\n\ths_req->r1_length = hs_req->req.length;\n\ths_req->r1_linear = true;\n\ttrace_dwc2_r1_lifetime(DWC2_R1_MAP, hs_req->r1_req_id,\n\t\t\t       hs_req->r1_map_id, hs_ep->index,\n\t\t\t       (u64)hs_req->r1_dma, hs_req->r1_length,\n\t\t\t       hs_req->req.actual, 0, hs_req->req.status,\n\t\t\t       hs_req->req.dma_mapped);\n}\n\nstatic void dwc2_r1_measure_event(struct dwc2_hsotg_ep *hs_ep,\n\t\t\t\t   struct dwc2_hsotg_req *hs_req,\n\t\t\t\t   u8 stage, int result)\n{\n\tif (!hs_req->r1_linear)\n\t\treturn;\n\n\ttrace_dwc2_r1_lifetime(stage, hs_req->r1_req_id, hs_req->r1_map_id,\n\t\t\t       hs_ep->index, (u64)hs_req->r1_dma,\n\t\t\t       hs_req->r1_length, hs_req->req.actual, result,\n\t\t\t       hs_req->req.status, hs_req->req.dma_mapped);\n}\n#else\nstatic inline void dwc2_r1_measure_reset(struct dwc2_hsotg_req *hs_req) { }\nstatic inline void dwc2_r1_measure_mapped(struct dwc2_hsotg *hsotg,\n\t\t\t\t\t\t  struct dwc2_hsotg_ep *hs_ep,\n\t\t\t\t\t\t  struct dwc2_hsotg_req *hs_req) { }\nstatic inline void dwc2_r1_measure_event(struct dwc2_hsotg_ep *hs_ep,\n\t\t\t\t\t struct dwc2_hsotg_req *hs_req,\n\t\t\t\t\t u8 stage, int result) { }\n#endif\n\n'''
replace_once(gadget, anchor, insert)

anchor = '''\tINIT_LIST_HEAD(&hs_req->queue);\n\treq->actual = 0;\n\treq->status = -EINPROGRESS;\n'''
insert = anchor + '''\tdwc2_r1_measure_reset(hs_req);\n'''
replace_once(gadget, anchor, insert)

anchor = '''\tif (using_dma(hs)) {\n\t\tret = dwc2_hsotg_map_dma(hs, hs_ep, req);\n\t\tif (ret)\n\t\t\treturn ret;\n\t}\n'''
insert = '''\tif (using_dma(hs)) {\n\t\tret = dwc2_hsotg_map_dma(hs, hs_ep, req);\n\t\tif (ret)\n\t\t\treturn ret;\n\t\tdwc2_r1_measure_mapped(hs, hs_ep, hs_req);\n\t}\n'''
replace_once(gadget, anchor, insert)

anchor = '''\t\t\tdwc2_writel(hsotg, ureq->dma, dma_reg);\n\n\t\t\tdev_dbg(hsotg->dev, "%s: %pad => 0x%08x\\n",\n'''
insert = '''\t\t\tdwc2_writel(hsotg, ureq->dma, dma_reg);\n\n\t\t\tdwc2_r1_measure_event(hs_ep, hs_req,\n\t\t\t\t\t       DWC2_R1_PROGRAMMED, 0);\n\n\t\t\tdev_dbg(hsotg->dev, "%s: %pad => 0x%08x\\n",\n'''
replace_once(gadget, anchor, insert)

anchor = '''\tif (using_dma(hsotg))\n\t\tdwc2_hsotg_unmap_dma(hsotg, hs_ep, hs_req);\n'''
insert = '''\tif (using_dma(hsotg)) {\n\t\tdwc2_r1_measure_event(hs_ep, hs_req,\n\t\t\t\t       DWC2_R1_UNMAP_BEGIN, result);\n\t\tdwc2_hsotg_unmap_dma(hsotg, hs_ep, hs_req);\n\t\tdwc2_r1_measure_event(hs_ep, hs_req,\n\t\t\t\t       DWC2_R1_UNMAP_DONE, result);\n\t}\n'''
replace_once(gadget, anchor, insert)

trace = DWC2 / "trace-r1.h"
if trace.exists():
    raise SystemExit(f"ANCHOR_FAIL {trace}: already exists")
trace.write_text(r'''/* SPDX-License-Identifier: GPL-2.0 */
#undef TRACE_SYSTEM
#define TRACE_SYSTEM dwc2_r1

#if !defined(_TRACE_DWC2_R1_H) || defined(TRACE_HEADER_MULTI_READ)
#define _TRACE_DWC2_R1_H

#include <linux/tracepoint.h>

enum dwc2_r1_lifetime_stage {
	DWC2_R1_MAP = 1,
	DWC2_R1_PROGRAMMED = 2,
	DWC2_R1_UNMAP_BEGIN = 3,
	DWC2_R1_UNMAP_DONE = 4,
};

TRACE_EVENT(dwc2_r1_lifetime,
	TP_PROTO(u8 stage, u64 req_id, u64 map_id, u8 ep_index,
		 u64 dma_addr, u32 length, u32 actual, int result,
		 int status, bool dma_mapped),

	TP_ARGS(stage, req_id, map_id, ep_index, dma_addr, length, actual,
		result, status, dma_mapped),

	TP_STRUCT__entry(
		__field(u8, stage)
		__field(u64, req_id)
		__field(u64, map_id)
		__field(u8, ep_index)
		__field(u64, dma_addr)
		__field(u32, length)
		__field(u32, actual)
		__field(int, result)
		__field(int, status)
		__field(bool, dma_mapped)
	),

	TP_fast_assign(
		__entry->stage = stage;
		__entry->req_id = req_id;
		__entry->map_id = map_id;
		__entry->ep_index = ep_index;
		__entry->dma_addr = dma_addr;
		__entry->length = length;
		__entry->actual = actual;
		__entry->result = result;
		__entry->status = status;
		__entry->dma_mapped = dma_mapped;
	),

	TP_printk("stage=%u req=%llu map=%llu ep=%u dma=0x%llx len=%u actual=%u result=%d status=%d dma_mapped=%u",
		  __entry->stage,
		  (unsigned long long)__entry->req_id,
		  (unsigned long long)__entry->map_id,
		  __entry->ep_index,
		  (unsigned long long)__entry->dma_addr,
		  __entry->length, __entry->actual, __entry->result,
		  __entry->status, __entry->dma_mapped)
);

#endif /* _TRACE_DWC2_R1_H */

#undef TRACE_INCLUDE_PATH
#define TRACE_INCLUDE_PATH .
#undef TRACE_INCLUDE_FILE
#define TRACE_INCLUDE_FILE trace-r1

#include <trace/define_trace.h>
''')

print("R1_MEASURE_APPLY: PASS")
