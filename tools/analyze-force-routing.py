"""Attribute incident axial forces at chassis hardpoints; not a full force balance.

Torsionbar reactions, contact forces, gravity and excluded L-beams are not in the
source aggregates. Native total force is retained separately. No causal claim
about deformation follows from a force magnitude alone.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def validate_rows(rows,time,node_count,group_count):
    if rows.shape!=(len(time),1+node_count*group_count*3):raise ValueError('Truncated routing capture')
    if not np.isfinite(rows).all() or not np.array_equal(rows[:,0],time):
        raise ValueError('Routing timestamps or values invalid')
    return rows[:,1:].reshape(len(time),node_count,group_count,3)


def check_force(actual,expected):
    scale=max(1.,float(np.max(np.linalg.norm(expected,axis=1))))
    error=float(np.max(np.linalg.norm(actual-expected,axis=1))/scale)
    if error>1e-6:raise ValueError('Routing force does not match independently recorded beam loads')
    return error


def analyze(run):
    files=['frequency.json','frequency.csv','frequency_loads.csv','frequency_routing.csv','probe.json','compiled.json','frequency_analysis.json']
    meta=json.loads((run/files[0]).read_bytes());probe=json.loads((run/'probe.json').read_bytes())
    if not meta['complete'] or not probe['sources_unchanged'] or probe.get('error') or probe.get('resource_abort') or probe.get('completion',{}).get('status')!='completed':
        raise ValueError('Incomplete or invalid native recording')
    if meta['job_id']!=probe['completion']['job_id']:raise ValueError('Routing job identity mismatch')
    positions=np.loadtxt(run/'frequency.csv',delimiter=',',skiprows=1)
    loads=np.loadtxt(run/'frequency_loads.csv',delimiter=',',skiprows=1)
    rows=np.loadtxt(run/'frequency_routing.csv',delimiter=',',skiprows=1)
    if len(positions)!=meta['samples'] or not np.isfinite(positions).all():raise ValueError('Invalid position capture')
    if loads.shape!=(len(positions),1+2*len(meta['load_beams'])+3*len(meta['load_nodes'])) or not np.isfinite(loads).all() or not np.array_equal(loads[:,0],positions[:,0]):
        raise ValueError('Invalid independent beam-load capture')
    names=meta['routing_nodes'];groups=meta['routing_groups'];forces=validate_rows(rows,positions[:,0],len(names),len(groups))
    compiled=json.loads((run/'compiled.json').read_bytes())
    actual=compiled['actual_nodes'];by_cid={v['cid']:n for n,v in actual.items()}
    indices={n:i for i,n in enumerate(meta['nodes'])};load_index={v['cid']:i for i,v in enumerate(meta['load_beams'])}
    witnesses=[]
    for i,name in enumerate(names):
        for g,group in enumerate(groups):
            if group not in ('wishbone','steering','coilover'):continue
            incident=[(b,e) for b in meta['routing_beams'] for e in b['ends'] if e['node']==i+1 and e['group']==g+1]
            if not incident or any(b['cid'] not in load_index for b,e in incident):continue
            expected=np.zeros((len(rows),3))
            for b,e in incident:
                ia,ib=[indices[by_cid[b[k]]] for k in ('a','b')]
                delta=positions[:,2+ib*3:5+ib*3]-positions[:,2+ia*3:5+ia*3]
                direction=delta/np.linalg.norm(delta,axis=1)[:,None]
                expected+=direction*loads[:,1+2*load_index[b['cid']],None]*e['sign']
            witnesses.append(dict(node=name,group=group,relative_error=check_force(forces[:,i,g],expected)))
    if len(witnesses)<8:raise ValueError('Insufficient independent routing-force witnesses')
    analysis=json.loads((run/'frequency_analysis.json').read_bytes());corners={}
    for corner in ('FL','FR'):
        t=analysis['channels'][corner+'_toe_error_deg']['peak_time_s'];index=int(np.argmin(abs(rows[:,0]-t)))
        corners[corner]=dict(time_s=float(rows[index,0]),forces_n={name:{group:forces[index,i,g].tolist() for g,group in enumerate(groups)} for i,name in enumerate(names)})
    stats={name:{group:dict(peak_norm_n=float(np.max(np.linalg.norm(forces[:,i,g],axis=1))),
                             rms_norm_n=float(np.sqrt(np.mean(np.sum(forces[:,i,g]**2,axis=1)))))
                 for g,group in enumerate(groups)} for i,name in enumerate(names)}
    return dict(scope=__doc__,status='diagnostic_validated',witnesses=witnesses,samples=len(rows),nodes=names,groups=groups,
        statistics=stats,at_peak_toe=corners,excluded_lbeams=meta.get('routing_excluded_lbeams',[]),
        evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in files})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();r=analyze(a.run)
    (a.run/'force_routing_analysis.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=r['status'],samples=r['samples'],witnesses=len(r['witnesses']),rms_forces_n={n:{g:round(v['rms_norm_n'],1) for g,v in s.items()} for n,s in r['statistics'].items()}),indent=2))
