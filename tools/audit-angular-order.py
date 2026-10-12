"""Compare sealed builds for a torsion-bar ordering-only generator correction."""
import argparse,json,zipfile
from pathlib import Path
import numpy as np


def read(root):
    receipt=json.loads((root/'static_frame_build.json').read_bytes())
    with zipfile.ZipFile(root/receipt['zip_file']) as archive:
        name=next(n for n in archive.namelist() if n.endswith('.jbeam'))
        return next(iter(json.loads(archive.read(name)).values()))


def audit(part):
    nodes={r[0]:np.array(r[1:4]) for r in part['nodes'][1:] if isinstance(r,list)}
    quality=[];bars={}
    for row in part['torsionbars'][1:]:
        if not isinstance(row,list):continue
        a,b,c,d=row[:4]
        key=min((a,b,c,d),(d,b,c,a),(a,c,b,d),(d,c,b,a))
        if key in bars:raise ValueError('Duplicate angular energy')
        bars[key]=row[4]
        pa,pb,pc,pd=[nodes[n] for n in row[:4]];axis=pc-pb
        quality.append(min(float(np.linalg.norm(np.cross(u,axis))/(np.linalg.norm(u)*np.linalg.norm(axis))) for u in (pa-pb,pd-pc)))
    return bars,dict(count=len(quality),minimum_lever_axis_sine=min(quality),
                     below_point_four=sum(q<.4-1e-8 for q in quality))


def compare(before,after):
    a,b=read(before),read(after);aa,qa=audit(a);bb,qb=audit(b)
    shared=set(aa)&set(bb)
    relative={field:max((abs(aa[k][field]-bb[k][field])/max(abs(aa[k][field]),abs(bb[k][field]),1e-12) for k in shared),default=0.) for field in ('spring','damp')}
    return dict(before=str(before),after=str(after),before_geometry=qa,after_geometry=qb,
                identical_nodes=a['nodes']==b['nodes'],identical_wheels=a['pressureWheels']==b['pressureWheels'],
                same_angular_energies=set(aa)==set(bb),maximum_shared_coefficient_relative_change=relative,
                note='Rest-state geometry audit; native impact and steering tests remain required')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('before',type=Path);parser.add_argument('after',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    result=compare(args.before,args.after);args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
