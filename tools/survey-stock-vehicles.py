"""Read selected installed stock declarations, without extracting/modifying game files.

This is a source survey, NOT BeamNG's part/slot/variable compiler. It only reads
explicit tables from named parts; expressions and absent defaults stay unresolved.
The report must not be treated as a spawned vehicle or a handling qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile


SELECTION = {
    'utv': {
        'utv_suspension_F.jbeam': ['utv_suspension_F', 'utv_steering'],
        'utv_suspension_R.jbeam': ['utv_suspension_R'],
        'wheels/utv_wheels_F.jbeam': ['utv_wheel_aurata_14x7_F'],
        'tires/utv_tires_F.jbeam': ['utv_tire_F_30_10_14_offroad'],
    },
    'wigeon': {'wigeon_suspension_F_4w.jbeam':
               ['wigeon_suspension_F_4w', 'wigeon_steering_4w']},
    'covet': {'covet_suspension_F.jbeam': ['covet_suspension_F', 'covet_steering']},
}
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')


def clean(source):
    # Preserve source line numbers and string contents while removing comments.
    return TOKEN.sub(lambda m: m[0] if m[0].startswith('"') else
                     re.sub(r'[^\r\n]', ' ', m[0]), source)


def span(source, key, opening):
    match = re.search(r'"' + re.escape(key) + r'"\s*:\s*' +
                      re.escape(opening), source)
    if not match:
        return None
    start = match.end() - 1
    depth = 0
    closing = {'[': ']', '{': '}'}[opening]
    # Quoted expressions can contain brackets, so skip complete string tokens.
    tokens = re.finditer(r'"(?:\\.|[^"\\])*"|[\[\]{}]', source[start:])
    for token in tokens:
        if token[0] == opening:
            depth += 1
        elif token[0] == closing:
            depth -= 1
            if depth == 0:
                return start, start + token.end()
    raise ValueError('Unclosed container: ' + key)


def table(source, part, section):
    source = clean(source)
    bounds = span(source, part, '{')
    if bounds is None:
        raise ValueError('Missing part: ' + part)
    body = source[bounds[0]:bounds[1]]
    selected = span(body, section, '[')
    if selected is None:
        return []
    start = bounds[0] + selected[0] + 1
    stop = bounds[0] + selected[1] - 1
    rows = []
    decoder = json.JSONDecoder()
    while start < stop:
        while start < stop and (source[start].isspace() or source[start] == ','):
            start += 1
        if start == stop:
            break
        line = source.count('\n', 0, start) + 1
        value, end = decoder.raw_decode(source, start)
        if end > stop or not isinstance(value, (list, dict)):
            raise ValueError(f'Unsupported table row: {part}/{section}:{line}')
        rows.append((line, value))
        start = end
    return rows


def declarations(rows):
    if not rows:
        return []
    header = rows[0][1]
    if not isinstance(header, list) or not all(isinstance(x, str) for x in header):
        raise ValueError('Expected table header')
    options = {}
    result = []
    for line, row in rows[1:]:
        if isinstance(row, dict):
            options.update(row)
            continue
        values = row[:-1] if row and isinstance(row[-1], dict) else row
        inline = row[-1] if row and isinstance(row[-1], dict) else {}
        if len(values) > len(header):
            raise ValueError(f'Unmapped columns at line {line}')
        result.append({'line': line, 'values': options | dict(zip(header, values)) | inline})
    return result


def summarize(path):
    manifest = json.loads(path.read_text(encoding='utf-8'))
    jbeam = path.parent / manifest['vehicle_directory'] / manifest['main_jbeam']
    part = json.loads(jbeam.read_text(encoding='utf-8'))[manifest['main_part']]
    contract = manifest['steering_contract']
    wanted = set(contract['housing_nodes'] + contract['slider_nodes'])
    wanted.update(c + '_' + n for c in ('FL', 'FR') for n in
                  ('upper_ball', 'lower_ball', 'tie_outer', 'tie_inner'))
    nodes = declarations(list(enumerate(part['nodes'])))
    return {
        'manifest': str(path.resolve()),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'jbeam_sha256': hashlib.sha256(jbeam.read_bytes()).hexdigest(),
        'scope': 'Exported values; not runtime-compiled wheel graph',
        'expected_dry_mass_kg': manifest['expected_dry_mass_kg'],
        'hardpoint_nodes': [r['values'] for r in nodes if r['values']['id'] in wanted],
        'hydros': [r['values'] for r in declarations(list(enumerate(part['hydros'])))],
        'slidenodes': [r['values'] for r in declarations(list(enumerate(part['slidenodes'])))],
    }


def survey(game):
    result = []
    for vehicle, files in SELECTION.items():
        archive = game / 'content/vehicles' / (vehicle + '.zip')
        with ZipFile(archive) as stock:
            for filename, parts in files.items():
                entry = 'vehicles/' + vehicle + '/' + filename
                data = stock.read(entry)
                source = data.decode('utf-8-sig')
                for part in parts:
                    tables = {}
                    option_rows = {}
                    for section in ('nodes', 'hydros', 'slidenodes', 'pressureWheels'):
                        raw = table(source, part, section)
                        rows = declarations(raw)
                        if rows:
                            tables[section] = rows
                        # Wheel/tire parts can contribute only inherited options;
                        # omitting these would misleadingly imply no pressure wheel.
                        if section == 'pressureWheels' and raw:
                            option_rows[section] = [dict(line=line, values=row)
                                                    for line, row in raw if isinstance(row, dict)]
                    result.append(dict(vehicle=vehicle, archive=str(archive), entry=entry,
                                       part=part, sha256=hashlib.sha256(data).hexdigest(),
                                       tables=tables, option_rows=option_rows))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = dict(scope=__doc__, stock_live_measurements=False,
                  stock=survey(args.game), candidate=summarize(args.candidate))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    for part in report['stock']:
        print(part['part'], {k: len(v) for k, v in part['tables'].items()})
    print(args.output)
