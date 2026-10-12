"""Copy unmodified native captures and publish their provenance with HTML labels."""
import argparse,hashlib,json,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('artifacts',type=Path)
p.add_argument('--vehicle-capture',default='primary-vehicle-bt/tests/20261007T161025-88335a-settle/final.png')
p.add_argument('--alternate-capture',default='variant-vehicle-w/tests/20261007T202451-58a0f3-settle/final.png')
p.add_argument('--workflow-capture',default='native-template-ui-h/component-workflow.png')
p.add_argument('--reference-capture',default='native-template-ui-h/reference-skeleton.png')
a=p.parse_args()
root=Path(__file__).resolve().parents[1];assets=root/'docs/images';assets.mkdir(exist_ok=True)
sources={
 'synthetic-native-cad.png':'cad-preview-a/baseline-native-viewport.png',
 'synthetic-native-drive.png':a.vehicle_capture,
 'synthetic-alternate-drive.png':a.alternate_capture,
 'synthetic-template-ui.png':a.workflow_capture,
 'reference-skeleton.png':a.reference_capture,
 'synthetic-appearance-cad.png':'appearance-cad-a/native-viewport.png'}
evidence={}
for name,relative in sources.items():
    source=a.artifacts/relative;shutil.copyfile(source,assets/name)
    evidence[name]=dict(source=relative,sha256=hashlib.sha256(source.read_bytes()).hexdigest(),altered=False)
evidence['scope']='Native synthetic CAD and BeamNG captures. No full vehicle acceptance or real vehicle qualification is established by these pictures; consult the implementation journal and recorded acceptance.'
(assets/'synthetic-captures.json').write_text(json.dumps(evidence,indent=2)+'\n')
