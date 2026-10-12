"""Explicit generation inputs and compatibility with recorded calibration sources."""
from __future__ import annotations
import json
from pathlib import Path
from .models import TestScenario


def inputs(project):
    from .build import SOURCES, ASSETS
    path = project.source / 'generation.json'
    if not path.exists():
        return dict(sources=list(SOURCES), assets=list(ASSETS), part='mochi',
                    raw='mochi_raw.jbeam', mesh='mochi.dae', vehicle='mochi.jbeam')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('version') != 1:
        raise ValueError('Unsupported generation input manifest')
    binding=[data['render_binding']] if data.get('render_binding') else []
    if data.get('material_snapshot'): binding.append(data['material_snapshot'])
    runtime=data.get('runtime_assets',{})
    for source,target in runtime.items():
        if Path(source).name!=source or source not in data['sources'] or target!='lua/controller/'+source or not source.endswith('.lua'):
            raise ValueError('Invalid generation controller asset')
    for name in [*data['sources'], *data['assets'], data['raw'], data['mesh'], data['vehicle'], *binding]:
        if Path(name).name != name or name in ('', '.', '..'):
            raise ValueError('Generation files must be direct children of the snapshot')
    if not {data['raw'], data['mesh'], *data['assets'], *binding} <= set(data['sources']):
        raise ValueError('Generation source list omits required inputs')
    data['sources'] = sorted(set(data['sources']) | {'generation.json'})
    return data


def copy_runtime_assets(project, vehicle):
    import shutil
    for source,target in inputs(project).get('runtime_assets',{}).items():
        path=vehicle/target
        path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(project.source/source,path)


def scenario(config, name):
    if name not in config.get('fixtures',{}):
        return TestScenario.named(name)
    fixture = config['fixtures'][name]
    result = TestScenario(name, 16., 0., list(fixture['fixed_nodes']),
                          list(fixture['load_nodes']), 100., load_vectors=fixture['load_vectors'])
    result.validate()
    if not result.fixed_nodes or not result.load_nodes:
        raise ValueError('Reviewed supports and loads are required')
    return result


def verify_sources(project, hashes):
    from .build import sha256
    expected = {n: sha256(project.source/n) for n in inputs(project)['sources']}
    if hashes != expected:
        raise ValueError('Calibration source differs from this generation; recalibrate')


def load_artifact(project, artifact):
    from .build import sha256, node_table
    artifact = Path(artifact).resolve()
    spec = json.loads(artifact.read_text(encoding='utf-8-sig'))
    if spec.get('version') != 1:
        raise ValueError('Unsupported calibration artifact')
    verify_sources(project, spec['source_hashes'])
    generated = (artifact.parent/spec['vehicle_file']).resolve()
    if generated.parent != artifact.parent or sha256(generated) != spec['vehicle_sha256']:
        raise ValueError('Calibrated vehicle artifact was modified or escapes its folder')
    data = json.loads(generated.read_text())
    part = data[inputs(project)['part']]
    if any(n['options'].get('fixed') for n in node_table(part).values()):
        raise ValueError('Production calibration contains fixture pins')
    from .calibration import graph_identity, load_part
    if graph_identity(part) != graph_identity(load_part(project.source/inputs(project)['raw'], inputs(project)['part'])):
        raise ValueError('Calibration changed the generation graph')
    return spec, generated
