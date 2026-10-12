"""Compare existing constraint stiffness at recorded suspension poses."""
import argparse,hashlib,importlib.util,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('compliance',Path(__file__).with_name('evaluate-cad-compliance.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('run',type=Path);p.add_argument('--times',nargs='+',type=float,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
probe=json.loads((a.run/'probe.json').read_bytes());job=json.loads((a.run/'job.json').read_bytes());data=json.loads((a.run/'motion_diagnostics.json').read_bytes())
if probe.get('error') or not probe.get('sources_unchanged') or probe['completion']['status']!='completed' or data['job_id']!=job['id']:
    raise ValueError('Complete matched recording required')
expected=json.loads((a.receipt.parent/'manifest.json').read_bytes());recorded=json.loads((a.run/'build_manifest.json').read_bytes())
if expected!=recorded:raise ValueError('Recording does not match this build')
results=[]
for time in a.times:
    sample=min(data['samples'],key=lambda s:abs(s['t']-time))
    if abs(sample['t']-time)>.026:raise ValueError('Requested time is outside the recording')
    result=module.audit(a.receipt,sample['mechanism_positions']);result['time_s']=sample['t'];results.append(result)
    print({k:result[k] for k in ('time_s','rank','nullity','minimum_internal_frequency_hz','maximum_internal_frequency_hz')},flush=True)
a.output.write_text(json.dumps({'poses':results,'evidence_sha256':{f:hashlib.sha256((a.run/f).read_bytes()).hexdigest() for f in ('probe.json','job.json','motion_diagnostics.json','build_manifest.json')}},indent=2)+'\n')
