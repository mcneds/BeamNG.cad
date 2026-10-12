"""Immutable stiffness growth trial through the shared generation stage."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from monotone_rigidity import build
p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('--output',type=Path,required=True)
p.add_argument('--factor',type=float,default=1.5);p.add_argument('--step-limit',type=float,default=3.6);p.add_argument('--selection',choices=['front','frame','members'],default='front')
a=p.parse_args();build(a.receipt,a.output,a.factor,a.step_limit,a.selection)
print('Revision ready: '+str(a.output/'manifest.json'))
