"""Plot every completed acceleration pilot in two immutable vehicle builds.

The sidecar records source files and hashes. This is diagnostic evidence, not
a substitute for the complete repeated native acceptance suite.
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('baseline',type=Path)
p.add_argument('candidate',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args()
read=lambda path:json.loads(path.read_text(encoding='utf-8-sig'))
fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
evidence=[];colors=['#b95028','#168181']
for build,color,label in zip((a.baseline,a.candidate),colors,('Baseline damping','Carcass damping ×4')):
    manifest=read(build/'manifest.json')
    rows=[]
    for path in sorted((build/'tests').glob('*-acceleration')):
        if not (path/'result.json').exists():continue
        job=read(path/'job.json')
        if job.get('diagnostic'):continue
        result=read(path/'result.json')
        if result.get('recording_status')!='completed':continue
        motion=read(path/'motion_comparison.json');samples=motion['samples']
        if job['manifest']['physics_sha256']!=manifest['physics_sha256']:
            raise ValueError('Pilot does not belong to the selected build')
        axes[0].plot([v['t'] for v in samples],[v['lateral_m'] for v in samples],
                     color=color,alpha=.75,lw=1.6,label=label if not rows else None)
        rows.append(dict(run=str(path),status=result['status'],metrics=motion['metrics'],
                         files={name:hashlib.sha256((path/name).read_bytes()).hexdigest()
                                for name in ('job.json','result.json','motion_comparison.json')}))
    if not rows:raise ValueError('No completed normal acceleration pilots in '+str(build))
    evidence.append(dict(build=str(build),physics_sha256=manifest['physics_sha256'],runs=rows))
axes[0].axhspan(-.5,.5,color='#168181',alpha=.07)
for limit in (-.5,.5):axes[0].axhline(limit,color='#727780',ls='--',lw=1)
axes[0].set(xlabel='Simulation time (s)',ylabel='Lateral displacement (m)',title='Unassisted straight acceleration')
axes[0].legend(fontsize=9)
axes[0].text(.02,.03,'Dashed lines: unchanged ±0.50 m limit',transform=axes[0].transAxes,fontsize=9)
metrics=['camber_error_deg','toe_error_deg','hub_path_error_m','mount_error_m']
limits=np.array([2.,2.,.01,.005])
for i,(group,color) in enumerate(zip(evidence,colors)):
    for j,key in enumerate(metrics):
        values=[max(run['metrics'][c+'_peak_'+key] for c in ('FL','FR','RL','RR'))/limits[j]*100 for run in group['runs']]
        axes[1].scatter(np.full(len(values),j+(i-.5)*.22),values,color=color,s=30,alpha=.7)
axes[1].axhline(100,color='#727780',ls='--',lw=1)
axes[1].set(xticks=range(4),xticklabels=['Camber','Toe','Hub path','Mount'],ylabel='Peak error / acceptance limit (%)',
            title='Ideal linkage vs native motion; every pilot',ylim=(0,110))
for axis in axes:axis.grid(alpha=.15)
fig.supxlabel('Each trace/point is an independent pilot. Kinematic errors use measured travel and actuator length.\n'
               'This compares numerical tire settings; physical tire calibration and full acceptance are separate.',fontsize=9)
a.output.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(a.output,dpi=170)
a.output.with_suffix('.json').write_text(json.dumps(dict(scope='All completed normal acceleration pilots present at rendering',builds=evidence),indent=2)+'\n')
