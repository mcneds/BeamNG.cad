"""Audit execution throughput without assigning vehicle qualification."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);a=p.parse_args()
    batch=json.loads((a.directory/'benchmark.json').read_text())
    rows=[]
    for phase in ('sequential','parallel'):
        for record in batch[phase]['runs']:
            folder=Path(record['output'])
            data=list(csv.DictReader((folder/'vehicle.csv').open()))
            diagnostics=json.loads((folder/'motion_diagnostics.json').read_text())
            resources=json.loads((folder/'resources.json').read_text())
            dt=[diagnostics['physics_dt_min'],diagnostics['physics_dt_max']]
            rows.append(dict(run=folder.name,wall_s=record['wall_s'],recording_s=record['timings'].get('recording'),
                complete=not record.get('error') and not record.get('resource_abort') and record.get('sources_unchanged') and
                    record.get('completion',{}).get('status')=='completed' and
                    len(data)==record['completion'].get('samples') and float(data[-1]['t'])>=25 and
                    all(math.isfinite(float(v)) for row in data for v in row.values()) and
                    all(float(b['t'])>float(a['t']) for a,b in zip(data,data[1:])),
                physics_2000_hz=all(math.isclose(t,.0005,rel_tol=1e-6) for t in dt),
                physics_steps=diagnostics['physics_steps'],samples=len(data),
                telemetry_sha256=hashlib.sha256((folder/'vehicle.csv').read_bytes()).hexdigest(),
                manifest_sha256=record['manifest_sha256'],deterministic=record.get('deterministic',False),
                peak_lateral_m=max(abs(float(row['lateral_distance'])) for row in data),
                peak_private_gib=max(x.get('private_bytes',0) for x in resources)/2**30,
                minimum_available_gib=min(x['available_ram_bytes'] for x in resources)/2**30))
    comparable=all(r['complete'] and r['physics_2000_hz'] and r['deterministic'] for r in rows) and len({r['manifest_sha256'] for r in rows})==1
    result=dict(qualification_status='not_qualified',purpose='Diagnostic execution benchmark only',runs=rows,
        comparable=comparable,identical_csv=len({r['telemetry_sha256'] for r in rows})==1,
        sequential_s=batch['sequential']['wall_s'],parallel_s=batch['parallel']['wall_s'],
        throughput_ratio=batch['sequential']['wall_s']/batch['parallel']['wall_s'] if comparable else None)
    (a.directory/'comparison.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
