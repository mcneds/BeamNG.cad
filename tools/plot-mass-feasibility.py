"""Plot the saved fixed-layout bounds and donor-floor counterfactual screen."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('bounds',type=Path);p.add_argument('screen',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    b=json.loads(a.bounds.read_bytes());s=json.loads(a.screen.read_bytes())
    if b['manifest_sha256']!=s['manifest_sha256']:raise ValueError('Reports refer to different builds')
    modes=['mass_only','mass_com','discrete_mass_com_inertia']
    ballast=[b['bounds']['base_floor'][m]['minimum_added_kg'] for m in modes]+[b['numerical_mass_kg']]
    labels=['Mass only\n(lower bound)','Mass + COM\n(lower bound)','Mass + COM + inertia\n(lower bound)','Current build']
    fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained')
    x=np.arange(4);cad=b['cad_mass_kg']
    axes[0].bar(x,[cad]*4,color='#457b9d',label='CAD-derived mass (provisional)')
    axes[0].bar(x,ballast,bottom=cad,color='#e9a23b',label='Additional numerical mass')
    for i,v in enumerate(ballast):axes[0].text(i,cad+v+3,f'{cad+v:.1f} kg',ha='center',fontsize=10)
    axes[0].set_xticks(x,labels,fontsize=9);axes[0].set_ylim(0,340);axes[0].set_ylabel('Vehicle mass (kg)');axes[0].legend(fontsize=8)
    axes[0].set_title('Same ownership layout and 2 kg loaded-node floor')
    trials=s['trials'];y=[v['step_eigenvalue'] for v in trials]
    axes[1].bar(range(len(y)),y,color=['#457b9d' if v['passes_current_rest_screen'] else '#c8553d' for v in trials])
    axes[1].axhline(3.6,color='black',linestyle='--',label='Current screen limit: 3.6')
    for i,v in enumerate(trials):axes[1].text(i,y[i]*1.1,f"{y[i]:.2f}\n{v['mass_kg']:.1f} kg",ha='center',fontsize=10)
    axes[1].set_yscale('log');axes[1].set_ylim(1,400);axes[1].set_xticks(range(len(y)),[f"{v['donor_floor_kg']:g} kg" for v in trials])
    axes[1].set_xlabel('Donor floor; directly loaded nodes remain at least 2 kg')
    axes[1].set_ylabel('Rest-state timestep operator: largest eigenvalue');axes[1].legend(fontsize=8)
    axes[1].set_title('Lower donor floors, unchanged beam coefficients')
    fig.suptitle('Diagnostic bounds only: no stability or physical qualification from mass matching')
    fig.savefig(a.output,dpi=150);plt.close(fig)
