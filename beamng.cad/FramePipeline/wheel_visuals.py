"""Bind separate wheel bodies to native pressure-wheel rim or tire nodes.

Geometry is measured about the actual axle, independent of CAD axes and names.
Explicit WheelVisualRoles (source body ID -> rim/tire) resolve ambiguous bodies.
This changes render rows only; generated pressure-wheel physics is untouched.
"""
import numpy as np
from frame_harness.build import node_table


def render(part, corner, meshes, names, overrides=None):
    rows = [row for row in part.get('pressureWheels', [])[1:]
            if isinstance(row, list) and row[0] == corner]
    if len(rows) != 1 or len(meshes) != len(names) or len(set(names)) != len(names):
        raise ValueError('Wheel appearance requires one pressure wheel and distinct mesh names')
    row = rows[0]; nodes = node_table(part); options = row[-1]
    origin = np.asarray(nodes[row[3]]['position'], dtype=float)
    axis = np.asarray(nodes[row[4]]['position'], dtype=float) - origin
    radius, rim_radius = float(options['radius']), float(options['hubRadius'])
    if np.linalg.norm(axis) < 1e-8 or not 0 < rim_radius < radius:
        raise ValueError('Wheel appearance requires a valid axle and radii')
    axis /= np.linalg.norm(axis)
    # Keep a gap between the inferred classes. A body in that gap needs an
    # explicit role, rather than silently assigning metal to deforming rubber.
    rim_limit = rim_radius + .25 * (radius - rim_radius)
    tire_limit = rim_radius + .65 * (radius - rim_radius)
    overrides = overrides or {}; known = {item['Id'] for item, _ in meshes}
    if set(overrides) - known:
        raise ValueError('Wheel visual role names a missing CAD body')
    flex = []; report = {}
    for (item, triangles), name in zip(meshes, names):
        vertices = np.asarray(triangles, dtype=float).reshape(-1, 3) - origin
        if not len(vertices) or not np.isfinite(vertices).all():
            raise ValueError('Wheel appearance has empty or nonfinite geometry')
        radii = np.linalg.norm(vertices - np.outer(vertices @ axis, axis), axis=1)
        low, high = float(min(radii)), float(max(radii))
        role = overrides.get(item['Id'])
        if role is None:
            if high <= rim_limit: role = 'rim'
            elif high >= tire_limit and low >= .8 * rim_radius: role = 'tire'
            else:
                raise ValueError('Ambiguous wheel body '+item['Id']+': separate rim/hub and tire bodies or set WheelVisualRoles')
        if role not in ('rim', 'tire'):
            raise ValueError('Wheel visual role must be rim or tire')
        group = row[1] if role == 'rim' else row[2]
        flex.append([name, [group], []])
        report[item['Id']] = dict(mesh=name, role=role, group=group,
                                  radial_range_m=[low, high], explicit=item['Id'] in overrides)
    return flex, dict(corner=corner, bodies=report)
