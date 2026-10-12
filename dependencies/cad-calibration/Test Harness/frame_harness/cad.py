"""CAD surface audit and section measurements. Never substitutes the wrapped hull."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial import cKDTree


@dataclass
class Body:
    name: str
    vertices: np.ndarray
    faces: np.ndarray


def read_bodies(path: Path):
    root = ET.parse(path).getroot()
    ns = {"c": root.tag.split("}")[0][1:]}
    unit = root.find("c:asset/c:unit", ns)
    scale = float(unit.get("meter", "1")) if unit is not None else 1.
    axis = root.findtext("c:asset/c:up_axis", "Z_UP", ns)
    if axis != "Z_UP":
        raise ValueError("CAD calibration requires the prepared Z_UP DAE")
    geometries = {}
    for geometry in root.findall("c:library_geometries/c:geometry", ns):
        mesh = geometry.find("c:mesh", ns)
        if mesh is None:
            continue
        src = mesh.find("c:vertices/c:input[@semantic='POSITION']", ns).get("source")[1:]
        element = next(e for e in mesh.findall("c:source", ns) if e.get("id") == src)
        accessor = element.find("c:technique_common/c:accessor", ns)
        values = np.fromstring(element.findtext("c:float_array", namespaces=ns), sep=" ")
        offset, stride, count = (int(accessor.get(k, d)) for k, d in (("offset", "0"), ("stride", "3"), ("count", "0")))
        vertices = values[offset:offset+count*stride].reshape(count, stride)[:, :3]
        faces = []
        for primitive in mesh:
            kind = primitive.tag.split("}")[-1]
            if kind not in ("triangles", "polylist"):
                if kind in ("polygons", "trifans", "tristrips"):
                    raise ValueError(f"Unsupported CAD primitive {kind}: triangulate the export")
                continue
            inputs = primitive.findall("c:input", ns)
            stride = max(int(e.get("offset", "0")) for e in inputs)+1
            vertex_offset = next(int(e.get("offset", "0")) for e in inputs if e.get("semantic") == "VERTEX")
            indices = np.fromstring(primitive.findtext("c:p", namespaces=ns), sep=" ", dtype=int).reshape(-1, stride)[:, vertex_offset]
            counts = [3]*(len(indices)//3) if kind == "triangles" else list(map(int, primitive.findtext("c:vcount", namespaces=ns).split()))
            at = 0
            for n in counts:
                polygon = indices[at:at+n]; at += n
                faces.extend((polygon[0], polygon[i], polygon[i+1]) for i in range(1, n-1))
        geometries[geometry.get("id")] = (vertices, np.asarray(faces, dtype=int))
    bodies = []
    def visit(node, parent):
        transform = np.eye(4)
        for e in node:
            kind = e.tag.split("}")[-1]
            if kind not in ("matrix", "translate", "scale", "rotate"):
                continue
            v = np.fromstring(e.text, sep=" "); m = np.eye(4)
            if kind == "matrix":
                # Prepared exports and the original associator use row-major transforms.
                m = v.reshape(4, 4)
            elif kind == "translate":
                m[:3, 3] = v
            elif kind == "scale":
                m[:3, :3] = np.diag(v)
            else:
                from scipy.spatial.transform import Rotation
                m[:3, :3] = Rotation.from_rotvec(v[:3]/np.linalg.norm(v[:3])*np.deg2rad(v[3])).as_matrix()
            transform = transform @ m
        world = parent @ transform
        for inst in node.findall("c:instance_geometry", ns):
            vertices, faces = geometries[inst.get("url")[1:]]
            points = np.column_stack((vertices, np.ones(len(vertices)))) @ world.T
            points = points[:, :3]/points[:, 3:]*scale
            if np.linalg.det(world[:3, :3]) < 0:
                faces = faces[:, ::-1]
            bodies.append(Body(node.get("name") or node.get("id"), points, faces.copy()))
        for child in node.findall("c:node", ns):
            visit(child, world)
    scene_id = root.find("c:scene/c:instance_visual_scene", ns).get("url")[1:]
    scene = next(e for e in root.findall("c:library_visual_scenes/c:visual_scene", ns) if e.get("id") == scene_id)
    for node in scene.findall("c:node", ns):
        visit(node, np.eye(4))
    if not bodies or len({b.name for b in bodies}) != len(bodies):
        raise ValueError("CAD body names must be nonempty and unique")
    return bodies


def welded(body, tolerance):
    vertices = body.vertices
    parent = np.arange(len(vertices))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for a, b in sorted(cKDTree(vertices).query_pairs(tolerance)):
        parent[find(b)] = find(a)
    ids = np.array([find(i) for i in range(len(vertices))])
    roots, inverse = np.unique(ids, return_inverse=True)
    faces = inverse[body.faces]
    good = (faces[:, 0] != faces[:, 1]) & (faces[:, 0] != faces[:, 2]) & (faces[:, 1] != faces[:, 2])
    tri = vertices[roots][faces]
    cross = np.linalg.norm(np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]), axis=1)
    edge_product = np.linalg.norm(tri[:, 1]-tri[:, 0], axis=1)*np.linalg.norm(tri[:, 2]-tri[:, 0], axis=1)
    good &= cross > np.maximum(1e-12, 1e-5*edge_product)
    return Body(body.name, vertices[roots], faces[good])


def boundary_edges(body):
    f = body.faces
    directed = np.concatenate((f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]))
    edges, ids, counts = np.unique(np.sort(directed, axis=1), axis=0, return_inverse=True, return_counts=True)
    balance = np.bincount(ids, weights=np.where(directed[:, 0] < directed[:, 1], 1, -1))
    return edges[(counts != 2) | (balance != 0)]


def volume_properties(body):
    """Exact signed tetrahedron integrals for a closed, consistently oriented surface."""
    origin = body.vertices.mean(axis=0)
    t = body.vertices[body.faces]-origin
    dv = np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2]))/6
    sign = 1 if dv.sum() > 0 else -1
    dv *= sign
    volume = float(dv.sum())
    if volume <= 1e-14:
        raise ValueError(f"No material volume: {body.name}")
    sums = t.sum(axis=1)
    center = (dv[:, None]*sums).sum(axis=0)/(4*volume)
    second = np.einsum("t,ti,tj->ij", dv/20, sums, sums)+np.einsum("t,tki,tkj->ij", dv/20, t, t)
    second -= volume*np.outer(center, center)
    inertia = np.eye(3)*np.trace(second)-second
    if np.linalg.eigvalsh(inertia).min() <= 0:
        raise ValueError(f"Invalid material inertia: {body.name}")
    return {"volume_m3": volume, "center_m": (origin+center).tolist(), "inertia_per_density": inertia.tolist()}


def audit_body(body):
    initial = None
    original_volume=volume_properties(body)['volume_m3']
    for tolerance in (1e-8, 1e-7, 1e-6, 1e-5, 2e-5, 5e-5):
        candidate = welded(body, tolerance)
        # Coincident triangles with opposite winding contribute zero signed
        # volume and are export sheets, not material boundary. Cancel only exact
        # pairs; same-winding duplicates or arbitrary overlapping faces remain errors.
        canonical=np.sort(candidate.faces,axis=1)
        _,inverse,counts=np.unique(canonical,axis=0,return_inverse=True,return_counts=True)
        keep=np.ones(len(candidate.faces),dtype=bool);cancelled=0
        for group in np.flatnonzero(counts==2):
            indices=np.flatnonzero(inverse==group);a,b=candidate.faces[indices]
            parity=lambda f:sum(f[i]>f[j] for i in range(3) for j in range(i+1,3))%2
            if parity(a)!=parity(b):keep[indices]=False;cancelled+=2
        candidate=Body(body.name,candidate.vertices,candidate.faces[keep])
        # Export artifacts can form isolated fins: two open edges and one edge
        # shared by three faces. Remove only these dangling facets, never cap holes.
        removed_fins = 0
        for _ in range(8):
            f = candidate.faces
            edges = np.sort(np.stack((f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]), axis=1), axis=2)
            _, inv, counts = np.unique(edges.reshape(-1, 2), axis=0, return_inverse=True, return_counts=True)
            multiplicity = counts[inv].reshape(-1, 3)
            fin = (np.sum(multiplicity == 1, axis=1) == 2) & (np.max(multiplicity, axis=1) >= 3)
            if not np.any(fin):
                break
            proposed = Body(body.name, candidate.vertices, f[~fin])
            before = volume_properties(candidate)["volume_m3"]
            after = volume_properties(proposed)["volume_m3"]
            if abs(after/before-1) > .005:
                break
            removed_fins += int(fin.sum()); candidate = proposed
        bad = boundary_edges(candidate)
        properties = volume_properties(candidate)
        if initial is None:
            initial = properties["volume_m3"]
        if not len(bad) and abs(properties["volume_m3"]/original_volume-1) < .005:
            return candidate, {"name": body.name, "valid": True, "seam_weld_m": tolerance,
                               "removed_export_facets": len(body.faces)-len(candidate.faces), "removed_fins": removed_fins,
                               "cancelled_opposite_facets":cancelled,
                               "original_signed_volume_m3":original_volume,"repair_volume_relative_change":properties['volume_m3']/original_volume-1,
                               "boundary_edges": 0, **properties}
    return candidate, {"name": body.name, "valid": False, "seam_weld_m": tolerance,
                       "boundary_edges": len(bad), "reason": "Open/nonmanifold or inconsistently oriented CAD surface",
                       "provisional_properties": properties}


def section_loops(body, center, axes):
    local = (body.vertices-center) @ axes.T
    triangles=local[body.faces]; following=np.roll(triangles,-1,axis=1)
    crosses=(triangles[:,:,0]<0)!=(following[:,:,0]<0)
    valid=crosses.sum(axis=1)==2
    a=triangles[valid][crosses[valid]]; b=following[valid][crosses[valid]]
    hits=(a+(b-a)*(-a[:,0]/(b[:,0]-a[:,0]))[:,None])[:,1:]
    segments=hits.reshape(-1,2,2)
    segments=segments[np.linalg.norm(segments[:,0]-segments[:,1],axis=1)>1e-9]
    if not len(segments):
        raise ValueError("Empty CAD section")
    points = np.asarray(segments).reshape(-1, 2)
    # Plane intersections share original triangle edges; quantization only joins numerical seams.
    keys, inverse = np.unique(np.round(points, 7), axis=0, return_inverse=True)
    edges = {tuple(sorted(e)) for e in inverse.reshape(-1, 2) if e[0] != e[1]}
    neighbors = {i: set() for i in range(len(keys))}
    for a, b in edges:
        neighbors[a].add(b); neighbors[b].add(a)
    if any(len(v) != 2 for v in neighbors.values()):
        raise ValueError("CAD section does not form closed loops")
    loops = []
    while edges:
        a, b = min(edges); indices = [a]; current = a
        while True:
            next_node = next((n for n in sorted(neighbors[current]) if tuple(sorted((current, n))) in edges), None)
            if next_node is None:
                raise ValueError("Broken section loop")
            edges.remove(tuple(sorted((current, next_node))))
            current = next_node
            if current == a:
                break
            indices.append(current)
        loops.append(keys[indices])
    return loops


def polygon_properties(loops):
    from matplotlib.path import Path as Polygon
    area = 0.; first = np.zeros(2); second = np.zeros((2, 2))
    for i, p in enumerate(loops):
        q = np.roll(p, -1, axis=0); cross = p[:, 0]*q[:, 1]-q[:, 0]*p[:, 1]
        a = cross.sum()/2
        depth = sum(Polygon(other).contains_point(p[0]) for j, other in enumerate(loops) if i != j)
        weight = (-1)**depth * (1 if a > 0 else -1)
        area += weight*a
        first += weight*np.sum((p+q)*cross[:, None], axis=0)/6
        second[0, 0] += weight*np.sum((p[:, 0]**2+p[:, 0]*q[:, 0]+q[:, 0]**2)*cross)/12
        second[1, 1] += weight*np.sum((p[:, 1]**2+p[:, 1]*q[:, 1]+q[:, 1]**2)*cross)/12
        second[0, 1] += weight*np.sum((2*p[:, 0]*p[:, 1]+p[:, 0]*q[:, 1]+q[:, 0]*p[:, 1]+2*q[:, 0]*q[:, 1])*cross)/24
    second[1, 0] = second[0, 1]
    if area <= 0:
        raise ValueError("Nonpositive section area")
    center = first/area
    second -= area*np.outer(center, center)
    return area, center, second


def member_section(body, axis_hint=None):
    center = body.vertices.mean(axis=0)
    _, _, axes = np.linalg.svd(body.vertices-center, full_matrices=False)
    if axis_hint is not None:
        x = np.asarray(axis_hint)/np.linalg.norm(axis_hint)
        y = np.eye(3)[np.argmin(np.abs(x))]; y -= x*np.dot(x, y); y /= np.linalg.norm(y)
        axes = np.array([x, y, np.cross(x, y)])
    if np.linalg.det(axes) < 0:
        axes[2] *= -1
    along = (body.vertices-center) @ axes[0]
    length = float(np.ptp(along))
    sections = []
    for fraction in (.35, .5, .65):
        station = center+axes[0]*(along.min()+fraction*length)
        loops = section_loops(body, station, axes)
        area, offset, second = polygon_properties(loops)
        sections.append((area, station+offset @ axes[1:], second, loops))
    area, centroid, second, loops = sections[1]
    if max(abs(s[0]/area-1) for s in sections) > .05:
        raise ValueError("Nonuniform/curved member requires a centreline/section override")
    # Circular sections have approximately constant radius on each contour.
    def circle(p):
        c = np.linalg.lstsq(np.column_stack((2*p, np.ones(len(p)))), np.sum(p*p, axis=1), rcond=None)[0][:2]
        radii = np.linalg.norm(p-c, axis=1)
        return radii, float(np.std(radii)/np.mean(radii))
    round_section = all(circle(p)[1] < .04 for p in loops)
    # A sparse longitudinal slice can also fit a huge circle through its end
    # vertices. Circular section moments must be isotropic, independently of
    # that vertex fit; otherwise the wrong axis can win the volume ranking.
    moments=np.linalg.eigvalsh(second)
    round_section = round_section and moments[0]>0 and moments[1]/moments[0]<1.15
    if not round_section:
        raise ValueError("Noncircular torsion section requires an explicit J override")
    endpoints = [centroid+axes[0]*(a-(along.min()+.5*length)) for a in (along.min(), along.max())]
    radius = max(circle(p)[0].max() for p in loops)
    return {"a": endpoints[0].tolist(), "b": endpoints[1].tolist(), "axes": axes.tolist(),
            "area_m2": float(area), "Iy_m4": float(second[1, 1]), "Iz_m4": float(second[0, 0]),
            "J_m4": float(np.trace(second)), "radius_m": float(radius), "method": "CAD planar sections; circular Saint-Venant torsion"}


def curved_member(body):
    """Trace an unbranched tube using locally normal sections, including its bore.

    Global planar cuts seed the centreline only; they are never used as the
    physical section of a bent member. Ambiguous topology remains an error.
    """
    center = body.vertices.mean(axis=0)
    _, _, axes = np.linalg.svd(body.vertices-center, full_matrices=False)
    extent = (body.vertices-center) @ axes[0]
    fractions = np.linspace(.08, .92, 29)
    points = []
    for f in fractions:
        station = center+axes[0]*(extent.min()+f*np.ptp(extent))
        loops = section_loops(body, station, axes)
        if len(loops) != 2:
            raise ValueError('Curved tube must have one outer contour and one bore')
        _, offset, _ = polygon_properties(loops)
        points.append(station+offset @ axes[1:])
    points = np.array(points)
    converged = False
    for iteration in range(30):
        tangents = np.gradient(points, axis=0)
        measured = []; refined = []
        for point, tangent in zip(points, tangents):
            x = tangent/np.linalg.norm(tangent)
            y = np.eye(3)[np.argmin(abs(x))]; y -= x*np.dot(x,y); y /= np.linalg.norm(y)
            basis = np.array([x,y,np.cross(x,y)])
            loops = section_loops(body, point, basis)
            if len(loops) != 2:
                raise ValueError('Ambiguous curved tube section topology')
            area, offset, second = polygon_properties(loops)
            roundness = []; radii = []
            for loop in loops:
                c = np.linalg.lstsq(np.column_stack((2*loop,np.ones(len(loop)))),np.sum(loop*loop,axis=1),rcond=None)[0][:2]
                radius = np.linalg.norm(loop-c,axis=1)
                roundness.append(float(np.std(radius)/np.mean(radius)))
                radii.append(float(np.max(radius)))
            measured.append((area,second,max(radii),max(roundness)))
            refined.append(point+offset @ basis[1:])
        refined = np.array(refined)
        change = float(np.max(np.linalg.norm(refined-points,axis=1)))
        points = refined
        if change < 2e-6:
            converged = True; break
    if not converged:
        raise ValueError('Curved tube centreline did not converge')
    areas = np.array([s[0] for s in measured]); area = float(np.median(areas))
    if np.max(abs(areas/area-1)) > .05 or max(s[3] for s in measured) >= .04:
        raise ValueError('Nonuniform/noncircular curved tube requires an explicit section override')
    def end_center(p,q,first):
        # Mitered ends must terminate on their actual cap plane, not the
        # global bounding plane (which includes the tube's outside radius).
        direction=p-q; direction/=np.linalg.norm(direction)
        triangles=body.vertices[body.faces]
        normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        weights=np.linalg.norm(normals,axis=1)
        normals/=np.maximum(weights[:,None],1e-30)
        centers=triangles.mean(axis=1); along=(centers-center)@axes[0]
        terminal=along<extent.min()+.15*np.ptp(extent) if first else along>extent.max()-.15*np.ptp(extent)
        chosen=terminal & (abs(normals@direction)>.5)
        if not chosen.any(): raise ValueError('Cannot identify curved tube end cap')
        n=normals[chosen]; n*=np.sign(n@direction)[:,None]
        normal=np.average(n,axis=0,weights=weights[chosen])
        origin=np.average(centers[chosen],axis=0,weights=weights[chosen])
        return p+direction*np.dot(origin-p,normal)/np.dot(direction,normal)
    path=np.vstack((end_center(points[0],points[1],True),points,
                    end_center(points[-1],points[-2],False)))
    length=float(np.linalg.norm(np.diff(path,axis=0),axis=1).sum())
    discrepancy=abs(area*length/volume_properties(body)['volume_m3']-1)
    if discrepancy > .05:
        raise ValueError(f'Curved tube section/path volume differs from CAD by {discrepancy:.1%} (limit 5%)')
    second=np.median(np.array([s[1] for s in measured]),axis=0)
    def simplify(points,tolerance):
        if len(points)<=2:return points
        chord=points[-1]-points[0]
        errors=np.linalg.norm(np.cross(points-points[0],chord),axis=1)/np.linalg.norm(chord)
        i=int(np.argmax(errors))
        if errors[i]<=tolerance:return points[[0,-1]]
        return np.vstack((simplify(points[:i+1],tolerance)[:-1],simplify(points[i:],tolerance)))
    path=simplify(path,max(s[2] for s in measured)*.01)
    return dict(a=path[0].tolist(),b=path[-1].tolist(),path=path.tolist(),axes=axes.tolist(),
                area_m2=area,Iy_m4=float(second[1,1]),Iz_m4=float(second[0,0]),
                J_m4=float(np.trace(second)),radius_m=max(s[2] for s in measured),
                method='CAD locally normal curved tube sections',section_volume_discrepancy=discrepancy,
                extraction=dict(iterations=iteration+1,convergence_m=change,stations=len(points),
                                maximum_roundness=max(s[3] for s in measured)))


def extract_member(body):
    """Search principal surface-normal axes too: short tube axes need not be longest."""
    t = body.vertices[body.faces]
    normals = np.cross(t[:, 1]-t[:, 0], t[:, 2]-t[:, 0])
    area2 = np.linalg.norm(normals, axis=1)
    normals /= np.maximum(area2[:, None], 1e-30)
    _, normal_axes = np.linalg.eigh((normals.T*area2) @ normals)
    _, _, point_axes = np.linalg.svd(body.vertices-body.vertices.mean(axis=0), full_matrices=False)
    choices = []
    for axis in [None, *normal_axes.T, *point_axes]:
        try:
            section = member_section(body, axis)
            # Prefer the section most consistent with the body's material volume.
            estimate = section['area_m2']*np.linalg.norm(np.array(section['b'])-section['a'])
            score = abs(np.log(estimate/volume_properties(body)['volume_m3']))
            choices.append((score, section))
        except ValueError:
            pass
    if not choices:
        from .tube_reference import trace_member
        return trace_member(body)
    score, result = min(choices, key=lambda x: x[0])
    if abs(np.expm1(score)) > .2:
        # A circular slice through just one leg of a U-shaped or heavily
        # coped body is not evidence for a whole-member reference.
        from .tube_reference import trace_member
        return trace_member(body)
    result['section_volume_discrepancy'] = float(np.expm1(score))
    # Follow section centroids through bends, instead of projecting end points
    # onto one straight line. This reference path does not change the JBeam graph.
    axes=np.array(result['axes']); center=body.vertices.mean(axis=0)
    extent=(body.vertices-center)@axes[0]; path=[]
    for fraction in np.linspace(.05,.95,13):
        station=center+axes[0]*(extent.min()+fraction*np.ptp(extent))
        try:
            loops=section_loops(body,station,axes)
            area,offset,_=polygon_properties(loops)
            if .7<area/result['area_m2']<1.5:
                path.append(station+offset@axes[1:])
        except ValueError:
            pass
    if len(path)>=5:
        # Extend the first/last tangent only to the mesh's projected end planes.
        def end(p,q,target):
            direction=p-q
            return p+direction*(target-np.dot(p-center,axes[0]))/np.dot(direction,axes[0])
        points=[end(path[0],path[1],extent.min()),*path,end(path[-1],path[-2],extent.max())]
        # Remove nearly collinear intermediate stations; retain real curved portions.
        reduced=[points[0]]
        for i in range(1,len(points)-1):
            chord=points[i+1]-reduced[-1]
            off=np.linalg.norm(np.cross(points[i]-reduced[-1],chord))/max(np.linalg.norm(chord),1e-12)
            if off>2e-4: reduced.append(points[i])
        reduced.append(points[-1])
        result['path']=[p.tolist() for p in reduced]
        result['a'],result['b']=result['path'][0],result['path'][-1]
    return result
