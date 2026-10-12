"""Illustrate why a turn's final displacement cannot describe its full path.

Reads archived evidence only; does not requalify or alter its failed result.
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def plot(run, output):
    motion=json.loads((run/'motion_comparison.json').read_text(encoding='utf-8'))
    result=json.loads((run/'result.json').read_text(encoding='utf-8'))
    samples=motion['samples']
    t=np.array([s['t'] for s in samples])
    xy=np.array([[s['lateral_m'],s['forward_m']] for s in samples])
    yaw=np.degrees(np.unwrap(np.radians([s['yaw_deg'] for s in samples])))
    yaw-=yaw[0]
    sign=-1 if result['scenario']=='left_turn' else 1
    fig,axes=plt.subplots(1,2,figsize=(11,4.6),layout='constrained')
    path=axes[0];path.plot(*xy.T,color='#16706a',lw=2)
    for fraction in (.2,.45,.7):
        index=int(fraction*(len(xy)-3))
        path.annotate('',xy=xy[index+2],xytext=xy[index-2],arrowprops=dict(arrowstyle='->',color='#16706a',lw=2))
    path.scatter(*xy[0],marker='o',color='#222',label='Start')
    path.scatter(*xy[-1],marker='x',color='#c55d1c',label='Finish',zorder=3)
    path.axvline(0,color='#aaa',lw=.7);path.set_aspect('equal',adjustable='datalim')
    path.set(xlabel='Sideways from initial heading (m)',ylabel='Forward from start (m)',title='Recorded chassis path')
    path.legend(loc='best');path.grid(alpha=.2)
    axes[1].plot(t,sign*yaw,color='#16706a',lw=2)
    axes[1].axhline(45,color='#777',ls='--',label='Minimum heading change: 45°')
    axes[1].set(xlabel='Recording time (s)',ylabel='Heading in requested direction (degrees)',title='Heading continues through ±180°')
    axes[1].grid(alpha=.2);axes[1].legend(loc='upper left')
    final=abs(xy[-1,0]);excursion=max(abs(xy[:,0]))
    fig.suptitle(f'{result["scenario"].replace("_"," ").title()} · {sign*yaw[-1]:.1f}° of recorded rotation\n'
                 f'Final sideways displacement {final:.2f} m; path excursion {excursion:.2f} m')
    output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output,dpi=150);plt.close(fig)
    files=('motion_comparison.json','result.json')
    receipt=dict(run=str(run.resolve()),original_status=result['status'],original_reason=result.get('reason'),
                 purpose='Verifier diagnostic only; original qualification remains unchanged.',
                 sources={name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in files})
    output.with_suffix('.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();plot(args.run,args.output)
