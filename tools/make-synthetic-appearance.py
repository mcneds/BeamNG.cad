"""Independent native CAD recipe used only to replace an MVP's appearance."""
import argparse,copy,hashlib,json,math
from pathlib import Path
import numpy as np

p=argparse.ArgumentParser();p.add_argument('source_recipe',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
source=json.loads(a.source_recipe.read_text());result=copy.deepcopy(source)
result['variant']='appearance';result['source']='Deliberately different native CAD; no physical properties are applied during an appearance swap'
result['components']=[v for v in result['components'] if v['id'] in ('engine','panel_floor','panel_nose')]
for item in result['components']:
    shape=item['primitives'][0]
    if item['id']=='engine':
        center=np.array(shape['center']);shape['size']=[.32,.23,.17]
        cover=copy.deepcopy(shape);cover['center']=(center+[0,0,.12]).tolist();cover['size']=[.20,.15,.07]
        item['primitives'].append(cover)
    elif item['id']=='panel_floor':shape['size']=[.68,source['dimensions']['wheelbase']*.92,0]
    else:shape['size']=[.64,.45,0];shape['center'][1]-=.03
    for primitive in item['primitives']:
        primitive['analytic_volume_m3']=float(np.prod(primitive['size']))
    item['analytic_volume_m3']=sum(v['analytic_volume_m3'] for v in item['primitives'])
result.pop('recipe_sha256',None);result['recipe_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n')
