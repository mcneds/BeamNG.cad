"""Create an immutable numerical arm candidate using the production fitter."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from numerical_revision import build

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('receipt',type=Path);p.add_argument('--output',type=Path,required=True)
p.add_argument('--frequency',type=float,required=True)
p.add_argument('--members',choices=['all','upper','lower'],default='all')
p.add_argument('--damping-budget',type=float,help='Optional internal wishbone strain-damping budget [2,3.2]; coilover laws remain unchanged')
p.add_argument('--step-limit',type=float,help='Experimental assembled tangent limit [2,3.6], default 3.2; requires native stability checks')
p.add_argument('--coupled-frequency',type=float,help='Joint positive fit on the selected frame and front constraints; requires frame/front-load-path options')
p.add_argument('--coupled-objective',choices=['isotropic','logdet','motion'],default='isotropic',help='Optional weak-mode or CAD wheel-angle compliance objective')
p.add_argument('--shared-edge-fit',action='store_true',help='Fit member stiffness only on its owned constraints, excluding the shared chassis hinge edge')
p.add_argument('--frame-priority',type=float,default=1.,help='Rebalance explicit numerical rigid-frame reference toward its pivots')
p.add_argument('--frame-frequency',type=float,help='Refit an explicit numerical rigid frame jointly with the arms; does not calibrate material stiffness')
p.add_argument('--frame-only',action='store_true',help='Refit only the explicit rigid frame; preserve all member and steering coefficients')
p.add_argument('--front-load-path-frequency',type=float,help='Also refit existing front upright constraints and equivalent steering links')
a=p.parse_args()
build(a.receipt,a.output,a.frequency,a.members,a.frame_priority,a.frame_frequency,a.front_load_path_frequency,a.damping_budget,a.step_limit,a.coupled_frequency,a.coupled_objective,a.shared_edge_fit,a.frame_only)
print('Numerical revision ready: '+str(a.output/'manifest.json'),flush=True)
