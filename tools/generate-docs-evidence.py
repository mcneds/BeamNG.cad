"""Export selected calibration and mate-compiler evidence, with no machine paths."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from frame_harness.build import node_table,beam_table
from frame_harness.calibration import load_part,graph_identity
from frame_harness.projection import axial_columns
from frame_harness.generation import scenario
from joint_authoring import classify

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(name,data):(ROOT/'website/src/data'/name).write_text(json.dumps(data,indent=2,allow_nan=False))

def calibration(folder):
    folder=Path(folder);meta=json.loads((folder/'calibration.json').read_text());report=json.loads((folder/'report.json').read_text())
    raw=load_part(folder.parent.parent/'source/mochi_raw.jbeam');fitted=load_part(folder/'mochi.jbeam')
    assert graph_identity(raw)==graph_identity(fitted),'Calibration must preserve topology'
    nodes=node_table(fitted);names=list(nodes);positions=np.array([nodes[n]['position'] for n in names])
    beams=beam_table(fitted);endpoints=np.array([[names.index(e['a']),names.index(e['b'])] for e in beams])
    columns,_,_=axial_columns(positions,endpoints)
    cases=[]
    for name in ['flex','torsion']:
        fixture=scenario(meta['reference_config'],name);load=np.zeros(3*len(names))
        for n,v in fixture.resolved_load_vectors().items():load[3*names.index(n):3*names.index(n)+3]=v
        free=np.array([3*i+j for i,n in enumerate(names) if n not in fixture.fixed_nodes for j in range(3)])
        samples=[]
        for label,part in [('Initial graph',raw),('Fitted graph',fitted)]:
            springs=np.array([e['spring'] for e in beam_table(part)])
            u=np.zeros_like(load);a=columns[free];u[free]=np.linalg.solve((a*springs)@a.T,load[free])
            samples.append(dict(label=label,compliance=float(load@u),displacements=u.reshape(-1,3).tolist()))
        expected=report['responses'][name]['compliance_m_n']
        assert np.isclose(samples[-1]['compliance'],expected,rtol=1e-6),'Extracted response differs from retained report'
        cases.append(dict(id=name,target=report['responses'][name]['reference']['compliance_m_n'],samples=samples,
                          fixed=[names.index(n) for n in fixture.fixed_nodes],loads=[[names.index(n),v] for n,v in fixture.resolved_load_vectors().items()]))
    result=dict(label='Retained Mochi frame calibration · changed-generation regression',date='Extracted '+datetime.now(timezone.utc).date().isoformat(),
                positions=positions.tolist(),names=names,edges=endpoints.tolist(),masses=[nodes[n]['mass'] for n in names],cases=cases,
                massKg=report['mass']['actual_mass_kg'],frequencyHz=report['highest_linear_mode_hz'],offlineAccepted=report['offline_accepted'],
                sourceHashes={n:sha(folder/n) for n in ['report.json','calibration.json','mochi.jbeam']},
                rawGraphSha256=sha(folder.parent.parent/'source/mochi_raw.jbeam'),
                note='Historical offline linear response. Not current-vehicle acceptance or measured crash response.')
    write('frame-tuning.json',result)

def mates(project):
    project=Path(project);d=json.loads(project.read_text(encoding='utf-8-sig'));w=d['JointWorkspace']
    joint=next(j for j in w['Joints'] if j.get('Kind')=='revolute' and len(j.get('MateIds',[]))==2)
    records=[m for m in w['Mates'] if m['Id'] in joint['MateIds']]
    concentric=next(m for m in records if m['Type'].upper()=='CONCENTRIC')
    coincident=next(m for m in records if m['Type'].upper()=='COINCIDENT')
    variants=[('axis','Concentric axis',[concentric]),('hinge','Axis + seating plane',[concentric,coincident]),('slider','Axis + locked rotation',[concentric|{'LockRotation':True}]),('fixed','Plane + locked axis',[concentric|{'LockRotation':True},coincident])]
    cases=[]
    for key,label,ms in variants:
        trace={}
        def capture(frame,event,arg):
            if frame.f_code is classify.__code__ and event=='return':
                trace.update(matrix=frame.f_locals['matrix'].tolist(),free=frame.f_locals['free'].tolist())
        sys.setprofile(capture)
        try: result=classify(copy.deepcopy(ms))
        finally:sys.setprofile(None)
        cases.append(dict(id=key,label=label,kind=result['Kind'],dof=result['DegreesOfFreedom'],matrix=trace['matrix'],free=trace['free'],
                          center=result['Center'],axis=result['Axis'],hypothetical=key in ('slider','fixed')))
    geometries=[dict(name=m['Name'],type=m['Type'],entities=[{k:e[k] for k in ['Kind','Point','Axis'] if k in e} for e in m['Entities']]) for m in records]
    write('mate-compilation.json',dict(label=joint['Name'],sourceSha256=sha(project),compilerSha256=sha(ROOT/'beamng.cad/FramePipeline/joint_authoring.py'),
          geometry=geometries,cases=cases,note='Captured native mate geometry. Locked-rotation alternatives are explicit counterfactuals evaluated by the same compiler.'))

def preview():
    folder=ROOT/'website/public/assets/wrapping';cad=json.loads((folder/'cad.json').read_text());proxy=json.loads((folder/'a7-o100.json').read_text())['proxy']
    allp=cad['positions'];lo=[min(p[a] for p in allp) for a in [1,2]];hi=[max(p[a] for p in allp) for a in [1,2]]
    scale=min(340/(hi[0]-lo[0]),220/(hi[1]-lo[1]))
    paths=[]
    for offset,data,col in [(25,cad,'#b3c4d3'),(425,proxy,'#84d9df')]:
        def xy(i):p=data['positions'][i];return f'{offset+(p[1]-lo[0])*scale:.1f},{265-(p[2]-lo[1])*scale:.1f}'
        projected=sorted({tuple(sorted([xy(a),xy(b)])) for a,b in data['edges'] if xy(a)!=xy(b)})
        paths.append(f'<path d="'+''.join(f'M{a}L{b}' for a,b in projected)+f'" fill="none" stroke="{col}" stroke-width=".6" opacity=".65"/>')
    (folder/'preview.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 320"><rect width="800" height="320" fill="#111923"/><g fill="#e6eef5" font-family="sans-serif" font-size="18"><text x="25" y="32">CAD frame</text><text x="425" y="32">CGAL pruning proxy</text></g>'+''.join(paths)+'</svg>')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--calibration',required=True);p.add_argument('--project',required=True);args=p.parse_args()
    calibration(args.calibration);mates(args.project);preview();print('Exported checked calibration responses, native mate compiler cases and real-geometry preview.')
