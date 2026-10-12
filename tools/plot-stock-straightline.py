"""Plot actual paths for the stock/candidate diagnostic, without modifying results."""
import argparse
import csv
import json
import math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

COLORS={'utv':'#1f77b4','covet':'#2ca02c','wigeon':'#9467bd','candidate':'#d95f02'}
NAMES={'utv':'Stock UTV','covet':'Stock Covet','wigeon':'Stock Wigeon','candidate':'CAD candidate'}


def rows(run):
    with (Path(run)/'straight.csv').open() as f:
        return [{k:float(v) for k,v in r.items()} for r in csv.DictReader(f)]


def aligned(data,start):
    data=[r for r in data if r['t']>=start];base=data[0];angle=base['heading_rad']
    for r in data:
        x=r['forward_distance']-base['forward_distance'];y=r['lateral_distance']-base['lateral_distance']
        r['aligned_x']=x*math.cos(angle)+y*math.sin(angle)
        r['aligned_y']=-x*math.sin(angle)+y*math.cos(angle)
        r['heading_change']=math.degrees(r['heading_rad']-angle)
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pilot',type=Path,required=True);p.add_argument('--cruise',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    pilot=json.loads(a.pilot.read_text());cruise=json.loads(a.cruise.read_text())
    fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained')
    for run in pilot['runs']:
        name=run['label'];data=[r for r in aligned(rows(run['run']),4) if 0<=r['aligned_x']<=200]
        x=[r['aligned_x'] for r in data]
        axes[0,0].plot(x,[r['aligned_y'] for r in data],color=COLORS[name],label=NAMES[name])
        axes[0,1].plot(x,[r['speed']*3.6 for r in data],color=COLORS[name])
    for run in cruise['runs']:
        name=run['label'];m=run['metrics']['cruise']
        data=[r for r in aligned(rows(run['run']),m['start_t']) if 0<=r['aligned_x']<=200]
        style='-' if m['speed_within_5_percent'] else '--'
        x=[r['aligned_x'] for r in data]
        axes[1,0].plot(x,[r['aligned_y'] for r in data],color=COLORS[name],alpha=.6,linestyle=style)
        axes[1,1].plot(x,[r['speed']*3.6 for r in data],color=COLORS[name],alpha=.6,linestyle=style)
    unmatched=any(not r['metrics']['cruise']['speed_within_5_percent'] for r in cruise['runs'])
    titles=['Full throttle: drift relative to heading at 4 s','Full throttle: different speeds at the same distance',
            'Requested 36 km/h: three repeats per vehicle','Requested 36 km/h: actual speed']
    ylabels=['Lateral displacement (m)','Speed (km/h)','Lateral displacement (m)','Speed (km/h)']
    for ax,title,ylabel in zip(axes.flat,titles,ylabels):
        ax.set(title=title,xlabel='Forward distance from comparison start (m)',ylabel=ylabel,xlim=(0,200))
        ax.grid(alpha=.25);ax.axhline(0,color='gray',lw=.7)
    axes[0,0].legend()
    if unmatched:
        axes[1,0].text(.02,.97,'Dashed curves failed speed matching; not a matched-speed ranking',
                       transform=axes[1,0].transAxes,va='top',fontsize=8,color='#9c3700')
    axes[1,1].axhline(36,color='black',linestyle=':',linewidth=1)
    axes[1,1].set_ylim(26,42)
    fig.suptitle('Zero-steering native Drive recordings — unchanged stock configurations and CAD candidate')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(a.output,dpi=150)
    fig.savefig(a.output.with_suffix('.svg'))
    print(a.output)


if __name__=='__main__':main()
