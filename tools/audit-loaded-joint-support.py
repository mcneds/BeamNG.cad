"""Check generated and native receiving-node masses for loaded spherical joints."""
import argparse,hashlib,json,math
from pathlib import Path


def audit(manifest,compiled=None):
    model=json.loads(manifest.read_bytes());ledger=model['numerical_mass']
    targets=ledger['nodes'];nodes=model['nodes'];rows=[]
    native=json.loads(compiled.read_bytes())['actual_nodes'] if compiled else None
    for joint in model['joints']:
        if joint['kind']!='spherical' or joint['nodes'][-1] not in targets:continue
        for name in joint['nodes']:
            target=targets.get(name,{}).get('target_kg',ledger['target_kg'])
            mass=nodes[name]['mass_kg']
            actual=native.get(name,{}).get('mass_kg') if native is not None else None
            rows.append(dict(joint=joint['id'],node=name,target_kg=target,exported_mass_kg=mass,
                             target_recorded=name in targets,exported_meets_floor=mass>=target-1e-8,
                             native_mass_kg=actual,native_matches=(isinstance(actual,(float,int)) and
                                 math.isfinite(actual) and abs(actual-mass)<max(1e-6,mass*1e-6)) if native is not None else None))
    return dict(manifest=str(manifest),manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                compiled=str(compiled) if compiled else None,policy=ledger['policy'],
                all_receivers_recorded=all(r['target_recorded'] for r in rows),
                all_receivers_meet_floor=all(r['exported_meets_floor'] for r in rows),
                native_matches=all(r['native_matches'] for r in rows) if native is not None else None,
                simulated_mass_kg=model['expected_dry_mass_kg'],cad_mass_kg=model['cad_dry_mass_kg'],
                numerical_added_mass_kg=ledger['added_mass_kg'],receivers=rows,
                scope='Load-path/mass accounting only; does not qualify physical fidelity or vehicle stability')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--compiled',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    result=audit(a.manifest,a.compiled);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='receivers'},indent=2))
