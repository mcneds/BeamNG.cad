"""Attach current graph generation outputs to the real-CAD wrapping atlas."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.build import node_table,beam_table
from frame_harness.bracing import add_local_bracing

def main():
    p=argparse.ArgumentParser();p.add_argument('--work',required=True);args=p.parse_args()
    public=ROOT/'website/public/assets/wrapping';manifest=json.loads((public/'manifest.json').read_text())
    script=ROOT/'beamng.cad/FramePipeline/generation/JBeamShellGenerator.py'
    for case in manifest['cases']:
        folder=Path(args.work)/case['id'];target=folder/'graph.jbeam'
        with (folder/'graph.log').open('w') as log:
            subprocess.run([sys.executable,str(script),str(folder/'hull.off'),'-o',str(target)],stdout=log,stderr=subprocess.STDOUT,check=True)
        part=json.loads('\n'.join(l for l in target.read_text().splitlines() if not l.lstrip().startswith('//')))['mochi']
        nodes=node_table(part);names=list(nodes);indices={n:i for i,n in enumerate(names)}
        before=beam_table(part);bracing=add_local_bracing(part);after=beam_table(part)
        def edges(items):return [[indices[e['a']],indices[e['b']]] for e in items]
        graph=dict(positions=[nodes[n]['position'] for n in names],names=names,edges=edges(before),
                   addedEdges=edges(after[len(before):]),triangles=[],rank=3*len(nodes)-6,
                   shellNodes=sum(n.startswith('sh') for n in names),nodeCount=len(nodes),beamCount=len(after))
        output=public/(case['id']+'.json');data=json.loads(output.read_text());data['graph']=graph
        output.write_text(json.dumps(data,separators=(',',':')))
        case.update(graphNodes=len(nodes),graphBeams=len(after),sha256=hashlib.sha256(output.read_bytes()).hexdigest())
        print(case['id'],len(nodes),len(after),flush=True)
    for name in ['beamng.cad/FramePipeline/generation/JBeamShellGenerator.py','dependencies/cad-calibration/Test Harness/frame_harness/bracing.py','tools/generate-docs-graph.py']:
        manifest['sources'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    (public/'manifest.json').write_text(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
