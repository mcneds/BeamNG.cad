"""Native isolated-frame pilot for a fresh calibrated synthetic artifact."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dependencies/cad-calibration/Test Harness'))
from frame_harness.models import HarnessProject,ParameterSet
from frame_harness.generation import scenario
from frame_harness.runner import run_test
p=argparse.ArgumentParser();p.add_argument('generation',type=Path);p.add_argument('--scenario',default='flex');a=p.parse_args()
project=HarnessProject(game=Path('D:/SteamLibrary/steamapps/common/BeamNG.drive'),userpath=Path('H:/BeamNGCadHarness/synthetic-mvp-20261007'),source=a.generation/'source',runs=a.generation/'native-pilot')
config=json.loads((a.generation/'source/reference.json').read_text())
result=run_test(project,scenario(config,a.scenario),ParameterSet(name='angular-frame-pilot',calibration=str(a.generation/'study/solidworks-assigned/calibration.json')))
print(result,flush=True)
