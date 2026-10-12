"""Validate native load cadence and cross-check zero-damping axial beam forces."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np


def audit(run):
    meta=json.loads((run/'frequency.json').read_bytes());probe=json.loads((run/'probe.json').read_bytes())
    if not meta['complete'] or not probe['sources_unchanged'] or probe.get('error'):raise ValueError('Incomplete or changed-source capture')
    loads=np.loadtxt(run/'frequency_loads.csv',delimiter=',',skiprows=1)
    positions=np.loadtxt(run/'frequency.csv',delimiter=',',skiprows=1)
    beams=meta['load_beams'];names=meta['nodes'];index={n:i for i,n in enumerate(names)}
    if loads.shape!=(meta['samples'],1+2*len(beams)+3*len(meta['load_nodes'])):raise ValueError('Truncated load capture')
    if not np.isfinite(loads).all() or not np.array_equal(loads[:,0],positions[:,0]):raise ValueError('Load/position timestamps or values invalid')
    records=[];checks=[]
    for i,beam in enumerate(beams):
        stress=loads[:,1+i*2];length=loads[:,2+i*2]
        xyz=[positions[:,2+3*index[beam[n]]:5+3*index[beam[n]]] for n in ('a','b')]
        actual=np.linalg.norm(xyz[1]-xyz[0],axis=1);peak=int(np.argmax(abs(stress)))
        record=dict(beam=beam,peak_stress=float(max(abs(stress))),peak_time_s=float(loads[peak,0]),
            length_position_error_m=float(max(abs(length-actual))),stress_update_fraction=float(np.mean(np.diff(stress)!=0)))
        if beam['beam_type']==0 and beam['damp']==0 and beam['spring']>0:
            elastic=beam['spring']*(length-beam['rest'])
            if max(abs(elastic))>100:
                relative=float(np.sqrt(np.mean((stress-elastic)**2))/max(abs(elastic)))
                record['spring_extension_relative_rms_error']=relative
                if relative>.005 or record['length_position_error_m']>1e-5:raise ValueError('Native axial force disagrees with measured spring extension')
                checks.append(beam['cid'])
        records.append(record)
    if len(checks)<4:raise ValueError('Need four loaded, undamped normal beams to cross-check force units')
    node_force=loads[:,1+2*len(beams):]
    fresh=float(np.mean(np.any(np.diff(node_force,axis=0)!=0,axis=1)))
    if fresh<.8:raise ValueError('Native node forces are held snapshots')
    return dict(scope=__doc__,status='diagnostic_validated',force_unit_check='Native normal-beam stress matches N/m times metres for loaded undamped beams',
        checked_beams=checks,node_force_update_fraction=fresh,beams=records,
        evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in ('frequency.json','frequency.csv','frequency_loads.csv','probe.json')})

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();r=audit(a.run)
    (a.run/'load_audit.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in r.items() if k not in ('beams','evidence_sha256')},indent=2))
