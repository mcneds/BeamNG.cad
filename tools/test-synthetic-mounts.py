"""Run the existing settle/load/release contract on a complete vehicle export."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from build_static_frame import completed_build
from frame_harness.component_tests import verify,run_components
from frame_harness.models import HarnessProject
from frame_harness.session import DriveSession
from frame_harness.build import write_json

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('manifest',type=Path)
p.add_argument('--game',default='D:/SteamLibrary/steamapps/common/BeamNG.drive')
p.add_argument('--profile',default='H:/BeamNGCadHarness/synthetic-mvp-20261007')
p.add_argument('--save-report',action='store_true')
p.add_argument('--park-probe',action='store_true',help='One engine-off Park settling run, separate from mount qualification')
a=p.parse_args()
completed_build(a.manifest.parent/'static_frame_build.json')
if a.park_probe:
    project=HarnessProject(game=Path(a.game),userpath=Path(a.profile),runs=a.manifest.parent/'tests')
    with DriveSession(project,'vehicle') as session:
        result=run_components(a.manifest,'component_settle',session,gearbox_mode='park')
    if result['status']=='passed' and not a.save_report:
        from frame_harness.component_tests import compact_success
        compact_success(result['directory'])
    write_json(a.manifest.parent/'park-verification.json',result)
else:result=verify(a.manifest,a.game,a.profile,repeats=3,save_report=a.save_report)
print('NATIVE_MOUNT_RESULT '+result['status'],flush=True)
raise SystemExit(0 if result['status']=='passed' else 1)
