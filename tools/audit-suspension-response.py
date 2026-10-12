"""Audit native spring forces against the declared law, independently of handling.

This checks implementation fidelity, not whether the declared law matches the
real spring. It never changes a build, qualification result or handling limit.
"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def spring_force(wheel,length):
    law=wheel.get('coilover_spring')
    design=wheel['ride_reference']['reference_shock_length_m']
    compression=design-length
    force=wheel['spring_preload_n']+wheel['spring_n_m']*compression
    if law:
        force+=(law['final_rate_n_m']-law['initial_rate_n_m'])*max(0.,compression-law['crossover_compression_m'])
    return float(force)


def audit(run,output):
    names=('build_manifest.json','motion_diagnostics.json','motion_comparison.json','result.json')
    manifest,diagnostics,motion,result=[json.loads((run/n).read_text(encoding='utf-8')) for n in names]
    samples=[s for s in diagnostics['samples'] if s['t']>=4]
    if not samples:raise ValueError('No post-startup native force samples')
    report=dict(scope=__doc__,qualification_changed=False,physical_system_calibrated=False,
        original_status=result['status'],scenario=result['scenario'],run=str(run.resolve()),
        files={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in names},corners={})
    handling={'straight_lateral_drift','straight_heading'}
    checks=motion['checks']
    report['mechanism_screen_failed_checks']=[k for k,v in checks.items() if k not in handling and v is not True]
    report['handling_checks']={k:v for k,v in checks.items() if k in handling}
    report['mechanism_screen_passed']=bool(checks) and not report['mechanism_screen_failed_checks']
    report['limitations']=manifest.get('limitations',[])
    fig,axes=plt.subplots(2,2,figsize=(11,8),layout='constrained')
    for ax,(corner,wheel) in zip(axes.flat,manifest['wheels'].items()):
        rows=[];damping=[]
        expected_rates=[wheel['spring_n_m']]
        if wheel.get('coilover_spring'):expected_rates.append(wheel['coilover_spring']['final_rate_n_m']-wheel['coilover_spring']['initial_rate_n_m'])
        for sample in samples:
            beams=sample.get('coilovers',{}).get(corner)
            if not beams:raise ValueError('Missing coilover force samples: '+corner)
            springs=[b for b in beams if b['spring_n_m']>0]
            if len(springs)!=len(expected_rates) or not np.allclose(sorted(b['spring_n_m'] for b in springs),sorted(expected_rates),rtol=1e-5,atol=1e-5):
                raise ValueError('Native spring branches differ from declared law: '+corner)
            length=float(springs[0]['length_m'])
            if any(abs(b['length_m']-length)>1e-7 for b in beams):raise ValueError('Coilover branches have different eye distances')
            expected=spring_force(wheel,length)
            actual=-sum(b['elastic_force_n'] for b in springs) # native stress is negative in compression
            stop=-sum(b['elastic_force_n'] for b in beams if b['spring_n_m']==0)
            rows.append([length,expected,actual,stop])
            for b in beams:
                if b['damping_ns_m']>0 and 'length_rate_m_s' in b and abs(b['elastic_force_n'])<1.:
                    damping.append([b['length_rate_m_s'],b['damping_force_n'],b['damping_ns_m']])
        data=np.asarray(rows);error=data[:,2]-data[:,1];tolerance=max(5.,.01*float(max(abs(data[:,1]))))
        entry=dict(samples=len(rows),peak_force_error_n=float(max(abs(error))),rms_force_error_n=float(np.sqrt(np.mean(error**2))),
            screening_tolerance_n=tolerance,declared_spring_law_screen_passed=bool(max(abs(error))<=tolerance),
            minimum_eye_length_m=float(min(data[:,0])),maximum_eye_length_m=float(max(data[:,0])),
            peak_stop_force_n=float(max(abs(data[:,3]))),spring_settings_source=wheel.get('coilover_settings_source'),
            damping_scope='Unloaded-stop samples only; native cutoff filtering and sparse sampling prevent dynamic damping qualification.')
        if damping:
            damp=np.asarray(damping);rate=damp[:,0];active=abs(rate)>.002
            entry['damping_samples']=len(damping)
            if np.count_nonzero(active)>=3:
                entry['apparent_damping_n_s_m']=float(rate[active]@damp[active,1]/(rate[active]@rate[active]))
                entry['declared_damping_n_s_m']=float(np.median(damp[:,2]))
        law=wheel.get('coilover_spring');design=wheel['ride_reference']['reference_shock_length_m']
        if law:entry['both_rate_regions_sampled']=bool(min(data[:,0])<design-law['crossover_compression_m']<max(data[:,0]))
        report['corners'][corner]=entry
        order=np.argsort(data[:,0]);ax.plot((design-data[order,0])*1000,data[order,1],label='Declared spring law')
        ax.scatter((design-data[:,0])*1000,data[:,2],s=8,label='Native spring force')
        ax.set(title=corner,xlabel='Compression from ride reference (mm)',ylabel='Spring force (N; compression positive)')
        ax.grid(alpha=.2);ax.legend()
    fig.suptitle('Coilover force fidelity; travel-stop force is reported separately')
    output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output,dpi=150);plt.close(fig)
    output.with_suffix('.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({c:v['peak_force_error_n'] for c,v in report['corners'].items()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();audit(a.run,a.output)
