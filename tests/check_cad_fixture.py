"""Validate coordinates from tools/Test-Cad.ps1 against analytic fixture geometry."""
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent))
from test_preparation import prepare

def check(root):
    root=Path(root)
    packages={name:json.loads((root/name/'geometry.json').read_text()) for name in ('meshes','body-only','edited')}
    original={m['Component']:m for m in packages['meshes']['Meshes']}
    expected={'source-1':((1,3,5),(5,5,6)), 'source-2':((-4,-1,2),(-2,3,3)),
              'nested-1/source-1':((6,20,33),(10,22,34)), 'source-3':((6,6,8),(8,10,9))}
    for component,(low,high) in expected.items():
        record=original[component];tris=prepare.read_stl(root/'meshes'/record['File']);vertices=[p for tri in tris for p in tri]
        bounds=tuple(min(p[i] for p in vertices) for i in range(3)),tuple(max(p[i] for p in vertices) for i in range(3))
        assert bounds==(low,high),(component,bounds)
        volume=sum((a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6 for a,b,c in tris)
        assert math.isclose(volume,8,abs_tol=1e-5),(component,volume)
    assert len({m['Id'] for m in original.values()})==4
    for record in packages['edited']['Meshes']:
        before=original[record['Component']]
        assert record['Id']==before['Id'],'Identity changed on placement edit'
        old=prepare.read_stl(root/'meshes'/before['File']);new=prepare.read_stl(root/'edited'/record['File'])
        if record['Component']=='source-2':
            assert min(p[0] for tri in new for p in tri)==-5
        else: assert old==new
    body=packages['body-only']['Meshes'][0]
    assert body['Id']==original['source-1']['Id']
    assert (root/'body-only'/body['File']).read_bytes()==(root/'meshes'/body['File']).read_bytes()
    print('PASS analytic assembly bounds, known distances, outward mirrored volume, body/instance identity, fresh re-export')
if __name__=='__main__': check(sys.argv[1])
