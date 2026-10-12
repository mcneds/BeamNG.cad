"""Check all recorded fixed-part nodes relative to the moving frame."""
import argparse,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle_motion import rigid_fit

p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('run',type=Path)
a=p.parse_args();m=json.loads(a.manifest.read_text());motion=json.loads((a.run/'motion_diagnostics.json').read_text())
contracts=m['fixed_attachment_contract'];chassis=m['chassis_nodes'];original=m['nodes']
weights=np.array([original[n]['mass_kg'] for n in chassis]);base=np.array([original[n]['position'] for n in chassis])
samples=motion['samples']
if len(samples)<10 or samples[-1]['t']<29 or samples[0]['t']>.6:
    raise ValueError('Incomplete fixed attachment recording')
times=np.array([s['t'] for s in samples])
if not np.isfinite(times).all() or np.any(np.diff(times)<=0) or np.max(np.diff(times))>.6:
    raise ValueError('Invalid fixed attachment sampling')
report={owner:dict(peak_error_m=0.,settled_peak_error_m=0.,final_error_m=0.) for owner in contracts}
for s in samples:
    positions=s['reference_positions'];r,t=rigid_fit(base,[positions[n] for n in chassis],weights)
    for owner,c in contracts.items():
        names=c['nodes'];now=np.array([positions[n] for n in names]);rest=np.array([original[n]['position'] for n in names])
        error=np.linalg.norm((now-t)@r.T-rest,axis=1)
        if not np.isfinite(error).all():raise ValueError('Nonfinite fixed attachment position')
        peak=float(error.max());item=report[owner];item['peak_error_m']=max(item['peak_error_m'],peak)
        if s['t']>=4:item['settled_peak_error_m']=max(item['settled_peak_error_m'],peak)
        item['final_error_m']=peak
for item in report.values():item['passed']=item['peak_error_m']<=.005
result=dict(passed=all(v['passed'] for v in report.values()),limit_m=.005,samples=len(samples),duration_s=float(times[-1]),components=report)
(a.run/'fixed-attachment-check.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
