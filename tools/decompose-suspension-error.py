"""Attribute front toe error to measured constraint deviations, not intended travel.

Four-distance wishbone / rigid-upright reconstruction at the same hub height.
Shapley contributions average all intervention orders; these are kinematic
sensitivities, not causal load identification or material validation.
"""
import argparse,hashlib,itertools,json,math,sys
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import Predictor,rigid_fit,angles,angle_error,hub_datum


def reconstruct(p,actual,height,extension,split_arms=False):
    sites=['lower_ball','upper_ball','tie_outer','hub','hub_axis']
    r,t=rigid_fit([p[k] for k in sites],[actual[k] for k in sites])
    distorted={k:(actual[k]-t)@r.T for k in sites}
    mounts=[arm+'_inner_'+end for arm in ('lower','upper') for end in ('front','rear')]+['tie_inner']
    edges=[(arm+'_inner_'+end,arm+'_ball') for arm in ('lower','upper') for end in ('front','rear')]
    rest=[np.linalg.norm(p[b]-p[a]) for a,b in edges]
    measured=[np.linalg.norm(actual[b]-actual[a]) for a,b in edges]
    tie=np.linalg.norm(p['tie_outer']-p['tie_inner'])+extension
    groups=['mounts',*(['lower_arm','upper_arm'] if split_arms else ['arms']),'tie','upright'];count=len(groups)
    results={};seed=np.r_[Rotation.from_matrix(r.T).as_rotvec(),t+p['hub']@r-p['hub']]
    for mask in range(1<<count):
        on={name for i,name in enumerate(groups) if mask&(1<<i)}
        shape=distorted if 'upright' in on else {k:p[k] for k in sites}
        anchors={k:actual[k] if 'mounts' in on else p[k] for k in mounts}
        lengths=[m if ('arms' in on or (a.split('_')[0]+'_arm') in on) else n for (a,b),m,n in zip(edges,measured,rest)]
        target=np.linalg.norm(actual['tie_outer']-actual['tie_inner']) if 'tie' in on else tie
        def pose(x):
            rotation=Rotation.from_rotvec(x[:3]);return {k:p['hub']+rotation.apply(v-p['hub'])+x[3:] for k,v in shape.items()}
        def residual(x):
            q=pose(x)
            return [*[np.linalg.norm(q[b]-anchors[a])-length for (a,b),length in zip(edges,lengths)],
                np.linalg.norm(q['tie_outer']-anchors['tie_inner'])-target,q['hub'][2]-height]
        fit=least_squares(residual,seed,xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=300)
        error=float(max(abs(fit.fun)))
        if not fit.success or error>1e-7:raise ValueError('Constraint reconstruction failed '+str(on)+': '+str(error))
        q=pose(fit.x);axis=q['hub_axis']-q['hub'];axis*=1 if p['hub_axis'][0]>p['hub'][0] else -1
        results[mask]=dict(toe_deg=float(angles(axis)[1]),residual_m=error)
    contributions={}
    for i,name in enumerate(groups):
        total=0.
        for mask in range(1<<count):
            if mask&(1<<i):continue
            size=mask.bit_count();weight=math.factorial(size)*math.factorial(count-1-size)/math.factorial(count)
            total+=weight*float(angle_error(results[mask|(1<<i)]['toe_deg'],results[mask]['toe_deg']))
        contributions[name]=total
    predicted=float(angle_error(results[(1<<count)-1]['toe_deg'],results[0]['toe_deg']))
    if abs(sum(contributions.values())-predicted)>1e-6:raise ValueError('Attribution does not sum to total toe change')
    return dict(contributions_deg=contributions,nominal_toe_deg=results[0]['toe_deg'],reconstructed_toe_deg=results[(1<<count)-1]['toe_deg'],
        reconstructed_error_deg=predicted,maximum_constraint_residual_m=max(r['residual_m'] for r in results.values()),
        arm_lengths_change_mm={a+'--'+b:float((m-n)*1000) for (a,b),m,n in zip(edges,measured,rest)},
        scope='Constraint deviations at fixed measured hub height; no change to authored setup')


