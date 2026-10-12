"""Compare ideal axle roll steer at declared ride positions; no native qualification."""
import argparse,copy,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
import numpy as np
from vehicle_templates import TemplateModel,Mechanism
from vehicle_alignment import solve
from suspension_loads import ride_reference
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def audit(definition,output):
    results=[];fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for sag in (0.,.03,.06,.09):
        data=copy.deepcopy(definition);parameters=data['parameters']
        parameters.update(level_axle_ride_height=True,ride_sag_m=sag)
        for axle in ('front','rear'):parameters.pop(axle+'_ride_hub_height_m',None)
        model=TemplateModel(data);alignment=solve(model)
        for ax,axle,corners in zip(axes,('front','rear'),(('FL','FR'),('RL','RR'))):
            samples=[]
            for roll in np.linspace(-.025,.025,31):
                angles=[]
                for corner,sign in zip(corners,(1,-1)):
                    travel,extension,_=ride_reference(model,corner,alignment)
                    _,pose=Mechanism(model,corner).solve(travel+sign*roll,extension)
                    axis=pose['hub_axis']-pose['hub'];axis*=1 if axis[0]>=0 else -1
                    angles.append(float(np.degrees(np.arctan2(axis[1],axis[0]))))
                samples.append(dict(opposed_travel_m=float(roll),mean_signed_toe_deg=float(np.mean(angles))))
            ax.plot([s['opposed_travel_m']*1000 for s in samples],[s['mean_signed_toe_deg'] for s in samples],label=f'{sag*1000:.0f} mm sag')
            results.append(dict(sag_m=sag,axle=axle,samples=samples))
    for ax,axle in zip(axes,('Front','Rear')):
        ax.set_title(axle+' ideal roll steer');ax.set_xlabel('Left bump / right droop (mm)')
        ax.set_ylabel('Mean signed wheel angle (degrees)');ax.grid(alpha=.2);ax.legend()
    fig.suptitle('Rigid-link geometry only; excludes tires, compliance and body dynamics')
    output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output,dpi=150);plt.close(fig)
    output.with_suffix('.json').write_text(json.dumps(dict(qualification=False,results=results),indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('template',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();audit(json.loads(args.template.read_text(encoding='utf-8-sig')),args.output)
