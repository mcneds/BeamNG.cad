"""Compare unchanged-vehicle Drive/Neutral settling diagnostics, never qualify a build."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(path):
    return json.loads(path.read_bytes())


def report(drive, neutral, output):
    cases={};jobs=[];probes=[];series={}
    for label,run,gear in [('Drive',drive,'D'),('Neutral',neutral,'N')]:
        probe=read(run/'probe.json');job=read(run/'job.json');result=read(run/'result.json')
        if not probe['sources_unchanged'] or not probe['telemetry']['finite'] or not probe['telemetry']['increasing']:
            raise ValueError('Invalid recording identity or telemetry')
        if probe.get('neutral_settle',False)!=(gear=='N') or job['scenario']!='settle':
            raise ValueError('Wrong isolation controls')
        gears={s['gear'] for s in read(run/'motion_diagnostics.json')['samples']}
        if gears!={gear}:raise ValueError('Native gear selection did not match diagnostic')
        if result['recording_status']!='completed':raise ValueError('Incomplete recording')
        rows=[{k:float(v) for k,v in r.items()} for r in csv.DictReader((run/'vehicle.csv').open())]
        last=[r for r in rows if r['t']>=rows[-1]['t']-5]
        cases[label]=dict(run=str(run),observed_gears=sorted(gears),
            final_speed_m_s=rows[-1]['speed'],final_forward_distance_m=rows[-1]['forward_distance'],
            final_lateral_distance_m=rows[-1]['lateral_distance'],
            last_five_seconds_mean_rpm=sum(r['rpm'] for r in last)/len(last),
            settled_relative_speed_m_s=result['metrics']['settled_relative_speed_m_s'],
            failed_checks=[k for k,v in result['checks'].items() if not v],
            hashes={name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in
                    ('probe.json','job.json','vehicle.csv','result.json','motion_diagnostics.json')})
        jobs.append(job);probes.append(probe);series[label]=rows
    # Compare all physical and scenario inputs; staging identifiers differ.
    excluded={'id','output','changed_files','staging_bytes'}
    if {k:v for k,v in jobs[0].items() if k not in excluded}!={k:v for k,v in jobs[1].items() if k not in excluded}:
        raise ValueError('Scenario or vehicle differs')
    for key in ('mode','deterministic','manifest_sha256','implementation','probe_sha256'):
        if probes[0][key]!=probes[1][key]:raise ValueError('Unmatched execution: '+key)
    fig,axes=plt.subplots(2,1,figsize=(9,6),layout='constrained',sharex=True)
    for label,rows in series.items():
        axes[0].plot([r['t'] for r in rows],[r['speed']*3.6 for r in rows],label=label)
        axes[1].plot([r['t'] for r in rows],[r['relative_node_speed'] for r in rows],label=label)
    axes[0].set(ylabel='Vehicle speed (km/h)',title='Same vehicle and controls; only Drive / Neutral differs')
    axes[1].set(xlabel='Simulation time (s)',ylabel='Relative node speed (m/s)')
    for ax in axes:ax.legend();ax.grid(alpha=.2)
    output.parent.mkdir(parents=True,exist_ok=True);fig.savefig(output.with_suffix('.png'),dpi=140);plt.close(fig)
    data=dict(scope=__doc__,qualified=False,controls_verified=True,cases=cases,
              limitation='Neutral isolates powertrain creep; it does not qualify powered dynamics or validate real clutch/spring settings. Original acceptance is unchanged.')
    output.write_text(json.dumps(data,indent=2)+'\n');return data


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--drive',type=Path,required=True);p.add_argument('--neutral',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report(a.drive,a.neutral,a.output);print('Saved settling isolation:',a.output)
