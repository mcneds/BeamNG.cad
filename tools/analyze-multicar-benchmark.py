"""Quantify motion differences in a completed diagnostic multi-car benchmark."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('frequency',HERE/'analyze-suspension-frequency.py')
frequency=importlib.util.module_from_spec(spec);spec.loader.exec_module(frequency)


def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def analyze(root):
    bench=read(root/'benchmark.json')
    if not bench['sources_unchanged'] or bench.get('error') or bench.get('resource_abort'):
        raise ValueError('Incomplete or changed benchmark')
    reports={};summaries={}
    for label in ['solo0','solo64','paired']:
        batch=next(b for b in bench['batches'] if b['label']==label)
        for lane in batch['lanes']:
            run=root/(label+'-lane'+str(lane));job=read(run/'job.json');completion=read(run/'completion.json')
            if (completion['status']!='completed' or completion['job_id']!=job['id'] or
                completion['session_id']!=job['session_id'] or job['session_id']!=batch['completion']['session_id'] or
                job['id'] not in batch['completion']['children']):raise ValueError('Child identity differs from aggregate completion')
            # A probe sidecar makes the existing strict frequency analyzer reusable;
            # bind it to the real aggregate evidence and per-vehicle completion.
            sidecar=dict(mode='null',deterministic=True,qualification_status='not_qualified',
                purpose='Multi-car comparison only; no qualification receipt',sources_unchanged=True,
                manifest_sha256=bench['manifest_sha256'],completion=completion,
                aggregate_evidence=str(root/'benchmark.json'),aggregate_sha256=sha(root/'benchmark.json'))
            (run/'probe.json').write_text(json.dumps(sidecar,indent=2)+'\n')
            report=frequency.analyze(run);reports[run.name]=report
            (run/'frequency_analysis.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
            summaries[run.name]={c:{k:report['channels'][c+'_toe_error_deg'][k] for k in ['peak','mean','ac_rms']} for c in ['FL','FR']}
            print(run.name,summaries[run.name],flush=True)
    result=dict(scope='Same-lane solo versus simultaneous native reverse; diagnostic only',
        benchmark_sha256=sha(root/'benchmark.json'),benchmark=str(root),throughput_ratio=bench['throughput_ratio'],
        telemetry_equivalent=bench['equivalent_at_tolerance'],toe=summaries)
    (root/'motion-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);a=p.parse_args();analyze(a.root)
