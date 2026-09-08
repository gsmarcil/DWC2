#!/usr/bin/env python3
"""Shared parser/classifier for DWC2 R1 observer semantic ABI v9.

v9 keeps the v8 binary layout (112-byte header, 80-byte timeout record) but
changes denominator semantics: stop causality is established before candidate
accounting.  Negative-result gates MUST reject v8 because the layouts are
indistinguishable while the candidate counters are not semantically equivalent.
"""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Tuple

MAGIC = 0x424F3152
VERSION = 9
HDR = struct.Struct('<' + 'I' * 28)
REC = struct.Struct('<IHHHHHBBBBBBIIIIIIIQQIIHHHH')
assert HDR.size == 112 and REC.size == 80

# header fields
HDR_NAMES = (
    'magic','version','header_size','record_size','count','lost','next_seq','caps_flags',
    'gsnpsid','ghwcfg2','ghwcfg3','ghwcfg4','reset_generation',
    'setup_cfg0_seen','setup_cfgn_seen','setup_intf_seen',
    'candidate_cfg0_seen','candidate_cfgn_seen','candidate_intf_seen',
    'candidate_delayed_disable_seen','overlap_count','delayed_open_count',
    'delayed_closed_count','causal_sync_count','causal_unattributed_count',
    'snapshot_atomic','candidate_delayed_dequeue_seen','reserved1',
)

REC_NAMES = (
    'seq','tag','flags','w_value','w_index','w_length','bm_request_type','b_request',
    'trigger','ep_index','causal_state','mapping_class','gintsts','dctl','doepctl',
    'doepint','grstctl','gahbcfg','status','setup_cookie','req_dma','req_length',
    'req_actual','num_sgs','num_mapped_sgs','flags2','owner_cpu',
)

EV_TIMEOUT = 1
TRIG_NONE, TRIG_CFG0, TRIG_CFGN, TRIG_INTF = 0, 1, 2, 3
TRIG_NAMES = {0:'NONE',1:'SET_CONFIG_ZERO',2:'SET_CONFIG_NONZERO',3:'SET_INTERFACE'}
CAUSE_NONE, CAUSE_SYNC_OWNER, CAUSE_DELAYED, CAUSE_OVERLAP = 0,1,2,3
CAUSE_NAMES = {0:'NONE',1:'SYNC_OWNER',2:'DELAYED',3:'OVERLAP'}
MAP_NONE, MAP_ZERO, MAP_NOT_CORE, MAP_LINEAR, MAP_SG, MAP_INCONSISTENT_SG, MAP_UNKNOWN = range(7)
MAP_NAMES = {
    0:'NONE',1:'ZERO_LENGTH',2:'NOT_CORE_OWNED',3:'LINEAR',4:'SG',
    5:'INCONSISTENT_SG',6:'UNKNOWN'
}

F_REQ=1<<0; F_HW=1<<1; F_EPENA=1<<2; F_NO_XFC=1<<3; F_EIP=1<<4
F_DISABLE=1<<5; F_DEQUEUE=1<<6; F_NONZERO=1<<7; F_DMA_EN=1<<8; F_BULK=1<<9
F_GOUT_STS=1<<10; F_EP_NAK=1<<11; F_RXFLVL=1<<12; F_AHB_IDLE=1<<13
F_DMAREQ=1<<14; F_GOUT_NOW=1<<15

F2_DMA_MAPPED=1<<0; F2_SG_WAS_MAPPED=1<<1; F2_BOUNCE_ACTIVE=1<<2
F2_CORE_OWNED=1<<3; F2_U_ELIG_LINEAR=1<<4; F2_U_ELIG_SG=1<<5
F2_SG_COUNT_OVERFLOW=1<<6

CAP_DMA=1<<0; CAP_DDMA=1<<1
EPENA=1<<31; EPTYPE_MASK=3<<18; EPTYPE_BULK=2<<18; EP_NAK_STS=1<<17
XFC=1<<0; DCTL_GOUTNAKSTS=1<<3; GINT_GOUTNAKEFF=1<<7; GINT_RXFLVL=1<<4
GRST_AHBIDLE=1<<31; GRST_DMAREQ=1<<30; GAHBCFG_DMA_EN=1<<5
EINPROGRESS = -115

