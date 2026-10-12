"""Run the checked-in suites, never an editable install from another checkout."""
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
dependency=root/'dependencies/cad-calibration'
paths=[str(root/'beamng.cad/FramePipeline'),str(dependency/'Test Harness'),str(dependency/'Vehicle Wizard')]
for tests in (root/'tests',dependency/'Test Harness/tests',dependency/'Vehicle Wizard/tests'):
    code=f"import sys,unittest;sys.path[:0]={paths!r};suite=unittest.defaultTestLoader.discover({str(tests)!r});result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())"
    result=subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=root)
    if result.returncode:sys.exit(result.returncode)
