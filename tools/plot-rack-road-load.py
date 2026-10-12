"""Plot recorded steering targets and geometric error without changing qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('runs',type=Path,nargs='+')
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();evidence=[]
fig,axes=plt.subplots(2,len(a.runs),figsize=(6*len(a.runs),7),squeeze=False,layout='constrained')
for col,run in enumerate(a.runs):
    files={n:run/n for n in ('motion_comparison.json','build_manifest.json','result.json')}
    data={n:json.loads(f.read_text()) for n,f in files.items()}
    motion=data['motion_comparison.json'];manifest=data['build_manifest.json'];result=data['result.json']
    samples=motion['samples'];t=[s['t'] for s in samples]
    target=[s['corners']['FL']['actuator_extension_m']*1000 for s in samples]
    axes[0,col].plot(t,target,color='black',linestyle='--',label='Native hydro target')
    for corner,color in (('FL','#2468aa'),('FR','#b45720')):
        rest=np.array(manifest['template_definition']['hardpoints'][corner]['tie_inner'])
        axis=np.array(manifest['steering_contract']['axis'])
        measured=[float((np.array(s['corners'][corner]['actual']['tie_inner'])-rest)@axis)*1000 for s in samples]
        axes[0,col].plot(t,measured,color=color,label=corner+' measured rack end')
        axes[1,col].plot(t,[s['corners'][corner]['toe_error_deg'] for s in samples],color=color,label=corner)
    limit=motion['limits']['toe_error_deg']
    for sign in (-1,1):axes[1,col].axhline(sign*limit,color='#b52b32',linestyle=':',label='Acceptance limit' if sign==1 else None)
    speed=manifest['steering_contract'].get('speed_m_s')
    axes[0,col].set_title(run.parent.parent.name+' · '+result['scenario'].replace('_',' ')+' | '+result['status']+'\n'+
        ('rack speed '+str(speed)+' m/s' if speed is not None else 'previous relative hydro rate: 2/s'))
    axes[0,col].set_ylabel('Rack travel in chassis frame (mm)')
    axes[1,col].set_ylabel('Measured − ideal wheel toe (degrees)')
    for row in (0,1):
        axes[row,col].set_xlabel('Recorded physics time (s)');axes[row,col].grid(alpha=.2);axes[row,col].legend(fontsize=8)
    evidence.append(dict(run=str(run.resolve()),status=result['status'],
        files={n:hashlib.sha256(f.read_bytes()).hexdigest() for n,f in files.items()}))
fig.suptitle('Native road-load recording · unchanged 2° toe criterion\nIdeal linkage uses recorded actuator target, not measured rack position',fontsize=12)
a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output);plt.close(fig)
a.output.with_suffix('.json').write_text(json.dumps(dict(scope=__doc__,sources=evidence),indent=2)+'\n')
