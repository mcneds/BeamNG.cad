"""Bounded pinned-chassis bump/stop/release evidence; not arbitrary node-drag safety."""
import argparse,importlib.util,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('rate_analysis',Path(__file__).with_name('analyze-suspension-rate.py'))
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('runs',type=Path,nargs='+');p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    rows=[analysis.load(r) for r in a.runs]
    if any(r['excitation'].get('kind')!='recovery' for r in rows) or len({r['manifest_sha256'] for r in rows})!=1:raise ValueError('Mismatched recovery recordings')
    for row in rows:
        row['recovery_screen_passed']=all(c['recovery_shock_speed_rms_m_s']<=.01 and abs(c['recovery_length_offset_m'])<=.002 and c['recovery_stop_elastic_peak_n']<=1 and c['spring_law_error_peak_n']<=.1 for c in row['corners'].values())
    report=dict(scope=__doc__,runs=rows,thresholds=dict(shock_speed_rms_m_s=.01,length_offset_m=.002,remaining_stop_force_n=1,spring_law_error_n=.1),qualification_status='not_qualified')
    a.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(10,7),layout='constrained')
    for row in rows:
        e=row['excitation'];h=row['history'][e['corner']];label=f"{e['corner']} +{e['amplitude_n']:g} N"
        axes[0].plot(h['time_s'],h['compression_mm'],label=label)
        axes[1].plot(h['time_s'],h['stop_elastic_n'],label=label)
    for ax,y in zip(axes,['Shock compression (mm)','Elastic travel-stop force (N)']):
        ax.set(xlabel='Time (s)',ylabel=y);ax.grid(alpha=.25);ax.legend()
    fig.savefig(a.output.with_suffix('.png'),dpi=140);plt.close(fig)
    print(json.dumps([dict(force=r['excitation']['amplitude_n'],passed=r['recovery_screen_passed'],corners=r['corners']) for r in rows],indent=2))

if __name__=='__main__':main()