class ParseError(ValueError):
    pass

@dataclass(frozen=True)
class Header:
    magic:int; version:int; header_size:int; record_size:int; count:int; lost:int
    next_seq:int; caps_flags:int; gsnpsid:int; ghwcfg2:int; ghwcfg3:int; ghwcfg4:int
    reset_generation:int; setup_cfg0_seen:int; setup_cfgn_seen:int; setup_intf_seen:int
    candidate_cfg0_seen:int; candidate_cfgn_seen:int; candidate_intf_seen:int
    candidate_delayed_disable_seen:int; overlap_count:int; delayed_open_count:int
    delayed_closed_count:int; causal_sync_count:int; causal_unattributed_count:int
    snapshot_atomic:int; candidate_delayed_dequeue_seen:int; reserved1:int

@dataclass(frozen=True)
class Record:
    seq:int; tag:int; flags:int; w_value:int; w_index:int; w_length:int
    bm_request_type:int; b_request:int; trigger:int; ep_index:int; causal_state:int
    mapping_class:int; gintsts:int; dctl:int; doepctl:int; doepint:int; grstctl:int
    gahbcfg:int; status:int; setup_cookie:int; req_dma:int; req_length:int
    req_actual:int; num_sgs:int; num_mapped_sgs:int; flags2:int; owner_cpu:int

@dataclass(frozen=True)
class RecordAssessment:
    index:int
    integrity:str
    errors:Tuple[str,...]
    r1_state:str
    trigger:str
    cause:str
    caller:str
    mapping:str
    u_state:str
    bounce_active:bool
    seq:int
    setup_cookie:int


def s32(v:int)->int:
    return struct.unpack('<i', struct.pack('<I', v & 0xffffffff))[0]


def parse_bytes(data:bytes, *, require_version:int|None=VERSION)->Tuple[Header,List[Record]]:
    if len(data) < HDR.size:
        raise ParseError('short header')
    hv = HDR.unpack_from(data, 0)
    h = Header(*hv)
    if h.magic != MAGIC:
        raise ParseError(f'bad magic 0x{h.magic:08x}')
    if require_version is not None and h.version != require_version:
        raise ParseError(f'unsupported semantic version {h.version}; require {require_version}')
    if h.header_size != HDR.size or h.record_size != REC.size:
        raise ParseError(f'bad ABI sizes header={h.header_size} record={h.record_size}')
    expected = HDR.size + h.count * REC.size
    if len(data) != expected:
        raise ParseError(f'length mismatch got={len(data)} expected={expected}')
    recs=[]
    off=HDR.size
    for _ in range(h.count):
        recs.append(Record(*REC.unpack_from(data, off)))
        off += REC.size
    return h,recs


def parse_file(path:str|Path, *, require_version:int|None=VERSION):
    p=Path(path); data=p.read_bytes(); h,r=parse_bytes(data,require_version=require_version)
    return h,r,hashlib.sha256(data).hexdigest()


def raw_setup_ok(r:Record)->bool:
    if r.trigger == TRIG_CFG0:
        return (r.bm_request_type,r.b_request,r.w_value,r.w_index,r.w_length)==(0x00,0x09,0,0,0)
    if r.trigger == TRIG_CFGN:
        return r.bm_request_type==0x00 and r.b_request==0x09 and r.w_value!=0 and r.w_index==0 and r.w_length==0
    if r.trigger == TRIG_INTF:
        return r.bm_request_type==0x01 and r.b_request==0x0b and r.w_length==0
    if r.trigger == TRIG_NONE:
        return (r.bm_request_type,r.b_request,r.w_value,r.w_index,r.w_length)==(0,0,0,0,0)
    return False


def _bit(v:int,b:int)->bool:
    return bool(v & b)


