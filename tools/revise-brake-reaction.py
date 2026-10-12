"""Immutable experiment routing brake reaction through existing carrier hardpoints."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from brake_reaction import build
p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--corners',nargs='+',default=['FL','FR']);p.add_argument('--inertia-fraction',type=float,default=.95)
a=p.parse_args();build(a.receipt,a.output,a.corners,a.inertia_fraction);print('Revision ready: '+str(a.output/'manifest.json'))
