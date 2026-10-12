"""Plot archived toe residuals and mass penalties without hiding failed peaks."""
import argparse,hashlib,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('builds',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--motion',action='store_true');a=p.parse_args()
    trials=[('frame500-arms500-launch-deterministic-20261011','Baseline',0.),
            ('front-mass15-reverse-20261012','Front stiffness +50%',26.116388951778518),
            ('upper-mass15-reverse-20261012','Upper arms +50%',6.66220484273076),
            ('angular-replace03-reverse-20261012','Angular replacement',0.)]
    if a.motion:
        trials=[trials[0],trials[1],('motion-mass-reverse-20261012','Motion-weighted: 200 iterations',30.),
                ('motion-mass-tight-reverse-20261012','Motion-weighted: 800 iterations',30.)]
    fig,axes=plt.subplots(2,2,figsize=(12,7),layout='constrained');evidence={}
    colors=['#777777','#167ea6','#d68822','#b33d51']
    for (name,label,added),color in zip(trials,colors):
        source=a.builds/name/'frequency_analysis.json';d=json.loads(source.read_bytes());h=d['display_history'];values=[]
        for i,corner in enumerate(('FL','FR')):
            key=corner+'_toe_error_deg';axes[0,i].plot(h['time_s'],h['channels'][key],label=label,lw=1.1,color=color)
            values.append(d['channels'][key]['peak'])
        evidence[name]=dict(analysis_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),peaks_deg=values,added_numerical_mass_kg=added)
    for i,corner in enumerate(('FL','FR')):
        ax=axes[0,i];ax.axhline(2,color='black',ls='--',lw=.8);ax.axhline(-2,color='black',ls='--',lw=.8)
        ax.set(xlim=(4.7,5.8),xlabel='Simulation time (s)',ylabel='Toe residual from CAD (degrees)',title=corner+' during reverse braking');ax.grid(alpha=.2)
    axes[0,0].legend(fontsize=8)
    labels=[label for _,label,_ in trials];peaks=[max(evidence[name]['peaks_deg']) for name,_,_ in trials]
    ax=axes[1,0];bars=ax.barh(labels,peaks,color=['#777777','#167ea6','#d68822','#b33d51']);ax.axvline(2,color='black',ls='--',lw=1)
    ax.set(xlabel='Worst front toe residual (degrees)',title='Peaks use all 2,000 Hz samples',xlim=(0,4.2));ax.bar_label(bars,fmt='%.2f',padding=4)
    ax=axes[1,1];bars=ax.barh(labels,[mass for _,_,mass in trials],color=['#777777','#167ea6','#d68822','#b33d51']);ax.bar_label(bars,fmt='%.2f',padding=4)
    ax.set(xlabel='Additional numerical mass above baseline (kg)',title='Baseline already contains numerical ballast',xlim=(0,32))
    fig.suptitle('Numerical rigidity trials — none passes the 2° check',fontsize=14)
    a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output,dpi=160);plt.close(fig)
    a.output.with_suffix('.json').write_text(json.dumps(dict(scope=__doc__,trials=evidence,plot_scope='Time traces are decimated for display; bar peaks use the complete recorded interval. Geometry and physical suspension laws unchanged. Added mass changes dynamics.'),indent=2)+'\n')


if __name__=='__main__':main()
