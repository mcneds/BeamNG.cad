"""Regenerate pressure-wheel resolution through the production refinement stage."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from tire_resolution import DEFAULT_RAYS
from tire_revision import build

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('receipt',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--rays',type=int,default=DEFAULT_RAYS);a=p.parse_args();build(a.receipt,a.output,a.rays)
    print(a.output/'manifest.json')
