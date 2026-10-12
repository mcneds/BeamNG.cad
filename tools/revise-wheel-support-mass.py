import argparse
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from wheel_support_reuse import build
p=argparse.ArgumentParser(description='Replace reported axle ballast with existing wheel mass; preserve wheel moments.')
p.add_argument('receipt',type=Path);p.add_argument('--output',type=Path,required=True)
p.add_argument('--per-axle-kg',type=float,default=1.)
a=p.parse_args();build(a.receipt,a.output,a.per_axle_kg)
print('Diagnostic revision ready: '+str(a.output/'manifest.json'))
