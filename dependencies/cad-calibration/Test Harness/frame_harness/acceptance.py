"""Qualification is evidence-based and separate from successful recording."""
from __future__ import annotations
import json
import shutil
from pathlib import Path
import numpy as np
from .build import sha256, write_json


def latest_runs(state):
    return {r['key']: r for r in state.get('runs', [])}


def capture_evidence(state):
    """Hash actual rendered images; a replay of node coordinates is not a mesh review."""
    captures = {}
    for key, record in latest_runs(state).items():
        if not ('mesh-cut' in key or '-damage-' in key):
            continue
        run = Path(record['path'])
        location = run/'telemetry_location.json'
        if not location.exists():
            continue
        directory = run/json.loads(location.read_text())['directory']
        for path in sorted(directory.glob('*.png')):
            captures[f'{key}/{path.name}'] = {'path': str(path.resolve()), 'sha256': sha256(path)}
    return captures


def evaluate_acceptance(state, output):
    config = state['config']; active = latest_runs(state)
    captures = capture_evidence(state)
    write_json(output/'mesh-review-evidence.json', captures)
    review_path = output/'mesh-review.json'
    review = json.loads(review_path.read_text()) if review_path.exists() else {}
    expected_hashes = {key: value['sha256'] for key, value in captures.items()}
    review_current = bool(expected_hashes and review.get('capture_sha256') == expected_hashes and review.get('notes'))
    cuts = [active.get(f'mesh-cut-{f}', {}) for f in (.35, .65)]
    cuts_ok = all(r.get('status') == 'completed' and r.get('metrics', {}).get('capture_complete') and
                  r.get('metrics', {}).get('final_components', 0) >= 2 for r in cuts)
    results = {}
    for name, report in state['candidates'].items():
        reasons = []; checks = {}; rates = {}
        if not state.get('instrument_accepted'):
            reasons.append('Instrument validation not passed')
        if not report['offline_accepted']:
            reasons.append('CAD/reference/mass or offline elastic/yield criteria not met')
        if report.get('local_mount_reference_qualified') is False:
            reasons.append('Local mounting stiffness differs from the CAD reference; numerical connection fit does not qualify physical stiffness')
        if report.get('angular_constraints') and not report['angular_constraints'].get('damage_telemetry_qualified'):
            reasons.append('Native torsion-bar damage telemetry is not qualified')
        for base in ('idle', 'flex', 'torsion'):
            records = [active.get(f'{name}-{base}'+(f'-{i}' if i > 1 else ''), {}) for i in (1, 2, 3)]
            complete = all(r.get('status') == 'completed' for r in records)
            complete = complete and len({r.get('path') for r in records}) == 3
            checks[base+'_three_repeats'] = complete
            if not complete:
                reasons.append(base+': three valid independent repeats required')
                continue
            for r in records:
                m = r['metrics']
                if abs(m['measured_mass_kg']/report['mass']['target_mass_kg']-1) > .001:
                    reasons.append('Live mass differs by more than 0.1%')
                if m.get('broken_beams', 0) or m.get('max_rest_length_change_m', 0) > 1e-5:
                    reasons.append(base+': damage in a nondestructive test')
                if base == 'idle':
                    if m['final_shape_rms_m'] > .005 or m['tail_world_speed_rms_m_s'] > .05:
                        reasons.append('Idle shape/motion limits exceeded (5 mm, 0.05 m/s)')
                else:
                    ref = report['responses'][base]['reference']
                    if not ref or not m.get('hold_settled') or abs(m['held_deflection_m']/(100*ref['compliance_m_n'])-1) > .1:
                        reasons.append(base+': settled live compliance differs from reference by more than 10%')
        for base in ('flex', 'torsion'):
            fast = active.get(f'{name}-{base}-damage-{config["ramp_seconds"]:g}', {})
            slow = active.get(f'{name}-{base}-damage-{config["slow_ramp_seconds"]:g}', {})
            repeats = [slow, *[active.get(f'{name}-{base}-damage-{i}', {}) for i in (2, 3)]]
            if any(r.get('status') != 'completed' for r in [fast, *repeats]):
                reasons.append(base+': valid progressive tests at both rates and three slow repeats required')
            if len({r.get('path') for r in repeats}) != 3:
                reasons.append(base+': damage confirmations must be independent recordings')
            ref = report['responses'][base]['reference']
            for r in repeats:
                y = r.get('metrics', {}).get('first_yield_external_force_n')
                if not ref or y is None or abs(y/ref['first_yield_force_n']-1) > .15:
                    reasons.append(base+': measured first yield missing or differs from reference by more than 15%')
            for metric in ('first_yield_external_force_n', 'first_break_external_force_n'):
                a = fast.get('metrics', {}).get(metric); b = slow.get('metrics', {}).get(metric)
                delta = abs(a/b-1) if a is not None and b else None
                rates[base+'_'+metric] = delta
                if delta is None or delta > .05:
                    reasons.append(base+': threshold missing or loading-rate sensitivity exceeds 5%')
                values = [r.get('metrics', {}).get(metric) for r in repeats]
                variation = float(np.ptp(values)/np.mean(values)) if all(v and v > 0 for v in values) else None
                checks[base+'_'+metric+'_repeat_range_relative'] = variation
                if variation is None or variation > .05:
                    reasons.append(base+': damage threshold repeat range missing or exceeds 5%')
        relevant = [r for r in active.values() if r.get('candidate') == name]
        if any(r.get('status') != 'completed' for r in relevant):
            reasons.append('Live test failed or measurement invalid')
        if any(r.get('metrics', {}).get('mesh_load_valid') is False for r in relevant):
            reasons.append('Engine reported missing or invalid flexbody meshes')
        if any(r.get('metrics', {}).get('capture_complete') is False for r in relevant):
            reasons.append('Requested rendered captures incomplete')
        if any(r.get('metrics',{}).get('render_controller_valid') is False or
               r.get('metrics',{}).get('mesh_association_audit',{}).get('visible_groups_spanning_separated_components',0)>0
               for r in relevant):
            reasons.append('Visible render binding spans separated components or its controller evidence is invalid')
        if not cuts_ok:
            reasons.append('Both controlled cuts need valid separation telemetry and rendered captures')
        if not review_current:
            reasons.append('Rendered mesh review missing or stale')
        elif review.get('cases', {}).get(name) is not True:
            reasons.append('Rendered mesh review failed')
        results[name] = {'accepted': not reasons, 'reasons': sorted(set(reasons)), 'checks': checks,
                         'rate_relative_changes': rates, 'mesh_review_current': review_current,
                         'mesh_review_notes': review.get('notes') if review_current else None,
                         'qualification_scope': ('Stated equivalent-model tests using captured SolidWorks assignments; physical material condition and ductile rupture remain unvalidated' if config.get('material_source')=='solidworks' else 'Stated equivalent-model tests; unknown heat treatment and ductile rupture remain unvalidated')}
    return results


