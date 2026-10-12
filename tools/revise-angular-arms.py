"""Create an immutable sparse angular-arm trial through the shared generator."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from angular_arms import build
p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('--ratio',type=float,required=True);p.add_argument('--mode',choices=['parallel','replace'],default='parallel');p.add_argument('--members',choices=['all','upper','lower'],default='all');p.add_argument('--output',type=Path,required=True)
a=p.parse_args();build(a.receipt,a.output,a.ratio,a.mode,a.members);print('Revision ready: '+str(a.output/'manifest.json'))
