"""Plot recorded explicit-node speeds for the failed and corrected drop runs."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('before',type=Path);p.add_argument('after',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    fig,ax=plt.subplots(figsize=(9,4.8))
    fig.subplots_adjust(bottom=.2,top=.9,left=.1,right=.98)
    for folder,label,color in ((a.before,'Previous preview: missing support-node floor','#ba3434'),(a.after,'Corrected receiving-node floor','#21774b')):
        samples=json.loads((folder/'startup_diagnostics.json').read_bytes())['samples']
        valid=[s for s in samples if 0<s.get('max_speed',0)<1e5]
        ax.semilogy([s['seconds'] for s in valid],[s['max_speed'] for s in valid],label=label,color=color)
    ax.set(xlim=(0,3),ylim=(.01,1e5),xlabel='Physics time after spawning (s)',ylabel='Maximum explicit-node speed (m/s)',
           title='3 m drop: numerical runaway versus corrected joint supports')
    ax.annotate('Previous recording becomes nonfinite',xy=(.85,20000),xytext=(1.1,10000),arrowprops=dict(arrowstyle='->',color='#ba3434'))
    ax.grid(alpha=.25,which='both');ax.legend(loc='lower right')
    fig.text(.1,.025,'Corrected run: 30 s / 600 finite samples. Null renderer; diagnostic, not physical qualification.',fontsize=8)
    a.output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(a.output,dpi=150);plt.close(fig)


if __name__=='__main__':main()
