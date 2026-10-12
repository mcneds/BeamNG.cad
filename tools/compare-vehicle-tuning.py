"""Plot recorded alignment, attachment motion and drift across generated builds."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p=argparse.ArgumentParser()
p.add_argument('builds',type=Path,nargs='+')
p.add_argument('--scenario',default='acceleration')
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
for build in a.builds:
    manifest=json.loads((build/'manifest.json').read_text())
    runs=sorted((build/'tests').glob('*-'+a.scenario+'/motion_comparison.json'))
    if not runs:raise ValueError('Missing '+a.scenario+' recording in '+str(build))
    data=json.loads(runs[-1].read_text());samples=data['samples']
    result=json.loads((runs[-1].parent/'result.json').read_text())
    label=build.name.removeprefix('actual-cad-generated-').removesuffix('-20261011')+' ('+result['status']+')'
    t=[s['t'] for s in samples]
    front=[max(abs(s['corners'][c]['toe_error_deg']) for c in ('FL','FR')) for s in samples]
    rear=[max(abs(s['corners'][c]['camber_error_deg']) for c in ('RL','RR')) for s in samples]
    differentials=[owner for owner,role in manifest['component_roles'].items() if role in ('front_diff','rear_diff','rear_final_drive')]
    displacement=[1000*max(s['fixed_components'][owner] for owner in differentials) for s in samples]
    axes[0,0].plot(t,front,label=label);axes[0,1].plot(t,rear,label=label)
    axes[1,0].plot(t,displacement,label=label)
    axes[1,1].plot([s['forward_m'] for s in samples],[s['lateral_m'] for s in samples],label=label)
for ax,title,ylabel,limit in ((axes[0,0],'Front toe error vs ideal linkage','Degrees',2),
                              (axes[0,1],'Rear camber error vs ideal linkage','Degrees',2),
                              (axes[1,0],'Differential displacement relative to chassis','Millimetres',5)):
    ax.set(title=title,xlabel='Recording time (s)',ylabel=ylabel)
    ax.axhline(limit,color='black',linestyle='--',linewidth=.8,label='Screening limit');ax.grid(alpha=.2)
axes[1,1].set(title='Unassisted vehicle path',xlabel='Forward displacement (m)',ylabel='Lateral displacement (m)')
axes[1,1].grid(alpha=.2)
handles,labels=axes[0,0].get_legend_handles_labels()
fig.legend(handles,labels,loc='outside lower center',ncols=min(4,len(labels)))
fig.suptitle(a.scenario.capitalize()+' — generated vehicle comparison; not material qualification')
a.output.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(a.output)
print(a.output)
