"""Check carrier force laws at auxiliary nodes with no external constraint.

Native normal-beam forces are measured; torsion forces are independently
reconstructed from recorded position/velocity and compiled coefficients. This
tests the deployed carrier model before using it to predict compliance.
"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np


def angle(p):
    a,b,c,d=np.moveaxis(p,-2,0);axis=c-b;axis=axis/np.linalg.norm(axis,axis=-1)[...,None]
    left=a-b;right=d-c;left-=axis*np.sum(left*axis,axis=-1)[...,None];right-=axis*np.sum(right*axis,axis=-1)[...,None]
    return np.arctan2(np.sum(axis*np.cross(left,right),axis=-1),np.sum(left*right,axis=-1))


def gradient(p):
    h=np.maximum(np.linalg.norm(np.ptp(p,axis=-2),axis=-1)*1e-6,1e-8);result=np.zeros_like(p)
    for i in range(4):
        for j in range(3):
            plus=p.copy();minus=p.copy();plus[...,i,j]+=h;minus[...,i,j]-=h
            delta=angle(plus)-angle(minus);result[...,i,j]=np.arctan2(np.sin(delta),np.cos(delta))/(2*h)
    return result


def audit(run):
    read=lambda n:json.loads((run/n).read_bytes())
    m=read('build_manifest.json');meta=read('frequency.json');compiled=read('compiled.json');balance=read('node_force_balance.json');job=read('job.json')
    if balance['status']!='force_balance_consistent' or not meta['complete'] or not meta['config'].get('complete_front_carriers'):raise ValueError('Complete, force-validated carrier recording required')
    for name,expected in balance['evidence_sha256'].items():
        if hashlib.sha256((run/name).read_bytes()).hexdigest()!=expected:raise ValueError('Force-balance input changed: '+name)
    pos=np.loadtxt(run/'frequency.csv',delimiter=',',skiprows=1);vel=np.loadtxt(run/'frequency_velocities.csv',delimiter=',',skiprows=1);loads=np.loadtxt(run/'frequency_loads.csv',delimiter=',',skiprows=1)
    if not np.array_equal(pos[:,0],loads[:,0]) or not np.array_equal(pos[:,0],vel[:,0]):raise ValueError('Unmatched positions/forces/velocities')
    selected=np.arange(0,len(pos),4)
    if len(selected)<400:raise ValueError('At least 0.8 seconds of physics samples required')
    names=meta['nodes'];index={n:i for i,n in enumerate(names)};n=len(names)
    xyz=pos[selected,2:].reshape(-1,n,3);velocity=vel[selected,1:].reshape(-1,n,3)
    f=loads[selected,1+2*len(meta['load_beams']):].reshape(-1,n,3)
    bycid={v['cid']:name for name,v in compiled['actual_nodes'].items()};reports={}
    reference={name:np.array(v['position']) for name,v in m['nodes'].items()}
    for owner,role in m['component_roles'].items():
        if role not in ('fl_upright','fr_upright'):continue
        group=set(m['mass_allocations'][owner]);owned=sorted(group);gi={name:i for i,name in enumerate(owned)}
        if not group<=set(names):raise ValueError('Carrier recording incomplete')
        external=set()
        for beam in compiled['beams']:
            a,b=bycid.get(beam['a']),bycid.get(beam['b'])
            if a in group and b not in group:external.add(a)
            if b in group and a not in group:external.add(b)
        for row in compiled['torsionbars']:
            if not set(row[:4])<=group:external.update(set(row[:4])&group)
        for wheel in m['wheels'].values():external.update(set(wheel['tire_contract']['axle_nodes']+[wheel['brake_reaction_node']])&group)
        witnesses=sorted(group-external)
        if not witnesses:raise ValueError('No isolated carrier witnesses')
        normal=np.zeros((len(selected),len(group),3));torsion=normal.copy();damping=normal.copy()
        for i,beam in enumerate(meta['load_beams']):
            a,b=beam['a'],beam['b']
            if a not in group or b not in group:continue
            if beam['beam_type']!=0:raise ValueError('Witness has unmodelled beam type')
            delta=xyz[:,index[b]]-xyz[:,index[a]];force=delta/np.linalg.norm(delta,axis=1)[:,None]*loads[selected,1+2*i,None]
            normal[:,gi[a]]+=force;normal[:,gi[b]]-=force
        bars=[r for r in compiled['torsionbars'] if set(r[:4])<=group]
        for row in bars:
            ids=[index[name] for name in row[:4]];points=xyz[:,ids];g=gradient(points);delta=angle(points)-angle(np.array([reference[name] for name in row[:4]]));delta=np.arctan2(np.sin(delta),np.cos(delta))
            elastic=-row[4]['spring']*delta[:,None,None]*g
            rate=np.sum(g*velocity[:,ids],axis=(1,2));damped=-row[4]['damp']*rate[:,None,None]*g
            for i,name in enumerate(row[:4]):torsion[:,gi[name]]+=elastic[:,i];damping[:,gi[name]]+=damped[:,i]
        witness_reports=[]
        for name in witnesses:
            mass=compiled['actual_nodes'][name]['mass_kg'];actual=f[:,index[name]];gravity=mass*np.array([0.,0.,job['gravity']])
            predicted=normal[:,gi[name]]+torsion[:,gi[name]]+damping[:,gi[name]]+gravity
            denom=max(float(np.linalg.norm(actual-gravity)),1e-12)
            witness_reports.append(dict(name=name,mass_kg=mass,relative_internal_force_error=float(np.linalg.norm(actual-predicted)/denom),
                error_rms_n=float(np.sqrt(np.mean(np.sum((actual-predicted)**2,axis=1)))),
                normal_rms_n=float(np.sqrt(np.mean(np.sum(normal[:,gi[name]]**2,axis=1)))),
                torsion_elastic_rms_n=float(np.sqrt(np.mean(np.sum(torsion[:,gi[name]]**2,axis=1)))),
                torsion_damping_rms_n=float(np.sqrt(np.mean(np.sum(damping[:,gi[name]]**2,axis=1))))))
        reports[role]=dict(torsionbars=len(bars),witnesses=witness_reports,excluded_external_nodes=sorted(external))
    return dict(scope=__doc__,samples=len(selected),window_s=[float(pos[selected[0],0]),float(pos[selected[-1],0])],carriers=reports,
        caveats='Reference torsion angles use authored positions. Native normal forces are measured, not fitted. Unmodelled aerodynamic forces and native angular damping limits may contribute residuals. No qualification threshold is changed.',
        evidence_sha256={name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in ('frequency.csv','frequency_loads.csv','frequency_velocities.csv','compiled.json','build_manifest.json','node_force_balance.json')})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();r=audit(a.run)
    (a.run/'carrier_internal_forces.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r['carriers'],indent=2))
