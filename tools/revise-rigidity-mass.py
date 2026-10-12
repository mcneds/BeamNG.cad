import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from rigidity_mass_plan import build
p=argparse.ArgumentParser();p.add_argument('receipt',type=Path);p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--added-limit',type=float,default=30.)
a=p.parse_args();build(a.receipt,a.plan,a.output,a.added_limit);print('Revision ready: '+str(a.output/'manifest.json'))
