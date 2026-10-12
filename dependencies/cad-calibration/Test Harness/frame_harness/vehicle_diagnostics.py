"""Explicit interventions in owned recordings; never calibrated vehicle properties."""
import math


def balance_ballast(manifest,symmetric=False):
    """Add a small counterweight at one existing chassis node, without editing CAD.

    Include native-generated pressure-wheel mass, which is absent from the
    explicit node graph. Increasing a node's mass avoids destabilizing the
    original springs by removing mass from a force-carrying node.
    """
    nodes=manifest['nodes']
    mass=sum(v['mass_kg'] for v in nodes.values())
    moment=sum(v['mass_kg']*v['position'][0] for v in nodes.values())
    for wheel in manifest['wheels'].values():
        generated=wheel['wheel_mass_kg']
        center=sum(nodes[wheel['nodes'][k]]['position'][0] for k in ('axis_in','axis_out'))/2
        mass+=generated;moment+=generated*center
    if not math.isfinite(mass+moment) or mass<=0 or abs(mass-manifest['expected_dry_mass_kg'])>1e-5:
        raise ValueError('Cannot reconstruct diagnostic vehicle mass')
    if abs(moment)<1e-6:raise ValueError('Vehicle mass is already centered laterally')
    candidates=[n for n in manifest['chassis_nodes'] if nodes[n]['position'][0]*moment<0]
    if not candidates:raise ValueError('No chassis node opposite the mass offset')
    node=max(candidates,key=lambda n:abs(nodes[n]['position'][0]))
    added=-moment/nodes[node]['position'][0]
    if not 0<added<=mass*.05:raise ValueError('Diagnostic counterweight would exceed five percent of vehicle mass')
    weights=[dict(node=node,added_mass_kg=added,expected_node_mass_kg=nodes[node]['mass_kg']+added)]
    if symmetric:
        position=nodes[node]['position'];mirror=[-position[0],*position[1:]]
        opposite=min(manifest['chassis_nodes'],key=lambda n:sum((a-b)**2 for a,b in zip(nodes[n]['position'],mirror)))
        if max(abs(a-b) for a,b in zip(nodes[opposite]['position'],mirror))>1e-6:
            raise ValueError('Mass-matched control requires a mirrored chassis node')
        weights=[dict(node=n,added_mass_kg=added/2,expected_node_mass_kg=nodes[n]['mass_kg']+added/2) for n in (node,opposite)]
    return dict(kind='symmetric_ballast' if symmetric else 'balance_ballast',node=node,original_mass_kg=mass,
                original_node_mass_kg=nodes[node]['mass_kg'],added_mass_kg=added,
                expected_node_mass_kg=weights[0]['expected_node_mass_kg'],weights=weights,
                expected_total_mass_kg=mass+added,original_lateral_com_m=moment/mass,
                expected_lateral_com_m=moment/(mass+added) if symmetric else 0.,qualification_allowed=False)
