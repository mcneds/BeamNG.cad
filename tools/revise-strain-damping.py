"""Generate an immutable trial using the shared internal strain damping stage."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from filtered_strain_damping import build
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('receipt',type=Path);p.add_argument('--output',type=Path,required=True)
p.add_argument('--ratio',type=float);p.add_argument('--cutoff',type=float,default=25.)
p.add_argument('--fixed-limit',type=float,help='Reduce only fixed numerical damping to an envelope limit in [2.9,3.2)')
p.add_argument('--step-limit',type=float,default=3.2,help='Experimental unfiltered envelope limit [3.2,3.6]; native verification required')
a=p.parse_args();build(a.receipt,a.output,a.ratio,a.cutoff,a.step_limit,a.fixed_limit)
print('Revision ready: '+str(a.output/'manifest.json'))
