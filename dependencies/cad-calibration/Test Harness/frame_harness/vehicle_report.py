"""Flat, self-contained report for a generic vehicle run."""
import csv
import html
from pathlib import Path


def write_report(directory,result):
    root=Path(directory);plot=''
    if (root/'vehicle.csv').exists():
        with (root/'vehicle.csv').open(encoding='utf-8') as stream:rows=list(csv.DictReader(stream))
        if rows:
            import matplotlib
            matplotlib.use('Agg')
            from matplotlib import pyplot as plt
            t=[float(r['t']) for r in rows];fig,axes=plt.subplots(4,1,figsize=(10,9),sharex=True,layout='constrained')
            for axis,columns,label in [(axes[0],['speed'],'Speed (m/s)'),(axes[1],['av_FL','av_FR','av_RL','av_RR'],'Wheel speed (rad/s)'),
                                      (axes[2],['travel_FL','travel_FR','travel_RL','travel_RR'],'Hub travel (m)'),(axes[3],['broken'],'Broken beams')]:
                for col in columns:axis.plot(t,[float(r[col]) for r in rows],label=col,linewidth=1)
                axis.set_ylabel(label);axis.grid(True,alpha=.25);axis.legend(loc='upper left',ncol=len(columns),fontsize=8)
            axes[-1].set_xlabel('Simulation time (s)');fig.savefig(root/'telemetry.png',dpi=120);plt.close(fig)
            plot='<h2>Telemetry</h2><img src="telemetry.png" alt="Speed, wheel rotation, suspension travel and broken beams over time">'
    if not plot and (root/'telemetry.png').exists():
        plot='<h2>Telemetry</h2><img src="telemetry.png" alt="Recorded speed, wheel rotation, suspension travel and broken beams">'
    esc=html.escape
    links=' | '.join(f'<a href="{name}">{label}</a>' for name,label in
        [('vehicle.csv','Telemetry CSV'),('result.json','Result JSON'),('compiled.json','Compiled graph'),('beamng.log','Game log'),('motion-comparison.html','Ideal versus simulated motion')]
        if (root/name).is_file())
    if not (root/'vehicle.csv').exists():links+=' | Raw diagnostics were not retained; measured results and images are preserved.'
    checks=''.join(f'<tr><td>{esc(k)}</td><td>{"PASS" if v else "FAIL"}</td></tr>' for k,v in result.get('checks',{}).items())
    metrics=''.join(f'<tr><td>{esc(k)}</td><td>{esc(str(v))}</td></tr>' for k,v in result.get('metrics',{}).items())
    dimensions=result.get('assessment',{}).get('dimensions',{})
    assessment=''
    if dimensions:
        rows=''.join(f'<tr><td>{esc(k.replace("_"," "))}</td><td>{esc(v["status"])}</td><td>{esc(v["scope"])}</td></tr>' for k,v in dimensions.items())
        assessment='<h2>Calibration evidence</h2><table>'+rows+'</table><p>These separate assessments preserve the original acceptance result. Physical dynamics remain unqualified until independently tested.</p>'
    screenshot='<h2>Final state</h2><img src="final.png" alt="Actual game capture">' if (root/'final.png').exists() else '<p>No graphics capture was saved.</p>'
    document=f'''<!doctype html><meta charset="utf-8"><title>Vehicle test — {esc(result['scenario'])}</title>
<style>body{{font:14px Arial,sans-serif;background:#ddd;color:#171717;margin:24px;max-width:1100px}}h1{{font-size:23px}}h2{{font-size:17px}}table{{border-collapse:collapse;background:#f7f7f3;width:100%}}td{{border:1px solid #888;padding:6px}}img{{max-width:100%;border:1px solid #888}}a{{color:#164a83}}</style>
<h1>{esc(result['scenario'])}: {esc(result['status'].upper())}</h1><p>{esc(result.get('reason') or 'All measured checks passed.')}</p>
<p>{links}</p>
{assessment}<h2>Checks</h2><table>{checks}</table><h2>Measurements</h2><table>{metrics}</table>{plot}{screenshot}
<p>Simulation evidence for this build only. CAD joint-center accuracy, mesh clearance and real material fracture still require separate review.</p>'''
    (root/'report.html').write_text(document,encoding='utf-8')


def write_acceptance_report(directory,result):
    root=Path(directory);rows=[]
    for i,run in enumerate(result['runs']):
        href=Path(run['directory']).relative_to(root).as_posix()+'/report.html'
        values='; '.join(f'{k} = {v:.4g}' if isinstance(v,(float,int)) else f'{k} = {v}' for k,v in run.get('metrics',{}).items())
        rows.append(f'<tr><td>{i//8+1}</td><td><a href="{html.escape(href)}">{html.escape(run["scenario"])}</a></td><td>{html.escape(run["status"])}</td><td>{html.escape(values)}</td></tr>')
    document=f'''<!doctype html><meta charset="utf-8"><title>Vehicle acceptance</title><style>body{{font:14px Arial;background:#ddd;color:#111;margin:24px}}table{{border-collapse:collapse;background:#f7f7f3}}td,th{{border:1px solid #888;padding:7px;text-align:left}}a{{color:#164a83}}</style>
<h1>Vehicle acceptance: {html.escape(result['status'].upper())}</h1><p>{result['completed_runs']} of {result['required_runs']} independent game runs completed.</p>
<table><tr><th>Repeat</th><th>Scenario / report</th><th>Status</th><th>Measurements</th></tr>{''.join(rows)}</table>
<p>Review separately: CAD hardpoint accuracy, mesh clearance and real material fracture. These tests do not establish those properties.</p><p><a href="acceptance.json">Raw acceptance scorecard</a></p>'''
    (root/'report.html').write_text(document,encoding='utf-8')
