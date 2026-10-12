"""Audit native diagnostic clutch traces; does not qualify or retune a vehicle."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(run, start=18.):
    completion=json.loads((run/'completion.json').read_text())
    job=json.loads((run/'job.json').read_text())
    compiled=json.loads((run/'compiled.json').read_text())
    if completion['status']!='completed' or completion['job_id']!=job['id'] or compiled['job_id']!=job['id']:
        raise ValueError('Incomplete recording or mismatched identity')
    if any(abs(completion[k]-.0005)>1e-8 for k in ('physics_dt_min','physics_dt_max')):
        raise ValueError('Unexpected physics timestep')
    with (run/'powertrain.csv').open() as f:
        data=[{k:float(v) for k,v in row.items()} for row in csv.DictReader(f)]
    if not data or any(not math.isfinite(v) for row in data for v in row.values()):
        raise ValueError('Missing/nonfinite powertrain telemetry')
    if any(b['physics_t']<=a['physics_t'] or b['physics_t']-a['physics_t']>.011 for a,b in zip(data,data[1:])):
        raise ValueError('Unordered or incomplete 100 Hz powertrain telemetry')
    if data[-1]['gfx_t']<job['duration']-.1 or data[0]['physics_t']>.011:
        raise ValueError('Truncated powertrain recording')
    data=[row for row in data if row['gfx_t']>=start]
    if len(data)<200:raise ValueError('Insufficient cruise telemetry')
    clutch=compiled['devices'].get('clutch',{})
    if clutch.get('type')!='centrifugalClutch':
        raise ValueError('Trace requires the native centrifugalClutch named clutch')
    slip=[r['clutch_input_av']-r['clutch_output_av'] for r in data]
    target=job['target_speed']
    # This is accumulated virtual torsional displacement, not physical clutch
    # wear or heat. Native compliance remains active at full engagement.
    result=dict(run=str(run),qualified=False,start_s=start,samples=len(data),
        job_id=job['id'],hashes={name:digest(run/name) for name in
            ('job.json','completion.json','compiled.json','powertrain.csv','straight.csv')},
        fixed_cvt_ratio=job.get('fixed_cvt_ratio'),target_speed_m_s=target,
        diagnostic_clutch_override=compiled.get('diagnostic_clutch_override'),
        speed_min_m_s=min(r['speed'] for r in data),speed_max_m_s=max(r['speed'] for r in data),
        speed_rms_error_m_s=math.sqrt(sum((r['speed']-target)**2 for r in data)/len(data)),
        speed_within_5_percent=all(abs(r['speed']-target)<=target*.05 for r in data),
        slip_rms_rad_s=math.sqrt(sum(v*v for v in slip)/len(slip)),
        virtual_twist_min_rad=min(r['clutch_angle'] for r in data),
        virtual_twist_max_rad=max(r['clutch_angle'] for r in data),
        torque_min_nm=min(r['clutch_torque'] for r in data),torque_max_nm=max(r['clutch_torque'] for r in data),
        fully_engaged_fraction=sum(r['clutch_ratio']>=.999 for r in data)/len(data),
        negative_torque_full_throttle_fraction=sum(r['throttle']>=.95 and r['clutch_torque']<0 for r in data)/len(data),
        spring_min_nm_rad=min(r['clutch_spring'] for r in data),spring_max_nm_rad=max(r['clutch_spring'] for r in data),
        damping_min_nm_s_rad=min(r['clutch_damp'] for r in data),
        damping_max_nm_s_rad=max(r['clutch_damp'] for r in data))
    if job.get('adaptive_clutch'):
        base=job['adaptive_clutch'];inverse=1/base['engine_inertia_kg_m2']
        output_inverse=(1/base['effective_inertia_kg_m2']-inverse)/base['maximum_gearing']**2
        errors=[]
        for row in data:
            expected=(2*math.pi*base['frequency_limit_hz'])**2/(2*(inverse+(row['cvt_ratio']*base['rear_reduction'])**2*output_inverse))
            errors.append(abs(row['clutch_spring']/expected-1))
        increase=max(r['energy_after_adjustment']-r['energy_before_adjustment'] for r in data)
        eigen=max(r['compliance_eigenvalue'] for r in data)
        if increase>1e-8 or eigen>base['step_eigenvalue']+1e-9 or max(errors)>1e-8:
            raise ValueError('Adaptive compliance violated passivity, stability or actual-ratio spring budget')
        result['adaptive_compliance']=dict(maximum_energy_increase_j=increase,
            maximum_step_eigenvalue=eigen,maximum_spring_relative_error=max(errors),base_budget=base)
    return result,data


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',action='append',type=Path,required=True)
    p.add_argument('--label',action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if len(a.run)!=len(a.label):p.error('Give one label per run')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(4,1,figsize=(11,10),sharex=True,layout='constrained')
    report=dict(qualified=False,purpose=__doc__,runs=[])
    for run,label in zip(a.run,a.label):
        result,data=summarize(run);result['label']=label;report['runs'].append(result)
        t=[r['gfx_t'] for r in data]
        for ax,key,scale in zip(axes,('speed','clutch_angle','clutch_torque','cvt_ratio'),(3.6,1,1,1)):
            ax.plot(t,[r[key]*scale for r in data],label=label,lw=1)
    for ax,ylabel in zip(axes,('Speed (km/h)','Virtual clutch twist (rad)','Clutch torque (Nm)','CVT ratio')):
        ax.set_ylabel(ylabel);ax.grid(alpha=.25)
    axes[0].axhline(36,color='black',ls=':',lw=1)
    axes[0].legend();axes[-1].set_xlabel('Simulated time (s)')
    fig.suptitle('Clutch/CVT diagnostics: complete native recordings; no qualification')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    fig.savefig(a.output.with_suffix('.png'),dpi=140)
    fig.savefig(a.output.with_suffix('.svg'))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
