"""Compare CAD motion-error spectra with wheel rotation across sealed speed holds.

Rotation orders describe association, not causality or a measured transfer function.
"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np


def read_run(run):
    read=lambda name:json.loads((run/name).read_bytes())
    report=read('frequency_analysis.json');meta=read('frequency.json')
    wheels=read('frequency_wheels.json');job=read('job.json');probe=read('probe.json')
    if job['scenario']!='steady_speed' or not probe['sources_unchanged'] or probe.get('error'):
        raise ValueError('Unchanged steady-speed recording required')
    for name,digest in report['evidence_sha256'].items():
        if hashlib.sha256((run/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Analysis evidence changed: '+name)
    if not wheels['complete'] or wheels['job_id']!=job['id'] or wheels['samples']!=report['samples'] or not meta['complete']:
        raise ValueError('Incomplete or mismatched wheel capture')
    if wheels['names']!=['FL','FR','RL','RR']:raise ValueError('Wheel order differs')
    data=np.genfromtxt(run/'frequency_wheels.csv',delimiter=',',names=True)
    positions=np.loadtxt(run/'frequency.csv',delimiter=',',skiprows=1,usecols=0)
    if len(data)!=wheels['samples'] or not np.array_equal(data['physics_s'],positions) or not np.isfinite(np.array(data.tolist())).all():
        raise ValueError('Nonfinite or asynchronous wheel data')
    corners={}
    for corner in ('FL','FR'):
        spin=np.abs(data[corner+'_angularVelocity'])/(2*np.pi);mean=float(spin.mean())
        if mean<=0:raise ValueError('Stationary wheel is not a speed comparison')
        spectrum=report['channels'][corner+'_toe_error_deg']
        corners[corner]=dict(wheel_rotation_hz=mean,wheel_rotation_range_hz=[float(spin.min()),float(spin.max())],
            toe_error_mean_deg=spectrum['mean'],toe_error_ac_rms_deg=spectrum['ac_rms'],toe_error_peak_deg=spectrum['peak'],
            spectral_peaks=[dict(**p,mean_rotation_order=p['hz']/mean) for p in spectrum['peaks']],
            bands_rms_deg=spectrum['bands_rms'],frequency_hz=spectrum['frequency_hz'],density=spectrum['density'])
    files=['frequency_analysis.json','frequency_wheels.csv','frequency_wheels.json','job.json','probe.json']
    return dict(run=str(run),manifest_sha256=probe['manifest_sha256'],target_speed_m_s=job['steady_speed']['target_m_s'],
                samples=report['samples'],corners=corners,evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in files})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('runs',type=Path,nargs='+');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    runs=sorted([read_run(r) for r in a.runs],key=lambda r:r['target_speed_m_s'])
    if len({r['manifest_sha256'] for r in runs})!=1:raise ValueError('Comparison requires the same sealed build')
    if len({r['target_speed_m_s'] for r in runs})!=len(runs):raise ValueError('Duplicate speed; analyze repeats separately')
    result=dict(scope=__doc__,qualification_status='diagnostic_only',runs=runs,
                analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4),sharey=True)
    for ax,corner in zip(axes,('FL','FR')):
        for r in runs:
            c=r['corners'][corner];ax.semilogy(c['frequency_hz'],np.maximum(c['density'],1e-14),label=f"{r['target_speed_m_s']*3.6:.0f} km/h")
        ax.set(xlim=(0,300),ylim=(1e-10,.1),title=corner+' toe error relative to CAD motion',xlabel='Frequency (Hz)');ax.grid(alpha=.25);ax.legend()
    axes[0].set_ylabel('Power density (degree squared / Hz)')
    fig.suptitle('2 kHz native recordings; 40–42 s speed hold; unchanged build')
    fig.tight_layout();fig.savefig(a.output.with_suffix('.png'),dpi=160);plt.close(fig)
    print(json.dumps([dict(speed_kmh=r['target_speed_m_s']*3.6,FR={k:v for k,v in r['corners']['FR'].items() if k not in ('frequency_hz','density')}) for r in runs],indent=2))


if __name__=='__main__':main()
