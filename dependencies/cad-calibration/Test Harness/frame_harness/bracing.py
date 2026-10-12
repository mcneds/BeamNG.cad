"""Geometric internal bracing applied before a generation is reviewed or fitted."""
from itertools import combinations
import numpy as np
from scipy.spatial import Delaunay,cKDTree
from .build import node_table,beam_table


def add_local_bracing(part,neighbours=16):
    nodes=node_table(part);names=sorted(nodes)
    xyz=np.array([nodes[name]['position'] for name in names])
    if len(names)<4 or np.linalg.matrix_rank(xyz-xyz.mean(axis=0))!=3:
        raise ValueError('Local frame bracing requires a volumetric node layout')
    if cKDTree(xyz).query(xyz,k=2)[0][:,1].min()<1e-8:
        raise ValueError('Local frame bracing requires distinct node positions')
    existing={tuple(sorted((edge['a'],edge['b']))) for edge in beam_table(part)}
    candidates=set()
    for tetra in Delaunay(xyz).simplices:
        candidates.update(combinations(sorted(names[i] for i in tetra),2))
    for i,near in enumerate(cKDTree(xyz).query(xyz,k=min(len(names),neighbours+1))[1]):
        candidates.update(tuple(sorted((names[i],names[j]))) for j in near if i!=j)
    added=sorted(candidates-existing)
    for a,b in added:
        part['beams'].append([a,b,dict(beamType='|NORMAL',beamSpring=450000.,beamDamp=70.,
            beamDeform=9000.,beamStrength=35000.,beamPrecompression=1.,breakGroup='',
            disableMeshBreaking=True,disableTriangleBreaking=True)])
    return dict(method='local tetrahedra and nearest-node bracing',neighbours=neighbours,
                node_count=len(names),original_beams=len(existing),added_edges=[list(e) for e in added],
                final_beams=len(existing)+len(added),properties='Initial estimates; fresh CAD calibration required')
