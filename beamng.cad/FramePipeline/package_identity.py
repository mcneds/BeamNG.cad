"""Namespaced export of immutable, calibrated frame packages.

Calibration keeps its original identifiers. Export changes only identifiers and
asset references, and records an invertible map plus the original JBeam hash.
"""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET


def validate_identity(value):
    if not isinstance(value, dict) or not re.fullmatch(r'[0-9a-f]{32}', value.get('id', '')):
        raise ValueError('Invalid project identity')
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,45}', value.get('namespace', '')):
        raise ValueError('Invalid package namespace')
    return value


def layout(record):
    identity = record.get('identity')
    if identity:
        validate_identity(identity)
        model = identity['namespace']
        return model, model + '.zip', model + '.jbeam', model + '.dae'
    return 'mochi', 'ak1di_mochi.zip', 'mochi.jbeam', 'mochi.dae'


def remap(value, mapping, old_model, new_model):
    if isinstance(value, dict):
        return {mapping.get(k, k): remap(v, mapping, old_model, new_model) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v, mapping, old_model, new_model) for v in value]
    if isinstance(value, str):
        if value in mapping:
            return mapping[value]
        prefix = '/vehicles/' + old_model + '/'
        if value.startswith(prefix):
            return '/vehicles/' + new_model + '/' + value[len(prefix):]
    return value


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def export(contents, record, identity):
    validate_identity(identity)
    if record.get('identity'):
        if record['identity'] != identity:
            raise ValueError('This build belongs to another project. Generate a build for this project.')
        return contents, record, None
    old_model, _, jbeam, dae = layout(record)
    model = identity['namespace']; prefix = 'vehicles/' + old_model + '/'
    part_data = json.loads(contents[prefix + jbeam])
    root = ET.fromstring(contents[prefix + dae])
    if root.tag.startswith('{'): ET.register_namespace('', root.tag[1:].split('}')[0])
    materials = json.loads(contents[prefix + 'main.materials.json'])
    identifiers = set(part_data)
    for part in part_data.values():
        for row in part.get('nodes', [])[1:]:
            if isinstance(row, list): identifiers.add(row[0])
        for section, fields in [('nodes', ('group',)), ('beams', ('breakGroup',)), ('triangles', ('group',))]:
            for row in part.get(section, [])[1:]:
                opts = row if isinstance(row, dict) else row[-1] if isinstance(row, list) and isinstance(row[-1], dict) else {}
                for field in fields:
                    values = opts.get(field, [])
                    identifiers.update([values] if isinstance(values, str) and values else values or [])
        for row in part.get('flexbodies', [])[1:]:
            if isinstance(row, list): identifiers.add(row[0])
    for element in root.iter():
        for key in ('id', 'name', 'symbol', 'material'):
            if element.get(key): identifiers.add(element.get(key))
    identifiers.update(materials)
    for material in materials.values():
        if isinstance(material, dict):
            identifiers.update(material[k] for k in ('name', 'mapTo') if material.get(k))
    # Main identity is exact; all other identifiers use a disjoint suffix.
    mapping = {key: model if key == old_model else model + '__' + key for key in sorted(identifiers)}
    if len(set(mapping.values())) != len(mapping): raise ValueError('Export identifier collision')
    for element in root.iter():
        for key, value in list(element.attrib.items()):
            if key in ('id', 'name', 'symbol', 'material'): element.set(key, mapping.get(value, value))
            elif value.startswith('#'): element.set(key, '#' + mapping.get(value[1:], value[1:]))
        # COLLADA image IDs are also referenced as element text by surfaces.
        if element.tag.endswith('}init_from') and element.text in mapping:element.text=mapping[element.text]
    renamed = {}
    for path, data in contents.items():
        relative = path[len(prefix):]
        target = 'vehicles/' + model + '/' + ({jbeam: model + '.jbeam', dae: model + '.dae'}.get(relative, relative))
        if relative == jbeam: data = encoded(remap(part_data, mapping, old_model, model))
        elif relative == dae: data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        elif relative == 'main.materials.json': data = encoded(remap(materials, mapping, old_model, model))
        elif relative.endswith('.pc'):
            config = remap(json.loads(data), mapping, old_model, model)
            config['model'] = model
            data = encoded(config)
        renamed[target] = data
    exported = renamed['vehicles/' + model + '/' + model + '.jbeam']
    result = dict(record, version=2, identity=identity, zip_file='work/dist/' + model + '.zip',
                  identity_export={'version': 1, 'mapping': mapping, 'source_model': old_model,
                                   'source_jbeam': 'identity/source.jbeam',
                                   'source_sha256': hashlib.sha256(contents[prefix+jbeam]).hexdigest(),
                                   'exported_sha256': hashlib.sha256(exported).hexdigest()})
    verify_export(result, contents[prefix+jbeam], exported)
    return renamed, result, contents[prefix+jbeam]


def verify_export(record, source, exported):
    spec = record['identity_export']; model = layout(record)[0]
    if hashlib.sha256(source).hexdigest() != spec['source_sha256']:
        raise ValueError('Original export JBeam changed')
    if hashlib.sha256(exported).hexdigest() != spec['exported_sha256']:
        raise ValueError('Exported JBeam changed')
    mapping = spec['mapping']
    if len(set(mapping.values())) != len(mapping): raise ValueError('Noninvertible identifier mapping')
    expected = remap(json.loads(source), mapping, spec['source_model'], model)
    if expected != json.loads(exported): raise ValueError('Namespaced export changed physical data')
    if record.get('calibration') and spec['source_sha256'] != record['calibration']['vehicle_sha256']:
        raise ValueError('Export source differs from calibrated artifact')