def audit(run,split_arms=False):
    files=['build_manifest.json','job.json','frequency.json','frequency.csv','frequency_analysis.json']
    manifest,job,meta=json.loads((run/files[0]).read_bytes()),json.loads((run/files[1]).read_bytes()),json.loads((run/files[2]).read_bytes())
    analysis=json.loads((run/files[4]).read_bytes())
    if analysis.get('qualification_status')!='diagnostic_only':raise ValueError('Validated frequency analysis required')
    if hashlib.sha256((run/'frequency.csv').read_bytes()).hexdigest()!=analysis['evidence_sha256']['frequency.csv']:raise ValueError('Frequency recording changed')
    data=np.loadtxt(run/'frequency.csv',delimiter=',',skiprows=1);names=meta['nodes'];index={n:i for i,n in enumerate(names)}
    world=data[:,2:].reshape(len(data),len(names),3);ids=meta['config']['chassis_nodes'];ci=[index[n] for n in ids]
    original={n:np.array(v['position']) for n,v in manifest['nodes'].items()};ref=np.array([original[n] for n in ids]);weights=[manifest['nodes'][n]['mass_kg'] for n in ids]
    full_fits=None
    if meta['config'].get('full_chassis_registration'):
        from frame_harness.frequency_registration import fits
        files.append('frequency_chassis.csv')
        stats=np.loadtxt(run/'frequency_chassis.csv',delimiter=',',skiprows=1)
        if stats.shape!=(len(data),13) or not np.array_equal(stats[:,0],data[:,0]):raise ValueError('Incomplete chassis statistics')
        full=job['motion_reference']['chassis']
        full_fits=fits([original[n] for n in full],[manifest['nodes'][n]['mass_kg'] for n in full],stats[:,1:])
    predictor=Predictor(manifest);report={}
    for corner in ('FL','FR'):
        time=analysis['channels'][corner+'_toe_error_deg']['peak_time_s'];i=int(np.argmin(abs(data[:,0]-time)))
        r,t=rigid_fit(ref,world[i,ci],weights) if full_fits is None else (full_fits[0][i],full_fits[1][i])
        local={n:(world[i,index[n]]-t)@r.T for n in names}
        mapping=job['motion_reference']['corners'][corner];mechanism=predictor.mechanisms[corner];p=mechanism.p
        if not mechanism.wishbone or mechanism.translating_rack:raise ValueError('Requires equivalent-tie front wishbones')
        actual={k:local[n] for k,n in mapping['points'].items()};axispoints=[local[n] for n in mapping['axis']]
        actual['hub']=hub_datum(p['hub'],[original[n] for n in mapping['axis']],axispoints)
        delta=axispoints[1]-axispoints[0]
        actual['hub_axis']=actual['hub']+delta/np.linalg.norm(delta)*np.linalg.norm(p['hub_axis']-p['hub'])*(1 if p['hub_axis'][0]>p['hub'][0] else -1)
        extension=analysis['peak_toe_context'][corner].get('actuator_extension_m',analysis['ideal_interpolation'][corner]['actuator_extension_m'])
        item=reconstruct(p,actual,actual['hub'][2],extension,split_arms)
        ideal=predictor.solve(corner,float(actual['hub'][2]-p['hub'][2]),extension)
        direction=ideal['hub_axis']-ideal['hub'];direction*=1 if p['hub_axis'][0]>p['hub'][0] else -1
        if abs(float(angle_error(item['nominal_toe_deg'],angles(direction)[1])))>1e-4:raise ValueError('Independent nominal reconstruction differs from CAD predictor')
        if abs(float(angle_error(item['reconstructed_toe_deg'],angles(delta)[1])))>1e-4:raise ValueError('Reconstruction differs from measured upright')
        item.update(time_s=float(data[i,0]),mount_movement_mm={k:((actual[k]-p[k])*1000).tolist() for k in actual if k.endswith(('inner_front','inner_rear')) or k=='tie_inner'})
        report[corner]=item
    return dict(scope=__doc__,corners=report,evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in files})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--split-arms',action='store_true');a=p.parse_args();r=audit(a.run,a.split_arms)
    (a.run/('constraint_attribution_split_arms.json' if a.split_arms else 'constraint_attribution.json')).write_text(json.dumps(r,indent=2),encoding='utf-8');print(json.dumps(r['corners'],indent=2))
