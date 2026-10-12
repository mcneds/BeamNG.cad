"""Physical properties captured from native SolidWorks body/part assignments."""
from __future__ import annotations
import json
import math
from pathlib import Path

ASSIGNED_CASE = 'solidworks-assigned'
REQUIRED = ('density_kg_m3', 'young_pa', 'poisson', 'shear_pa', 'yield_pa', 'ultimate_pa')


def load_snapshot(path, body_ids=None):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if (data.get('format'), data.get('version'), data.get('units')) != ('solidworks-body-materials', 1, 'SI'):
        raise ValueError('Unsupported SolidWorks material snapshot')
    records = data.get('bodies', [])
    if not records:
        raise ValueError('SolidWorks material snapshot has no bodies')
    result = {}; errors = []
    for item in records:
        label = f"{item.get('component', '')} / {item.get('body', item.get('body_id', '?'))}"
        identity = item.get('body_id')
        if not isinstance(identity, str) or not identity or identity in result:
            raise ValueError('Missing or duplicate material body identity')
        result[identity] = item
        if item.get('error'):
            errors.append(label + ': ' + str(item['error'])); continue
        if item.get('model') != 'linear_isotropic':
            errors.append(label + ': unsupported material model'); continue
        for field in ('name', 'database', 'configuration', 'assignment', 'database_sha256', 'entry_sha256'):
            if not item.get(field): errors.append(label + ': missing material provenance ' + field)
        for field in REQUIRED:
            value = item.get(field)
            if type(value) not in (int, float) or not math.isfinite(value) or (not -1 < value < .5 if field == 'poisson' else value <= 0):
                errors.append(label + ': missing/invalid material property ' + field)
        if isinstance(item.get('ultimate_pa'), (int, float)) and isinstance(item.get('yield_pa'), (int, float)) and item['ultimate_pa'] < item['yield_pa']:
            errors.append(label + ': tensile strength is below yield strength')
    if body_ids is not None and set(result) != set(body_ids):
        errors.append('Material snapshot does not exactly cover the selected CAD bodies')
    if errors:
        raise ValueError('Correct the SolidWorks material assignments/properties before calibration:\n' + '\n'.join(errors))
    return result


def physical_properties(materials, names):
    """Keep properties per body, including bodies with the same library entry."""
    return [{key: materials[name][key] for key in REQUIRED} for name in names]
