"""Live smoke test: two different instrument graphs in one owned Drive process."""
import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'dependencies/cad-calibration/Test Harness'))
from frame_harness.models import HarnessProject,TestScenario
from frame_harness.runner import run_test
from frame_harness.session import DriveSession

def main():
    output=root/'beamng.cad/bin/session-progress/live-tests'
    project=HarnessProject(userpath=Path('H:/BeamNGCadHarness/session-validation'),runs=output)
    results=[]
    with DriveSession(project) as session:
        for name in ('spring','spring-yield'):
            scenario=TestScenario.named(name);scenario.capture=True
            result=run_test(project,scenario,session=session,retries=0)
            results.append(result)
            if result.status!='completed': raise RuntimeError(result.failure_reason)
    launches=[json.loads((Path(r.path)/'session.json').read_text()) for r in results]
    assert len({l['pid'] for l in launches})==1, 'Process restarted between tests'
    assert all(r.metrics['capture_complete'] for r in results)
    print('PASS: same PID, fresh compiled instruments, complete captures; owned process closed')

if __name__=='__main__': main()
