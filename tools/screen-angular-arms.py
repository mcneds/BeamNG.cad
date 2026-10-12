"""Screen a sparse arm angular trial before packaging or native execution."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from angular_screen import matrices,discrete_spectrum
from frame_harness.build import node_table
from angular_arms import staged


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('--ratio',type=float,default=.5);p.add_argument('--mode',choices=['parallel','replace'],default='parallel');p.add_argument('--members',choices=['all','upper','lower'],default='all');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    receipt=json.loads(a.receipt.read_bytes());manifest=json.loads((a.receipt.parent/'manifest.json').read_bytes())
    path=next(n for n in receipt['component_files'] if n.endswith('.jbeam'));data=(a.receipt.parent/path).read_bytes()
    if hashlib.sha256(data).hexdigest()!=receipt['component_files'][path]:raise ValueError('Baseline JBeam changed')
    part=next(iter(json.loads(data).values()));part,new=staged(part,manifest,a.ratio,a.mode,a.members) if a.ratio else (part,[])
    print('Assembling nonsymmetric dynamics',flush=True)
    k,c=matrices(part,node_table(part));print('Solving full discrete spectrum',flush=True)
    result=discrete_spectrum(k,c);result.update(ratio=a.ratio,mode=a.mode,members=a.members,angular_beams=new,baseline_jbeam_sha256=hashlib.sha256(data).hexdigest())
    a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
