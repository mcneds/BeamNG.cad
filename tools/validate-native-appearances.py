"""Check native CAD samples without SolidWorks or BeamNG; emits usable DAE/material assets."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from prepare_frame import read_stl,write_dae,dae_materials

def validate(folder):
    records=json.loads((folder/'samples.json').read_text());results=[]
    for record in records:
        ident=record['Id'];record['AppearanceGroups']=json.loads((folder/(ident+'.appearance.json')).read_text())
        new=np.asarray(read_stl(folder/record['File'],'X-ZY'));old=np.asarray(read_stl(folder/(ident+'.legacy.stl'),'X-ZY'))
        a,b=new.reshape(-1,3),old.reshape(-1,3)
        error=max(cKDTree(a).query(b)[0].max(),cKDTree(b).query(a)[0].max())
        if error>2e-6:raise ValueError('Appearance export moved CAD mesh points: '+str(error))
        path=folder/(ident+'.dae');write_dae(path,[(record,new)])
        materials=dae_materials(path.read_bytes());(folder/(ident+'.materials.json')).write_text(json.dumps(materials,indent=2))
        expected={tuple(g['Appearance']['BaseColor']) for g in record['AppearanceGroups']}
        actual={tuple(m['Stages'][0]['baseColorFactor']) for m in materials.values()}
        if expected!=actual:raise ValueError('Native CAD colours changed during material packaging')
        results.append(dict(component=record['Component'],body=record['Body'],triangles=len(new),material_count=len(materials),max_vertex_error_m=float(error),colors=list(expected)))
    report=dict(status='passed',samples=results,scope='Native appearance extraction, original mesh coordinates, DAE slots and BeamNG material JSON; live BeamNG rendering not rerun')
    (folder/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);validate(parser.parse_args().folder)
