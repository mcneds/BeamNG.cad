"""Apply normal numerical checks to a completed execution probe, never qualify it."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.vehicle import analyze

p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args()
probe=json.loads((a.run/'probe.json').read_bytes())
manifest_path=a.run/'build_manifest.json';manifest=json.loads(manifest_path.read_bytes())
if not probe.get('sources_unchanged') or probe.get('resource_abort') or probe.get('error'):
    raise ValueError('Probe did not complete with unchanged sources and adequate resources')
job=json.loads((a.run/'job.json').read_bytes());completion=probe.get('completion',{})
if completion.get('status')!='completed':raise ValueError('Probe recording did not complete')
if completion.get('job_id')!=job['id']:raise ValueError('Probe job identity mismatch')
result=analyze(a.run,manifest,job['scenario'],completion)
result.update(qualification_status='diagnostic_only',probe_mode=probe['mode'],
    scope='Normal numerical thresholds retained. Missing rendering checks fail as usual; no acceptance receipt is written.',
    evidence_sha256={n:hashlib.sha256((a.run/n).read_bytes()).hexdigest() for n in ['probe.json','build_manifest.json','job.json','compiled.json','vehicle.csv','motion_diagnostics.json']})
(a.run/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(dict(status=result['status'],reason=result.get('reason'),metrics={k:v for k,v in result['metrics'].items() if any(s in k for s in ['toe_error','broken_beams','uncommanded','peak_speed'])}),indent=2))
