"""Diagnostic only: isolate a mount patch with its surrounding frame held fixed."""
import argparse,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from frame_harness.build import node_table,beam_table
p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);a=p.parse_args()
m=json.loads(a.manifest.read_text());part=next(iter(json.loads((a.manifest.parent/m['vehicle_directory']/m['main_jbeam']).read_text()).values()))
nodes=node_table(part);beams=beam_table(part);results=[]
for name,patch in part['cadMountPatches'].items():
    parents=patch['parents'];point=np.array(patch['position']);k=np.zeros((12,12))
    def add(aa,bb,pa,pb,spring):
        d=pb-pa;d/=np.linalg.norm(d);col=np.zeros(12)
        if aa is not None:col[aa*3:aa*3+3]=d
        if bb is not None:col[bb*3:bb*3+3]=-d
        k[:]+=spring*np.outer(col,col)
    for beam in beams:
        aa,bb=beam['a'],beam['b']
        if aa not in parents and bb not in parents:continue
        if (aa not in parents and aa not in m['chassis_nodes']) or (bb not in parents and bb not in m['chassis_nodes']):continue
        add(parents.index(aa) if aa in parents else None,parents.index(bb) if bb in parents else None,
            np.array(nodes[aa]['position']),np.array(nodes[bb]['position']),beam['spring'])
    for i,n in enumerate(parents):add(i,3,np.array(nodes[n]['position']),point,180000)
    compliance=np.linalg.inv(k)[9:,9:]
    results.append(dict(mount=name,vertical_mm_per_100n=compliance[2,2]*100000,
                        weakest_mm_per_100n=np.linalg.eigvalsh(compliance)[-1]*100000))
for row in sorted(results,key=lambda r:r['weakest_mm_per_100n'],reverse=True):print(json.dumps(row))