def consistency_errors(r:Record)->List[str]:
    e=[]
    if r.tag != EV_TIMEOUT: e.append('tag_not_timeout')
    if r.trigger not in TRIG_NAMES: e.append('unknown_trigger')
    if r.causal_state not in CAUSE_NAMES: e.append('unknown_cause')
    if r.mapping_class not in MAP_NAMES: e.append('unknown_mapping_class')
    if not raw_setup_ok(r): e.append('raw_setup_mismatch')

    checks = [
        (F_EPENA, bool(r.doepctl & EPENA), 'EPENA'),
        (F_NO_XFC, not bool(r.doepint & XFC), 'NO_XFERCOMPL'),
        (F_EIP, s32(r.status)==EINPROGRESS, 'EINPROGRESS'),
        (F_NONZERO, r.req_length!=0, 'NONZERO_LENGTH'),
        (F_DMA_EN, bool(r.gahbcfg & GAHBCFG_DMA_EN), 'DMA_EN'),
        (F_BULK, (r.doepctl & EPTYPE_MASK)==EPTYPE_BULK, 'BULK_OUT'),
        (F_GOUT_STS, bool(r.dctl & DCTL_GOUTNAKSTS), 'GOUTNAK_STS'),
        (F_EP_NAK, bool(r.doepctl & EP_NAK_STS), 'EP_NAK_STS'),
        (F_RXFLVL, bool(r.gintsts & GINT_RXFLVL), 'RXFLVL'),
        (F_AHB_IDLE, bool(r.grstctl & GRST_AHBIDLE), 'AHB_IDLE'),
        (F_DMAREQ, bool(r.grstctl & GRST_DMAREQ), 'DMAREQ'),
        (F_GOUT_NOW, bool(r.gintsts & GINT_GOUTNAKEFF), 'GOUTNAKEFF_NOW'),
    ]
    for bit,want,name in checks:
        if _bit(r.flags,bit) != want: e.append(f'flag_raw_mismatch:{name}')

    callers=int(_bit(r.flags,F_DISABLE))+int(_bit(r.flags,F_DEQUEUE))
    if callers != 1: e.append('caller_bits_not_exactly_one')
    if not _bit(r.flags,F_REQ) and r.seq: e.append('seq_without_req_present')

    if r.causal_state in (CAUSE_SYNC_OWNER,CAUSE_DELAYED,CAUSE_OVERLAP):
        if r.trigger == TRIG_NONE: e.append('causal_without_trigger')
        if r.setup_cookie == 0: e.append('causal_without_cookie')
    elif r.causal_state == CAUSE_NONE:
        if r.trigger != TRIG_NONE or r.setup_cookie != 0:
            e.append('none_cause_with_setup_state')

    f2=r.flags2
    core=_bit(f2,F2_CORE_OWNED); ul=_bit(f2,F2_U_ELIG_LINEAR); us=_bit(f2,F2_U_ELIG_SG)
    dm=_bit(f2,F2_DMA_MAPPED); swm=_bit(f2,F2_SG_WAS_MAPPED); ov=_bit(f2,F2_SG_COUNT_OVERFLOW)
    if ul and us: e.append('both_u_eligibility_bits')
    if (ul or us) and not core: e.append('u_eligible_without_core_owned')

    mc=r.mapping_class
    if mc==MAP_NONE:
        if core or ul or us: e.append('map_none_with_owned_bits')
    elif mc==MAP_ZERO:
        if r.req_length!=0: e.append('zero_map_with_nonzero_length')
        if core or ul or us: e.append('zero_map_with_owned_bits')
    elif mc==MAP_NOT_CORE:
        if not swm: e.append('not_core_without_sg_was_mapped')
        if core or ul or us: e.append('not_core_with_owned_bits')
    elif mc==MAP_LINEAR:
        if r.req_length==0: e.append('linear_zero_length')
        if not (core and ul and dm) or us or swm: e.append('linear_provenance_bits_bad')
        if r.num_mapped_sgs!=0 or r.num_sgs!=0: e.append('linear_with_sg_counts')
        if ov: e.append('linear_with_sg_overflow')
    elif mc==MAP_SG:
        if r.req_length==0: e.append('sg_zero_length')
        if not (core and us) or ul or swm or dm: e.append('sg_provenance_bits_bad')
        if not ov and (r.num_mapped_sgs==0 or r.num_sgs==0): e.append('sg_counts_zero_without_overflow')
    elif mc==MAP_INCONSISTENT_SG:
        if core or ul or us: e.append('inconsistent_sg_with_owned_bits')
        if not ov and not (r.num_mapped_sgs>0 and r.num_sgs==0): e.append('inconsistent_sg_shape_missing')
    elif mc==MAP_UNKNOWN:
        if core or ul or us: e.append('unknown_map_with_owned_bits')
    return e


