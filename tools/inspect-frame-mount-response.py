"""Compare local suspension mounting compliance with the independent CAD frame.

Read-only diagnostic. No accepted artifact or test tolerance is changed.
"""
import argparse,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from vehicle_revisions import load_baseline
from frame_harness.build import node_table,beam_table
from frame_harness.calibration import graph_response
from frame_harness.projection import axial_columns
from frame_harness.reference import build_frame,solve_frame
from frame_harness.models import TestScenario

p=argparse.ArgumentParser();p.add_argument('vehicle',type=Path);p.add_argument('audit',type=Path);a=p.parse_args()
_,manifest,contents,_=load_baseline(a.vehicle/'static_frame_build.json')
parts=json.loads(contents['vehicles/'+manifest['model']+'/'+manifest['main_jbeam']]);part=parts[manifest['main_part']]
all_nodes=node_table(part);hinges={corner+'_'+which for corner in ('RL','RR') for which in ('hinge_inner','hinge_outer')}
front={corner+'_'+arm+'_'+which for corner in ('FL','FR') for arm in ('upper','lower') for which in ('inner_front','inner_rear')}
names=[n for n in all_nodes if n in manifest['chassis_nodes'] or n in hinges or n in front]
positions={n:np.array(all_nodes[n]['position']) for n in names};beams=[b for b in beam_table(part) if b['a'] in positions and b['b'] in positions]
ends=np.array([[names.index(b['a']),names.index(b['b'])] for b in beams]);columns,_,_=axial_columns(np.array(list(positions.values())),ends)
springs=np.array([b['spring'] for b in beams])
audit=json.loads(a.audit.read_text());frame=build_frame(audit['sections'])
for corner in ('RL','RR'):
    inner,outer=[corner+'_'+which for which in ('hinge_inner','hinge_outer')]
    for axis in (1,2):
        direction=np.eye(3)[axis]*.5
        scenario=TestScenario('mount',10,0,list(front),[inner,outer],1,load_vectors={inner:direction.tolist(),outer:(-direction).tolist()})
        actual=graph_response(columns,springs,names,scenario)[0]
        expected=solve_frame(frame,positions,scenario,435e6)['compliance_m_n']
        clamped=TestScenario('mount',10,0,list(manifest['chassis_nodes'])+list(front),[inner,outer],1,load_vectors=scenario.load_vectors)
        joint=graph_response(columns,springs,names,clamped)[0]
        print(json.dumps(dict(corner=corner,axis=axis,graph_compliance_m_n=actual,cad_compliance_m_n=expected,
                             joint_only_compliance_m_n=joint,frame_contribution_m_n=actual-joint,ratio=actual/expected)),flush=True)