def export_qualified(output, state):
    for name, decision in state.get('acceptance', {}).items():
        if decision['accepted']:
            target=output/name/'qualified-mod'
            shutil.copytree(output/name/'diagnostic-mod',target,dirs_exist_ok=True)
            write_json(target/'qualification.json',decision)
            shutil.make_archive(str(target),'zip',target)


def review_calibration(output, decisions, notes):
    """Record an actual image inspection, then recompute qualification without rerunning Drive."""
    from .calibration import render_calibration
    output = output.resolve(); state = json.loads((output/'calibration-study.json').read_text())
    if set(decisions) != set(state['candidates']) or any(type(v) is not bool for v in decisions.values()) or not notes.strip():
        raise ValueError('A boolean visual decision for each case and review notes are required')
    captures = capture_evidence(state)
    if not captures:
        raise ValueError('No rendered mesh evidence exists')
    write_json(output/'mesh-review.json', {'capture_sha256': {k:v['sha256'] for k,v in captures.items()},
                                         'cases': decisions, 'notes': notes})
    state['acceptance'] = evaluate_acceptance(state, output)
    state['status'] = 'completed' if all(r['accepted'] for r in state['acceptance'].values()) else 'completed_with_limitations'
    export_qualified(output,state)
    write_json(output/'calibration-study.json', state); render_calibration(output, state)
    return state
