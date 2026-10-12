"""Interpolate two source-identical mass allocations for a controlled native test.

Both parents must describe the same stiffness change. The shared builder still
independently screens the resulting mass matrix; this tool cannot qualify it.
"""
import argparse,hashlib,json,math
from pathlib import Path


def blend(left,right,fraction,allow_budget_repair=False):
    if not math.isfinite(fraction) or not 0<fraction<1:raise ValueError('Fraction must be strictly between zero and one')
    for key in ('baseline_jbeam_sha256','changed_constraints','factor','selection','step_limit','maximum_mass_factor'):
        if left[key]!=right[key]:raise ValueError('Parent stiffness problem differs: '+key)
    if left.get('upper_factor')!=right.get('upper_factor'):raise ValueError('Parent upper-arm factor differs')
    for parent in (left,right):
        if parent.get('status')=='offline_plan_only':continue
        if not (allow_budget_repair and parent.get('status')=='not_converged_no_candidate'
                and math.isfinite(parent.get('final_step_eigenvalue',math.inf))
                and 0 < parent['final_step_eigenvalue'] <= parent['step_limit']+1e-7
                and parent.get('added_budget_kg') is not None
                and parent['total_added_kg'] > parent['added_budget_kg']):
            raise ValueError('Feasible parent plans required; budget-only repairs require explicit opt-in')
    nodes={}
    for parent,weight in ((left,1-fraction),(right,fraction)):
        for row in parent['nodes']:
            name=row['name'];before=float(row['before_kg']);after=float(row['after_kg'])
            if not 0<before<=after or not math.isfinite(after):raise ValueError('Invalid parent mass')
            record=nodes.setdefault(name,dict(name=name,before_kg=before,added_kg=0.))
            if record['before_kg']!=before:raise ValueError('Parent node reference mass differs')
            record['added_kg']+=weight*(after-before)
    result={k:left[k] for k in ('baseline_receipt','baseline_jbeam_sha256','changed_constraints','factor','selection','step_limit','maximum_mass_factor')}
    if left.get('upper_factor') is not None:result['upper_factor']=left['upper_factor']
    for row in nodes.values():row['after_kg']=row['before_kg']+row['added_kg']
    added=sum(row['added_kg'] for row in nodes.values())
    result.update(scope=__doc__,status='offline_plan_only',nodes=list(nodes.values()),total_added_kg=added,added_budget_kg=added,
                  blend_fraction=fraction,objective_lower_bound=None,scope_limit='Convex mass interpolation for the same symmetric stiffness operator. Independent reconstruction and eigenvalue check required by the builder; no native outcome is implied.')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('left',type=Path);p.add_argument('right',type=Path);p.add_argument('--fraction',type=float,default=.5);p.add_argument('--output',type=Path,required=True);p.add_argument('--allow-budget-repair',action='store_true');a=p.parse_args()
    if a.output.exists():raise FileExistsError('Use a fresh plan path')
    data=[path.read_bytes() for path in (a.left,a.right)];r=blend(*[json.loads(value) for value in data],a.fraction,a.allow_budget_repair)
    r['budget_repair_allowed']=a.allow_budget_repair
    r['parents']=[dict(path=str(path),sha256=hashlib.sha256(value).hexdigest()) for path,value in zip((a.left,a.right),data)]
    a.output.write_text(json.dumps(r,indent=2)+'\n');print('Added mass:',r['total_added_kg'])
