"""Plot recorded rack targets and motion without modifying native captures."""
import argparse
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

p=argparse.ArgumentParser(description=__doc__);p.add_argument('verification',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
evidence=json.loads(a.verification.read_text());runs=evidence['results']
if evidence['status']!='passed' or len(runs)!=2:raise ValueError('Two passing native sweep recordings are required')
fig,axes=plt.subplots(2,2,figsize=(11,6),layout='constrained');provenance=[]
for row,run in enumerate(runs):
    path=Path(run['directory'])/'rack_motion.json';record=json.loads(path.read_text());samples=record['samples']
    values=np.array([[s[k] for k in ('t','target_m','shift_m','error_m')] for s in samples])
    t,target,shift,error=values.T
    axes[row,0].plot(t,target*1000,color='#e6a130',lw=3,label='Native actuator target')
    axes[row,0].plot(t,shift*1000,color='#175f9e',lw=1.2,label='Measured rack translation')
    axes[row,1].plot(t,error*1000,color='#187960',lw=1.3)
    axes[row,0].set_title(f'±{round(np.ptp(target)*500)} mm sweep');axes[row,1].set_title('Maximum slider-node tracking error')
    axes[row,0].set_ylabel('Translation (mm)');axes[row,1].set_ylabel('Position error (mm)')
    for axis in axes[row]:axis.set_xlabel('Physics time (s)');axis.grid(alpha=.2)
    provenance.append(dict(job_id=record['job_id'],recording=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
axes[0,0].legend(loc='lower left',fontsize=8)
a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output);plt.close(fig)
a.output.with_suffix('.json').write_text(json.dumps(dict(scope='Isolated fixed-housing rack sweep; not full-vehicle acceptance',sources=provenance),indent=2))
