"""Distributed constraints for explicitly fixed, non-breakaway structures.

Locating three mount nodes does not make a deformable, lightly discretized
body rigid. An explicit rigid attachment constrains every mass node to its
parent. These are numerical constraints, not additional physical welds or bolts.
"""
import itertools
import numpy as np
from frame_harness.build import node_table, beam_table


def attach(part, children, parents, frequency=160.):
    nodes = node_table(part)
    children, parents = sorted(set(children)), sorted(set(parents))
    if not children or len(parents) < 4 or set(children) & set(parents):
        raise ValueError('Fixed structures need disjoint child and parent nodes')
    if not 0 < frequency <= 260:
        raise ValueError('Fixed structure frequency must be in (0,260] Hz')
    existing = {frozenset((b['a'], b['b'])) for b in beam_table(part)}
    xyz = np.array([nodes[n]['position'] for n in parents])
    parent_masses=np.array([float(nodes[n]['options']['nodeWeight']) for n in parents])
    rows, checks = [], []
    for child in children:
        delta = xyz - nodes[child]['position']
        lengths = np.linalg.norm(delta, axis=1)
        valid = [i for i in np.flatnonzero(lengths > 1e-5)
                 if frozenset((child, parents[i])) not in existing]
        mass = float(nodes[child]['options']['nodeWeight'])
        reduced=mass*parent_masses/(mass+parent_masses)
        # Nearby tiny masses cannot sustain the requested stiffness at the
        # physics timestep. Include load-bearing candidates and score achievable
        # directional support, not geometric proximity alone.
        nearby=sorted(valid,key=lambda i:(lengths[i],parents[i]))[:12]
        supported=sorted(valid,key=lambda i:(-reduced[i]/lengths[i],parents[i]))[:8]
        pool=sorted(set(nearby+supported))
        candidates = np.array(list(itertools.combinations(pool, 4)))
        if not len(candidates):raise ValueError('Insufficient distinct fixed supports')
        directions = delta[candidates] / lengths[candidates, None]
        eigen = np.linalg.eigvalsh(np.einsum('nki,nkj->nij', directions, directions))
        supported_eigen=np.linalg.eigvalsh(np.einsum('nki,nkj,nk->nij',directions,directions,reduced[candidates]))
        score=supported_eigen[:,0]/np.mean(lengths[candidates],axis=1)
        score[eigen[:,0]<.05]=-np.inf
        chosen = int(np.argmax(score))
        if eigen[chosen, 0] < .05:raise ValueError('Fixed supports are nearly coplanar: '+child)
        spring = mass * (2*np.pi*frequency)**2 / 4
        damp = .1 * mass * 2*np.pi*frequency / 4
        # Existing constraints remain unchanged. Duplicate edges must not double
        # count stiffness, so select other supports if the best set overlaps.
        selected = candidates[chosen]
        for i in selected:
            if frozenset((child, parents[i])) in existing:
                raise ValueError('Fixed support overlaps an existing beam: '+child)
            rows.append([child, parents[i], dict(beamSpring=spring, beamDamp=damp,
                beamDeform=1e30, beamStrength=1e30, beamPrecompression=1,
                beamType='|NORMAL', breakGroup='', disableMeshBreaking=True,
                disableTriangleBreaking=True, dampCutoffHz=0)])
        checks.append(dict(node=child, minimum_direction_eigenvalue=float(eigen[chosen, 0]),
                           selected_parents=[parents[i] for i in selected],
                           minimum_mass_weighted_direction_eigenvalue=float(supported_eigen[chosen,0]),
                           isolated_gravity_deflection_bound_m=9.81*mass/(spring*eigen[chosen, 0])))
    part['beams'].extend(rows)
    return rows, dict(nodes=children, parents=parents, added_beams=len(rows),
        frequency_hz=frequency, constraints=checks,
        scope='Explicit rigid attachment; retains mass, no breakaway or articulated motion')
