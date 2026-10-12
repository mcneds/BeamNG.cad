"""Measure wishbone flex relative to its own measured hinge, excluding travel.

Rigid rotation about the two inboard pivots preserves ball axial coordinate and
radius. Their errors isolate arm deformation from chassis motion and suspension
travel; they are not estimates of the real material stiffness.
"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np


def coordinates(points):
    a,b,p=np.asarray(points,float);axis=b-a;length=np.linalg.norm(axis)
    if length<1e-6:raise ValueError('Collapsed wishbone pivot pair')
    axis/=length;axial=float((p-a)@axis)
    return np.array([axial,np.linalg.norm(p-a-axial*axis),length])


def audit(run):
    paths=[run/'build_manifest.json',run/'motion_diagnostics.json',run/'motion_comparison.json']
    m,raw,comparison=[json.loads(p.read_bytes()) for p in paths]
    records=[]
    for s in raw['samples']:
        if s['t']<4:continue
        row=dict(t=s['t'],members={})
        for corner in ('FL','FR'):
            names=m['wheels'][corner]['hardpoint_nodes']
            for arm in ('upper','lower'):
                ids=[names[arm+'_'+suffix] for suffix in ('inner_front','inner_rear','ball')]
                rest=coordinates([m['nodes'][n]['position'] for n in ids])
                actual=coordinates([s['mechanism_positions'][n] for n in ids])
                row['members'][corner+'_'+arm]=dict(zip(('axial_error_mm','radius_error_mm','pivot_span_error_mm'),(actual-rest)*1000))
        records.append(row)
    if not records:raise ValueError('No active samples')
    peak={name:{key:max(abs(r['members'][name][key]) for r in records) for key in records[0]['members'][name]} for name in records[0]['members']}
    at_toe={}
    for corner in ('FL','FR'):
        s=max((r for r in comparison['samples'] if r['t']>=4),key=lambda r:abs(r['corners'][corner]['toe_error_deg']))
        closest=min(records,key=lambda r:abs(r['t']-s['t']))
        if abs(closest['t']-s['t'])>.001:raise ValueError('Motion and raw samples are not aligned')
        at_toe[corner]=dict(time=s['t'],toe_error_deg=s['corners'][corner]['toe_error_deg'],members=closest['members'])
    return dict(scope=__doc__,run=str(run),files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                peak_errors=peak,at_peak_toe=at_toe,samples=records)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    report=audit(a.run);a.output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report['peak_errors']))
