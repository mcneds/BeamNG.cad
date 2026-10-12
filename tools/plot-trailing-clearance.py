"""Draw physical fixture tubes and tire envelopes directly from CAD recipes."""
import argparse,hashlib,json,sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon,Rectangle,Circle
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
from synthetic_clearance import tube_wheel_clearance
p=argparse.ArgumentParser();p.add_argument('before',type=Path);p.add_argument('after',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
fig,axes=plt.subplots(1,2,figsize=(11,6),sharex=True,sharey=True)
for ax,path,label in zip(axes,(a.before,a.after),('Original physical tubes','Revised physical tubes')):
    r=json.loads(path.read_text());h=r['hardpoints']['RL'];hub=np.array(h['hub']);axis=np.array(h['hub_axis'])-hub
    shapes=next(c for c in r['components'] if c['id']=='rl_trailing_arm')['primitives']
    # Hub-height slice of the annular wheel envelope; tubes shown in plan.
    for sign in (-1,1):
        y=hub[1]+(.16 if sign>0 else -.28)
        ax.add_patch(Rectangle((hub[0]-.084,y),.168,.12,facecolor='#bec7d0',edgecolor='#555e68'))
    for shape in shapes:
        start=np.array(shape['a'])[:2];end=np.array(shape['b'])[:2];delta=end-start
        normal=np.array([-delta[1],delta[0]])/np.linalg.norm(delta)*shape['radius']
        clearance=tube_wheel_clearance(shape,hub,axis)
        color='#cd493e' if clearance<0 else '#226d9e'
        ax.add_patch(Polygon([start+normal,end+normal,end-normal,start-normal],color=color,alpha=.8))
        for point in (start,end):ax.add_patch(Circle(point,shape['radius'],color=color,alpha=.8))
    ax.scatter(*hub[:2],marker='+',color='#111111',s=100,zorder=5)
    ax.annotate('Hub centre',hub[:2],xytext=(hub[0]-.025,hub[1]+.075),arrowprops={'arrowstyle':'-'},fontsize=9,
                bbox={'facecolor':'white','edgecolor':'none','alpha':.85})
    ax.set_title(label);ax.set_aspect('equal');ax.grid(alpha=.2);ax.set_xlabel('Lateral position (m)')
    ax.set_xlim(.31,.99);ax.set_ylim(hub[1]-.68,hub[1]+.35)
axes[0].set_ylabel('Longitudinal position (m)')
axes[0].annotate('Tube crosses tire envelope',(.70,hub[1]-.20),xytext=(.34,hub[1]+.34),fontsize=9,
                 arrowprops={'arrowstyle':'->','color':'#cd493e'},color='#a62821',bbox={'facecolor':'white','edgecolor':'none','alpha':.85})
axes[1].annotate('Inboard tubes; spindle\nthrough central opening',(.615,hub[1]),xytext=(.34,hub[1]+.30),fontsize=9,color='#226d9e',
                 arrowprops={'arrowstyle':'->','color':'#226d9e'},bbox={'facecolor':'white','edgecolor':'none','alpha':.85})
fig.suptitle('Synthetic rear-left arm: physical CAD clearance',fontsize=15)
fig.text(.5,.015,'Plan view of CAD tubes; grey wheel envelope shown at hub height. Auxiliary JBeam constraints are not rendered.',ha='center',fontsize=9)
fig.tight_layout(rect=(0,.035,1,.95));a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output,dpi=150)
a.output.with_suffix('.json').write_text(json.dumps({'kind':'recipe_geometry_diagram','inputs':{
    str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (a.before,a.after)},
    'image_sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()},indent=2)+'\n')
