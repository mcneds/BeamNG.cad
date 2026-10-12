"""Separate sparse upper-arm compliance under transmitted load and inertia.

This is a local moving-pivot diagnostic, not a new target alignment. Native
forces come from a force-balance-validated recording. The local tangent predicts
axial/radial arm distortion; it does not predict contact forces for a new build.
"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np


def analyze(run):
    read=lambda name:json.loads((run/name).read_bytes())
    meta=read('frequency.json');manifest=read('build_manifest.json');compiled=read('compiled.json');balance=read('node_force_balance.json');job=read('job.json');frequency=read('frequency_analysis.json')
    if balance['status']!='force_balance_consistent' or not meta['complete']:raise ValueError('Force-validated complete recording required')
    for name,digest in balance['evidence_sha256'].items():
        if hashlib.sha256((run/name).read_bytes()).hexdigest()!=digest:raise ValueError('Changed force evidence: '+name)
    positions=np.loadtxt(run/'frequency.csv',delimiter=',',skiprows=1);loads=np.loadtxt(run/'frequency_loads.csv',delimiter=',',skiprows=1)
    if not np.array_equal(positions[:,0],loads[:,0]) or not np.isfinite(loads).all():raise ValueError('Unmatched force samples')
    names=meta['nodes'];index={n:i for i,n in enumerate(names)};n=len(names);beam_count=len(meta['load_beams'])
    xyz=positions[:,2:].reshape(-1,n,3);forces=loads[:,1+2*beam_count:].reshape(-1,n,3);reports={}
    for corner in ('FL','FR'):
        hp=manifest['wheels'][corner]['hardpoint_nodes'];a,b,c=[hp['upper_'+key] for key in ('inner_front','ball','inner_rear')]
        reference=np.array([manifest['nodes'][name]['position'] for name in (a,b,c)]);axis=reference[2]-reference[0];axis/=np.linalg.norm(axis)
        offset=reference[1]-reference[0];axial=float(offset@axis);radius=float(np.linalg.norm(offset-axial*axis));mass=compiled['actual_nodes'][b]['mass_kg'];gravity=np.array([0.,0.,job['gravity']])*mass
        legs=[]
        for parent in (a,c):
            selected=[(i,row) for i,row in enumerate(meta['load_beams']) if set((row['a'],row['b']))=={b,parent}]
            if len(selected)!=1:raise ValueError('One measured normal arm leg required')
            i,beam=selected[0]
            if beam['beam_type']!=0:raise ValueError('Normal arm required')
            # Compiled elastic coefficients and reference lengths are independent
            # of the measured force getter used below.
            cid_a,cid_b=[compiled['actual_nodes'][name]['cid'] for name in (b,parent)]
            matching=[row for row in compiled['beams'] if {row['a'],row['b']}=={cid_a,cid_b}]
            if len(matching)!=1:raise ValueError('Unique compiled arm leg required')
            row=matching[0]
            if float(row.get('damp',0))!=0:raise ValueError('Elastic distortion audit requires undamped upper-arm legs')
            legs.append((parent,i,beam,row))
        selected=np.arange(0,len(positions),4)
        peak=int(np.argmin(abs(positions[:,0]-frequency['peak_toe_context'][corner]['time_s'])))
        selected=np.unique(np.append(selected,peak));rows=[]
        for sample in selected:
            pa,pb,pc=[xyz[sample,index[name]] for name in (a,b,c)];axis=pc-pa;axis/=np.linalg.norm(axis)
            delta=pb-pa;radial=delta-axis*(delta@axis);radial/=np.linalg.norm(radial);basis=np.column_stack((axis,radial))
            ideal=pa+axial*axis+radius*radial;stiffness=np.zeros((3,3));internal=np.zeros(3);ideal_force=np.zeros(3)
            for parent,i,beam,row in legs:
                point=xyz[sample,index[parent]];d=pb-point;length=np.linalg.norm(d);direction=d/length
                # Positive beam force is tension in this validated capture.
                internal-=direction*loads[sample,1+2*i]
                k=float(row['spring']);rest=float(row['rest'])
                q=ideal-point;L=np.linalg.norm(q);v=q/L
                ideal_force-=k*(L-rest)*v
                stiffness+=k*(np.outer(v,v)+(1-rest/L)*(np.eye(3)-np.outer(v,v)))
            local=basis.T@stiffness@basis
            if np.linalg.eigvalsh(local).min()<=0:raise ValueError('Invalid local tangent')
            total=forces[sample,index[b]];external=total-internal-gravity
            terms={key:np.linalg.solve(local,basis.T@value) for key,value in dict(transmitted=external,inertia=-total,gravity=gravity,pivot_span=ideal_force).items()}
            observed=basis.T@(pb-ideal);predicted=sum(terms.values())
            rows.append(dict(time_s=float(positions[sample,0]),observed_mm=(observed*1000).tolist(),predicted_mm=(predicted*1000).tolist(),terms_mm={key:(value*1000).tolist() for key,value in terms.items()},transmitted_force_n=float(np.linalg.norm(external)),net_force_n=float(np.linalg.norm(total))))
        measured=np.array([r['observed_mm'] for r in rows]);predicted=np.array([r['predicted_mm'] for r in rows]);peak_row=min(rows,key=lambda r:abs(r['time_s']-positions[peak,0]))
        reports[corner]=dict(node=b,mass_kg=mass,coordinates=['hinge_axis','radial'],relative_distortion_prediction_error=float(np.linalg.norm(measured-predicted)/np.linalg.norm(measured)),at_peak_toe=peak_row,
            distortion_rms_mm={key:np.sqrt(np.mean(np.square([row['terms_mm'][key] for row in rows]),axis=0)).tolist() for key in rows[0]['terms_mm']},samples=len(rows))
    return dict(scope=__doc__,corners=reports,caveats='Transmitted loads are inferred by subtracting measured internal normal forces from independently validated total force. This decomposition is not a prediction of wheel/brake loads after a revision. Local tangent omits finite-deformation remainder; reported mismatch must be checked.',evidence_sha256={name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in ('frequency.csv','frequency_loads.csv','compiled.json','build_manifest.json','node_force_balance.json','frequency_analysis.json')})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();r=analyze(a.run)
    (a.run/'upper_arm_force_response.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
