"""Isolated one-factor tire-resolution or damper-filter experiment; not qualification.

Ray refinement preserves ring mass and analytical inertia, but does not assert
carcass stiffness equivalence. Keep such trials separate from a production fix.
"""
import argparse,copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from vehicle_revisions import load_baseline,canonical,package_revision

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('--output',type=Path,required=True)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--rays',type=int,choices=[16,20,24,32])
    group.add_argument('--damper-cutoff',type=float,choices=[0.,100.,500.])
    a=p.parse_args();record,m,contents,snapshot=load_baseline(a.receipt)
    project=json.loads((a.receipt.parent/'project.snapshot.json').read_bytes())
    name='vehicles/'+m['model']+'/'+m['main_jbeam'];parts=json.loads(contents[name]);part=parts[m['main_part']]
    changes={}
    if a.rays:
        for row in part['pressureWheels'][1:]:
            if not isinstance(row,list):continue
            o=row[-1];old=copy.deepcopy(o);factor=o['numRays']/a.rays
            o.update(numRays=a.rays,nodeWeight=o['nodeWeight']*factor,hubNodeWeight=o['hubNodeWeight']*factor)
            for key in ('tread_nodes','hub_nodes','reinforcement_l_beams'):m['wheels'][row[0]]['tire_contract'][key]=2*a.rays
            changes[row[0]]=dict(before=old,after=copy.deepcopy(o))
    else:
        for corner,w in m['wheels'].items():
            pair={w['nodes']['shock_top'],w['nodes']['shock_bottom']}
            rows=[r for r in part['beams'][1:] if isinstance(r,list) and set(r[:2])==pair and r[-1].get('beamType')=='|BOUNDED' and r[-1].get('beamSpring')==0]
            if len(rows)!=1:raise ValueError('Ambiguous damper '+corner)
            o=rows[0][-1];changes[corner]=dict(before=copy.deepcopy(o));o['dampCutoffHz']=a.damper_cutoff;changes[corner]['after']=copy.deepcopy(o)
    contents[name]=canonical(parts)
    m.pop('verification',None);m.pop('physical_evidence',None)
    m['low_speed_diagnostic']=dict(scope=__doc__,changes=changes)
    m['limitations'].append(__doc__)
    provenance={key:(a.receipt.parent/key).read_bytes() for key in record.get('component_provenance_sha256',{})}
    provenance.update({'low-speed/changes.json':canonical(changes),'low-speed/revision.py':Path(__file__).read_bytes(),'low-speed/parent-receipt.json':a.receipt.read_bytes()})
    if load_baseline(a.receipt)[3]!=snapshot:raise ValueError('Baseline changed')
    package_revision(a.output,project,m,contents,provenance,a.receipt,'Low-speed diagnostic only; unqualified')
    print(a.output/'manifest.json',flush=True)

if __name__=='__main__':main()
