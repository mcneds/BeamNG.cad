"""Validate a bounded single-node disturbance and recovery; no arbitrary-grab qualification."""
import argparse,hashlib,importlib.util,json,re
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('node_probe',Path(__file__).with_name('probe-node-perturbation.py'))
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

def analyze(run):
    names=['job.json','probe.json','completion.json','compiled.json','node_perturbation.json','vehicle.csv','node_perturbation.csv']
    job,status,completion,compiled,meta=[json.loads((run/n).read_bytes()) for n in names[:5]]
    e=job['excitation']
    if e!=probe.excitation(e['corner'],e['amplitude_n']) or job['duration']!=18.:
        raise ValueError('Changed disturbance contract')
    if job['scenario']!='node_perturbation' or job['gravity']!=-9.81 or job['fixture_fixed_nodes'] or compiled['fixed_nodes']!=0:raise ValueError('Wrong unpinned ground fixture')
    if not status.get('sources_unchanged') or status.get('error') or status.get('resource_abort') or completion.get('status')!='completed' or status.get('completion',{}).get('status')!='completed':raise ValueError('Incomplete/changed recording')
    if not meta['complete'] or meta['job_id']!=job['id'] or completion['job_id']!=job['id'] or meta['node']!=job['perturbed_node']:raise ValueError('Mismatched node/job identity')
    data=np.loadtxt(run/'node_perturbation.csv',delimiter=',',skiprows=1);r=np.genfromtxt(run/'vehicle.csv',delimiter=',',names=True)
    if data.shape!=(meta['samples'],8) or not np.isfinite(data).all() or abs(data[0,0]-.0005)>1e-8 or abs(data[-1,0]-job['duration'])>.051 or max(abs(np.diff(data[:,0])-.0005))>1e-8:raise ValueError('Incomplete physics telemetry')
    expected=np.array([probe.waveform(t,job['excitation']) for t in data[:,0]])
    if not np.allclose(expected,data[:,1],rtol=0,atol=1e-5):raise ValueError('Applied force waveform differs')
    if len(r)!=completion['samples'] or r['t'][-1]<job['duration']-.01 or not np.isfinite(np.array(r.tolist())).all() or np.any(np.diff(r['t'])<=0) or np.max(np.diff(r['t']))>.051:raise ValueError('Incomplete vehicle telemetry')
    if max(abs(r['throttle']))>0 or max(abs(r['brake']))>0:raise ValueError('Unexpected driven/braked fixture')
    motion=json.loads((run/'motion_diagnostics.json').read_bytes())
    if motion['job_id']!=job['id'] or len(motion['samples'])!=len(r):raise ValueError('Missing motion identity')
    if any(abs(s['steering_applied'])>1e-6 or abs(s['steering_command'])>1e-6 for s in motion['samples']):raise ValueError('Nonzero steering')
    log=(run/'beamng.log').read_text(errors='replace')
    instability=[line for line in log.splitlines() if re.search(r'instability detected|physics instability|unstable physics',line,re.I)]
    recovery=r['t']>=16;active=(r['t']>=6)&(r['t']<=10)
    result=dict(run=str(run),scope=__doc__,excitation=job['excitation'],manifest_sha256=status['manifest_sha256'],analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),recording_status='completed',qualification_status='not_qualified',
        maximum_broken_beams=float(max(r['broken'])),minimum_up_z=float(min(r['up_z'])),instability_log=instability,
        peak_relative_node_speed_m_s=float(max(r['relative_node_speed'][active])),recovery_relative_node_speed_peak_m_s=float(max(r['relative_node_speed'][recovery])),
        maximum_node_speed_m_s=float(max(np.linalg.norm(data[:,5:],axis=1))),
        peak_force_n=float(max(abs(data[:,1]))),force_work_j=float(np.trapezoid(data[:,1]*data[:,5],data[:,0])),
        evidence_sha256={n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in names+['motion_diagnostics.json','beamng.log']})
    result['recovery_screen_passed']=not instability and result['maximum_broken_beams']==0 and result['minimum_up_z']>.5 and result['recovery_relative_node_speed_peak_m_s']<.5
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();r=analyze(a.run)
    (a.run/'perturbation_analysis.json').write_text(json.dumps(r,indent=2),encoding='utf-8');print(json.dumps(r,indent=2))
    if not r['recovery_screen_passed']:raise SystemExit(2)
