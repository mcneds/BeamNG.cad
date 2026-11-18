import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from compact_revision import revise
p=argparse.ArgumentParser();p.add_argument('receipt',type=Path);p.add_argument('--component',action='append',required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();revise(a.receipt,a.component,a.output)