def base_r1_predicate(r:Record)->bool:
    need=F_REQ|F_HW|F_EPENA|F_NO_XFC|F_EIP|F_NONZERO|F_DMA_EN|F_BULK
    return (
        r.tag==EV_TIMEOUT and (r.flags & need)==need and r.seq!=0 and r.ep_index!=0
        and r.req_length!=0 and (r.doepctl&EPENA)!=0
        and (r.doepctl&EPTYPE_MASK)==EPTYPE_BULK and (r.doepint&XFC)==0
        and s32(r.status)==EINPROGRESS and (r.gahbcfg&GAHBCFG_DMA_EN)!=0
    )


def mapping_u_state(r:Record)->str:
    if r.mapping_class==MAP_LINEAR and not (r.flags2&F2_SG_COUNT_OVERFLOW):
        return 'U_ELIGIBLE_LINEAR_R2_SIMPLE'
    if r.mapping_class==MAP_SG:
        if r.flags2&F2_SG_COUNT_OVERFLOW:
            return 'U_ELIGIBLE_SG_COUNT_TRUNCATED_NOT_R2_READY'
        return 'U_ELIGIBLE_SG_IOVA_VECTOR_NOT_CAPTURED'
    if r.mapping_class==MAP_NOT_CORE: return 'NOT_CORE_OWNED_UNMAP_NOOP'
    if r.mapping_class==MAP_ZERO: return 'ZERO_LENGTH_UNMAP_NOOP'
    if r.mapping_class==MAP_INCONSISTENT_SG: return 'INCONSISTENT_SG_PROVENANCE'
    if r.mapping_class==MAP_UNKNOWN: return 'UNMAP_OWNERSHIP_UNKNOWN'
    return 'NO_LIVE_MAPPING_PROVENANCE'


def assess_record(r:Record,index:int)->RecordAssessment:
    errs=tuple(consistency_errors(r))
    caller='DISABLE' if r.flags&F_DISABLE else ('DEQUEUE' if r.flags&F_DEQUEUE else 'NONE')
    if errs:
        state='INVALID_INCONSISTENT_RECORD'
    elif not base_r1_predicate(r):
        state='TIMEOUT_OBSERVED_POST_TIMEOUT_ACTIVE_NOT_MET'
    elif r.causal_state==CAUSE_SYNC_OWNER:
        state='R1_PROVEN_SYNC'
    elif r.causal_state==CAUSE_DELAYED:
        state='R1_DELAYED_%s_CORRELATED' % caller
    elif r.causal_state==CAUSE_OVERLAP:
        state='TIMEOUT_CAUSAL_OVERLAP'
    else:
        state='TIMEOUT_UNATTRIBUTED'
    return RecordAssessment(
        index=index,integrity='VALID' if not errs else 'INVALID',errors=errs,
        r1_state=state,trigger=TRIG_NAMES.get(r.trigger,'UNKNOWN'),
        cause=CAUSE_NAMES.get(r.causal_state,'UNKNOWN'),caller=caller,
        mapping=MAP_NAMES.get(r.mapping_class,'UNKNOWN'),u_state=mapping_u_state(r),
        bounce_active=bool(r.flags2&F2_BOUNCE_ACTIVE),seq=r.seq,setup_cookie=r.setup_cookie,
    )


def header_errors(h:Header, *, negative_gate:bool=True)->List[str]:
    e=[]
    if h.magic!=MAGIC: e.append('bad_magic')
    if h.version!=VERSION: e.append('wrong_semantic_version')
    if h.header_size!=HDR.size or h.record_size!=REC.size: e.append('abi_size_mismatch')
    if h.reserved1!=0: e.append('reserved1_nonzero')
    if h.delayed_closed_count>h.delayed_open_count: e.append('delayed_close_gt_open')
    if negative_gate and h.snapshot_atomic!=1: e.append('snapshot_not_atomic')
    return e


def target_fingerprint(h:Header)->Tuple[int,int,int,int,int]:
    return (h.caps_flags,h.gsnpsid,h.ghwcfg2,h.ghwcfg3,h.ghwcfg4)


def header_to_dict(h:Header): return asdict(h)
def assessment_to_dict(a:RecordAssessment): return asdict(a)
