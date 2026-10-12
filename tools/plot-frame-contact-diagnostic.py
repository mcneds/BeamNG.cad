"""Plot the controlled native internal-contact comparison from archived runs."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('baseline',type=Path)
parser.add_argument('control',type=Path)
parser.add_argument('output',type=Path)
args=parser.parse_args()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
first,second=(read(p/'job.json') for p in (args.baseline,args.control))
if first.get('diagnostic') or second.get('diagnostic')!='no_self_collision':
    raise ValueError('Expected a normal run and an isolated internal-contact control')
if first['manifest']['physics_sha256']!=second['manifest']['physics_sha256'] or first['scenario']!=second['scenario']:
    raise ValueError('The two recordings must use identical physics and scenario')
fig,ax=plt.subplots(figsize=(9,4.5),layout='constrained')
colors=['#d16c28','#167e85']
for path,color,label in zip((args.baseline,args.control),colors,('Original internal contact','Internal contact disabled in control')):
    data=read(path/'motion_comparison.json')['samples']
    ax.plot([s['t'] for s in data],[s['chassis_shape_error_m']*1000 for s in data],color=color,label=label,lw=2)
ax.axhline(5,color='#687079',linestyle='--',lw=1,label='Unchanged 5 mm frame limit')
failure=read(args.baseline/'first_breaks.json')
ax.axvline(failure['time'],color=colors[0],linestyle=':',lw=1)
baseline=read(args.baseline/'motion_comparison.json')['samples']
event_shape=np.interp(failure['time'],[s['t'] for s in baseline],[s['chassis_shape_error_m']*1000 for s in baseline])
ax.annotate('Frame beam broke during settling',xy=(failure['time'],event_shape),xytext=(9,3.2),
            arrowprops=dict(arrowstyle='->',color=colors[0]),color=colors[0],fontsize=10)
ax.set(xlabel='Simulation time (s)',ylabel='Maximum frame shape error (mm)',
       title='A coarse frame envelope was contacting the attached floor panel',xlim=(0,30),ylim=(0,6.5))
ax.grid(alpha=.2);ax.legend(loc='upper left',fontsize=9)
fig.supxlabel('Same CAD, masses, springs and strength limits. Terrain collision and tire pressure retained.\n'
               'The controlled run is diagnostic; it cannot qualify the vehicle.',fontsize=9,color='#454d55')
args.output.parent.mkdir(parents=True,exist_ok=True)
fig.savefig(args.output,dpi=170)
args.output.with_suffix('.json').write_text(json.dumps(dict(baseline=str(args.baseline),control=str(args.control),
    physics_sha256=first['manifest']['physics_sha256'],diagnostic='no_self_collision'),indent=2)+'\n')
