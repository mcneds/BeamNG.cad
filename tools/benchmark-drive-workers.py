"""Compare two sequential and two concurrent diagnostic Drive recordings.

Profiles must be distinct harness-owned folders. Warm them beforehand with the
probe tool to avoid comparing a cold profile with cached imported meshes.
Does not generate acceptance/installation receipts or modify the vehicle.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest',type=Path)
    p.add_argument('--profiles',nargs=2,type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.profiles[0].resolve()==a.profiles[1].resolve():p.error('Workers need separate profiles')
    if any(not (x/'.frame-harness-owned').is_file() for x in a.profiles):p.error('Warm both owned profiles first')
    a.output.mkdir(parents=True,exist_ok=False)
    child=Path(__file__).with_name('probe-drive-execution.py')
    results={}
    def run(phase,index):
        output=a.output/(phase+'-'+str(index))
        command=[sys.executable,str(child),str(a.manifest),'--mode','null',
                 '--profile',str(a.profiles[index]),'--output',str(output),'--deterministic']
        with (a.output/(output.name+'.log')).open('w') as log:
            code=subprocess.call(command,stdout=log,stderr=subprocess.STDOUT,
                                 env=os.environ|{'OPENBLAS_NUM_THREADS':'1'})
        path=output/'probe.json'
        result=json.loads(path.read_text()) if path.is_file() else {}
        result.update(exit_code=code,output=str(output))
        return result
    for phase in ('sequential','parallel'):
        started=time.monotonic()
        if phase=='sequential':runs=[run(phase,i) for i in range(2)]
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:runs=list(pool.map(lambda i:run(phase,i),range(2)))
        results[phase]=dict(wall_s=time.monotonic()-started,runs=runs)
        (a.output/'benchmark.json').write_text(json.dumps(results,indent=2))
        print(phase,results[phase]['wall_s'],[(r.get('completion',{}).get('status'),r.get('error')) for r in runs],flush=True)
        if any(r.get('error') or r.get('completion',{}).get('status')!='completed' or not r.get('sources_unchanged') for r in runs):
            print('Stopping comparison after incomplete/changed probe',flush=True);return
    print('Throughput ratio:',results['sequential']['wall_s']/results['parallel']['wall_s'],flush=True)


if __name__=='__main__':main()
