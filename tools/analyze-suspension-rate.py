"""Equal-force rate response and native coilover-law audit; not qualification.

Finite four-second excitation windows contain transients and are not claimed
as steady-state frequency-response functions. Spring force is checked against
the declared law; damping is compared to instantaneous velocity and its driven
harmonic separately because the exported damper has a native low-pass filter.
"""
import argparse, csv, hashlib, importlib.util, json
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('shock_audit',Path(__file__).with_name('audit-shock-settings.py'))
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

def harmonic(t,y,hz):
    phase=2*np.pi*hz*(np.asarray(t)-6.)
    columns=np.column_stack([np.ones(len(t)),np.sin(phase),np.cos(phase)])
    coefficient=np.linalg.lstsq(columns,y,rcond=None)[0]
    return complex(coefficient[1],coefficient[2])

def load(run):
    read=lambda name:json.loads((run/(name+'.json')).read_bytes())
    job,probe,completion,meta,m,compiled=[read(n) for n in ('job','probe','completion','shock_rate','build_manifest','compiled')]
    if (job['scenario']!='suspension_rate' or job['gravity']!=0 or
        compiled['fixed_nodes']!=len(m['chassis_nodes']) or
        completion.get('status')!='completed' or probe.get('completion',{}).get('status')!='completed' or
        probe.get('error') or probe.get('resource_abort') or not probe.get('sources_unchanged') or
        not meta['complete'] or any(x['job_id']!=job['id'] for x in (meta,completion))):raise ValueError('Invalid rate fixture/recording')
    if m!=job['manifest']:raise ValueError('Manifest differs from job')
    source=next((Path(k) for k,v in probe['implementation'].items() if Path(k).name=='manifest.json' and v==probe['manifest_sha256']),None)
    if source is None or hashlib.sha256(source.read_bytes()).hexdigest()!=probe['manifest_sha256'] or json.loads(source.read_bytes())!=m:raise ValueError('Source manifest identity differs')
    groups={};count=0
    with (run/'shock_rate.csv').open() as f:
        for row in csv.DictReader(f):
            count+=1;key=(row['corner'],int(row['beam_cid']))
            groups.setdefault(key,[]).append([float(row[k]) for k in ('physics_s','length_m','velocity_m_s','elastic_n','damping_n','hub_force_n','rest_m')])
    if count!=meta['samples']:raise ValueError('Truncated shock data')
    groups={k:np.array(v) for k,v in groups.items()}
    for (c,cid),v in groups.items():
        if not np.isfinite(v).all() or abs(v[0,0]-.0005)>1e-8 or abs(v[-1,0]-job['duration'])>.051 or max(abs(np.diff(v[:,0])-.0005))>1e-8:
            raise ValueError('Incomplete/nonfinite/nonuniform physics samples')
        e=job['excitation'];t=v[:,0];ramp=np.clip(t/3,0,1);ramp=ramp*ramp*(3-2*ramp)
        expected=e['bias_n'][c]*ramp
        if c==e['corner']:
            mask=(t>=e['start_s'])&(t<e['start_s']+e['duration_s'])
            tau=t[mask]-e['start_s']
            if e.get('kind')=='recovery':
                envelope=np.clip(np.minimum(tau/2,(6-tau)/2),0,1)
                expected[mask]+=e['amplitude_n']*envelope**2*(3-2*envelope)
            else:expected[mask]+=e['amplitude_n']*np.sin(2*np.pi*e['frequency_hz']*tau)
        if not np.allclose(v[:,5],expected,atol=1e-5,rtol=0):raise ValueError('Recorded force differs from commanded waveform')
    results={};history={}
    actual={b['cid']:b for b in compiled['beams']}
    for c,w in m['wheels'].items():
        entries=[(actual[cid],v) for (corner,cid),v in groups.items() if corner==c]
        if len(entries)!=(3 if w.get('coilover_spring') else 2):raise ValueError('Missing coilover beam stream')
        v=entries[0][1];t=v[:,0];mask=(t>=6)&(t<10);pre=(t>=5)&(t<6)
        if any(not np.array_equal(other[:,0],t) or not np.allclose(other[:,1:3],v[:,1:3],rtol=0,atol=1e-9) for _,other in entries):raise ValueError('Asynchronous shock streams')
        x=w['ride_reference']['reference_shock_length_m']-v[:,1];velocity=v[:,2]
        elastic=sum(a[:,3] for b,a in entries if b['spring']>0)
        stop=sum(a[:,3] for b,a in entries if b['spring']==0)
        damping=sum(a[:,4] for _,a in entries);error=elastic-audit.spring_force(w,x)
        if job['excitation'].get('kind')=='recovery':
            loading=(t>=6)&(t<12);recovered=(t>=22)&(t<24)
            results[c]=dict(compression_range_mm=[float(min(x[loading])*1000),float(max(x[loading])*1000)],
                peak_shock_speed_m_s=float(max(abs(velocity))),spring_law_error_peak_n=float(max(abs(error[t>=6]))),
                stop_elastic_peak_n=float(max(abs(stop[loading]))),stop_engaged=bool(max(abs(stop[loading]))>1),
                recovery_shock_speed_rms_m_s=float(np.sqrt(np.mean(velocity[recovered]**2))),
                recovery_length_offset_m=float(np.mean(x[recovered])-np.mean(x[pre])),
                recovery_stop_elastic_peak_n=float(max(abs(stop[recovered]))))
            history[c]=dict(time_s=t[::20].tolist(),compression_mm=(x[::20]*1000).tolist(),stop_elastic_n=stop[::20].tolist(),
                shock_speed_m_s=velocity[::20].tolist())
            continue
        hz=job['excitation']['frequency_hz'];h=harmonic(t[mask],x[mask],hz)
        hv=harmonic(t[mask],velocity[mask],hz);hd=harmonic(t[mask],damping[mask],hz)
        # Do not report a coefficient from quiet-corner numerical noise.
        ratio=hd/(hv*w['damper_ns_m']) if abs(hv)>1e-4 else None
        results[c]=dict(compression_range_mm=[float(min(x[mask])*1000),float(max(x[mask])*1000)],
            compression_harmonic_mm=abs(h)*1000,compression_phase_deg=float(np.degrees(np.angle(h))),
            peak_shock_speed_m_s=float(max(abs(velocity[mask]))),
            pre_excitation_shock_speed_rms_m_s=float(np.sqrt(np.mean(velocity[pre]**2))),
            spring_law_error_peak_n=float(max(abs(error[mask]))),spring_law_error_rms_n=float(np.sqrt(np.mean(error[mask]**2))),
            stop_elastic_peak_n=float(max(abs(stop[mask]))),
            damping_instantaneous_error_rms_n=float(np.sqrt(np.mean((damping[mask]-w['damper_ns_m']*velocity[mask])**2))),
            damping_harmonic_ratio_magnitude=abs(ratio) if ratio is not None else None,
            damping_harmonic_phase_deg=float(np.degrees(np.angle(ratio))) if ratio is not None else None)
        history[c]=dict(time_s=t[mask][::10].tolist(),compression_mm=(x[mask][::10]*1000).tolist(),elastic_n=elastic[mask][::10].tolist(),
            expected_elastic_n=audit.spring_force(w,x[mask][::10]).tolist(),damping_n=damping[mask][::10].tolist())
    vehicle=np.genfromtxt(run/'vehicle.csv',delimiter=',',names=True)
    if not np.isfinite(vehicle['broken']).all() or max(vehicle['broken'])>0:raise ValueError('Broken structure in rate fixture')
    return dict(run=str(run),excitation=job['excitation'],manifest_sha256=probe['manifest_sha256'],corners=results,history=history,
        physics_step_s=.0005,recording_status='completed',qualification_status='not_qualified',
        evidence_sha256={f:hashlib.sha256((run/f).read_bytes()).hexdigest() for f in ('shock_rate.csv','shock_rate.json','job.json','probe.json','compiled.json','completion.json')})

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('runs',nargs='+',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    rows=[load(r) for r in a.runs]
    if len({r['manifest_sha256'] for r in rows})!=1:raise ValueError('Rate sweep requires same vehicle')
    motion={}
    for run in a.runs:
        path=run/'frequency_analysis.json'
        if path.is_file():
            value=json.loads(path.read_bytes())
            if value.get('evidence_sha256',{}).get('frequency.csv')!=hashlib.sha256((run/'frequency.csv').read_bytes()).hexdigest():
                raise ValueError('Stale motion analysis')
            motion[str(run)]=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                corners={c:{k:value['channels'][c+'_toe_error_deg'][k] for k in ('peak','mean','ac_rms')} for c in ('FL','FR')})
    report=dict(scope=__doc__,rates=rows,motion_residuals=motion)
    a.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(10,7),layout='constrained')
    for row in rows:
        c=row['excitation']['corner'];h=row['history'][c];label=str(row['excitation']['frequency_hz'])+' Hz, '+str(row['excitation']['amplitude_n'])+' N'
        axes[0].plot(h['time_s'],h['compression_mm'],label=label)
        axes[1].plot(h['compression_mm'],h['elastic_n'],label=label)
    axes[0].set(xlabel='Physics time (s)',ylabel='Shock compression from ride (mm)')
    axes[1].set(xlabel='Shock compression (mm)',ylabel='Elastic force (N, tension positive)')
    for ax in axes:ax.legend();ax.grid(alpha=.25)
    fig.suptitle('Equal-force suspension rate checks — finite transient windows')
    fig.savefig(a.output.with_suffix('.png'),dpi=140);plt.close(fig)
    print(json.dumps([dict(excitation=r['excitation'],corners=r['corners']) for r in rows],indent=2))

if __name__=='__main__':main()
