from pathlib import Path

p = Path('linux/drivers/usb/dwc2/gadget.c')
s = p.read_text()


def once(old, new, label):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1 match, got {n}')
    s = s.replace(old, new, 1)


once(
'''static void dwc2_r1_measure_reset_entry(struct dwc2_hsotg *hsotg,
\t\t\t\t\tu32 gintsts)
{''',
'''static bool dwc2_r1_measure_reset_active(struct dwc2_hsotg_req *hs_req)
{
\treturn hs_req && hs_req->r1_linear && hs_req->r1_reset_id != 0;
}

static void dwc2_r1_measure_reset_entry(struct dwc2_hsotg *hsotg,
\t\t\t\t\tu32 gintsts)
{''',
'enabled reset-active helper',
)

once(
'''static inline void dwc2_r1_measure_epint_enter(struct dwc2_hsotg_ep *hs_ep) { }
static inline void dwc2_r1_measure_reset_entry(struct dwc2_hsotg *hsotg,
\t\t\t\t\t       u32 gintsts) { }''',
'''static inline void dwc2_r1_measure_epint_enter(struct dwc2_hsotg_ep *hs_ep) { }
static inline bool dwc2_r1_measure_reset_active(struct dwc2_hsotg_req *hs_req)
{
\treturn false;
}
static inline void dwc2_r1_measure_reset_entry(struct dwc2_hsotg *hsotg,
\t\t\t\t\t       u32 gintsts) { }''',
'disabled reset-active helper',
)

once(
'''\t\tdwc2_r1_measure_event(hsotg, hs_ep, hs_req,
\t\t\t\t       DWC2_R1_UNMAP_DONE, result,
\t\t\t\t       hs_req->r1_reset_id != 0);''',
'''\t\tdwc2_r1_measure_event(hsotg, hs_ep, hs_req,
\t\t\t\t       DWC2_R1_UNMAP_DONE, result,
\t\t\t\t       dwc2_r1_measure_reset_active(hs_req));''',
'unconditional reset-id field access',
)

p.write_text(s)
