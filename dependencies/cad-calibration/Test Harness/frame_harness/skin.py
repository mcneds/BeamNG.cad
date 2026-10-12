"""Derived local render regions; the physical CAD mesh remains an immutable input."""
import copy
from itertools import combinations
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import Delaunay,QhullError
from .cad import read_bodies
from .build import node_table,beam_table,sha256


def partition_surface(triangles,centers):
    """Clip at shared Voronoi planes, rather than assigning whole triangles.

    Long CAD triangles must be split exactly at a binding boundary; centroid
    assignment leaves sawtooth strips on the detached surface.
    """
    try:
        starts,neighbours=Delaunay(centers).vertex_neighbor_vertices
        adjacent=[neighbours[starts[i]:starts[i+1]] for i in range(len(centers))]
    except QhullError:
        adjacent=[np.delete(np.arange(len(centers)),i) for i in range(len(centers))]
    for cell,near in enumerate(adjacent):
        normal=centers[near]-centers[cell]
        offset=(np.sum(centers[near]**2,axis=1)-np.sum(centers[cell]**2))*.5
        lengths=np.linalg.norm(normal,axis=1)
        normal=normal/lengths[:,None];offset=offset/lengths
        distances=triangles[:,:,:3]@normal.T-offset
        outside=(distances.min(axis=1)>1e-10).any(axis=1)
        # A triangle exactly on a bisector belongs to just one cell.
        outside|=((abs(distances).max(axis=1)<1e-10)&(near<cell)).any(axis=1)
        inside=(distances.max(axis=1)<=1e-10).all(axis=1)&~outside
        pieces=list(triangles[inside])
        for triangle in triangles[~inside&~outside]:
            polygon=list(triangle)
            for n,d in zip(normal,offset):
                if not polygon:break
                clipped=[];a=polygon[-1];da=float(a[:3]@n-d)
                for b in polygon:
                    db=float(b[:3]@n-d)
                    if (da<=0)!=(db<=0):clipped.append(a+(b-a)*(da/(da-db)))
                    if db<=0:clipped.append(b)
                    a,da=b,db
                polygon=clipped
            for i in range(1,len(polygon)-1):
                face=np.array([polygon[0],polygon[i],polygon[i+1]])
                if np.linalg.norm(np.cross(face[1,:3]-face[0,:3],face[2,:3]-face[0,:3]))>1e-15:pieces.append(face)
        if pieces:yield cell,np.array(pieces)


def partition_materials(geometry,triangles,centers,tag):
    """Interpolate UVs at fracture-region cuts and preserve every material slot."""
    mesh=geometry.find(tag('mesh'))
    primitives=[p for p in mesh if p.tag in (tag('triangles'),tag('polylist'))];at=0
    for group,primitive in enumerate(primitives):
        inputs=primitive.findall(tag('input'));uvinput=next((i for i in inputs if i.get('semantic')=='TEXCOORD'),None)
        counts=[3]*int(primitive.get('count')) if primitive.tag==tag('triangles') else list(map(int,primitive.findtext(tag('vcount')).split()))
        count=sum(n-2 for n in counts);points=triangles[at:at+count];at+=count
        if uvinput is not None:
            source=next(s for s in geometry.findall('.//'+tag('source')) if s.get('id')==uvinput.get('source')[1:])
            accessor=source.find('.//'+tag('accessor'));stride=int(accessor.get('stride','2'));offset=int(accessor.get('offset','0'))
            values=np.fromstring(source.findtext(tag('float_array')),sep=' ')[offset:].reshape(-1,stride)[:,:2]
            width=max(int(i.get('offset','0')) for i in inputs)+1
            indices=np.fromstring(primitive.findtext(tag('p')),sep=' ',dtype=int).reshape(-1,width)[:,int(uvinput.get('offset','0'))]
            uvfaces=[];offset=0
            for n in counts:
                polygon=indices[offset:offset+n];offset+=n
                uvfaces.extend((polygon[0],polygon[i],polygon[i+1]) for i in range(1,n-1))
            points=np.concatenate([points,values[np.asarray(uvfaces)]],axis=2)
        for cell,pieces in partition_surface(points,centers):
            yield cell,('' if len(primitives)==1 else '_material_'+str(group)),pieces[:,:,:3],pieces[:,:,3:] if uvinput is not None else None,primitive.get('material')
    if at!=len(triangles):raise ValueError('Render material partition requires triangulated CAD input')


def prepare_skin(part,physical_path,render_path):
    nodes=node_table(part);names=sorted(nodes);xyz=np.array([nodes[n]['position'] for n in names])
    edges={tuple(sorted((b['a'],b['b']))) for b in beam_table(part)}
    tetrahedra=[]
    for indices in Delaunay(xyz).simplices:
        indices=np.array(sorted(indices));points=xyz[indices]
        if np.linalg.cond((points[1:]-points[0]).T)>25:continue
        if not all(tuple(sorted((names[a],names[b]))) in edges for a,b in combinations(indices,2)):continue
        # Every possible nearest center must have a usable transverse locator.
        usable=True
        for i in range(4):
            vectors=np.delete(points,i,axis=0)-points[i];vectors/=np.linalg.norm(vectors,axis=1)[:,None]
            if min(abs(np.dot(vectors[a],vectors[b])) for a,b in combinations(range(3),2))>.6:usable=False
        if usable:tetrahedra.append(indices)
    if not tetrahedra:raise ValueError('No well-conditioned connected tetrahedra for render binding')
    tetrahedra=np.array(tetrahedra);centers=xyz[tetrahedra].mean(axis=1)
    centers,unique=np.unique(centers,axis=0,return_index=True);tetrahedra=tetrahedra[unique]
    original=ET.parse(physical_path).getroot();uri=original.tag.split('}')[0][1:];tag=lambda name:'{'+uri+'}'+name
    ET.register_namespace('',uri);root=ET.Element(tag('COLLADA'),version='1.4.1')
    for child in original:
        if child.tag not in {tag('library_geometries'),tag('library_visual_scenes'),tag('scene')}:
            root.append(copy.deepcopy(child))
    asset=root.find(tag('asset'))
    if asset is not None:
        unit=asset.find(tag('unit'))
        if unit is not None:unit.set('meter','1')
    geometries=ET.SubElement(root,tag('library_geometries'))
    scene=ET.SubElement(ET.SubElement(root,tag('library_visual_scenes')),tag('visual_scene'),id='cadRenderScene')
    originals={n.get('name') or n.get('id'):n for n in original.iter(tag('node'))}
    source_geometries={g.get('id'):g for g in original.iter(tag('geometry'))}
    regions=[];input_count=0;output_count=0;area_before=0.;area_after=0.
    for body in read_bodies(physical_path):
        triangles=body.vertices[body.faces];input_count+=len(triangles)
        surface=lambda t:float(np.linalg.norm(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]),axis=1).sum()*.5)
        area_before+=surface(triangles)
        original_node=originals[body.name];instance=original_node.find(tag('instance_geometry'))
        original_geometry=source_geometries[instance.get('url')[1:]]
        binding=instance.find(tag('bind_material'))
        for cell,suffix,points,uvs,material in partition_materials(original_geometry,triangles,centers,tag):
            area_after+=surface(points);output_count+=len(points)
            name=f'{body.name}_skin_{cell:04d}'+suffix
            geometry=ET.SubElement(geometries,tag('geometry'),id=name+'-mesh',name=name);mesh=ET.SubElement(geometry,tag('mesh'))
            source=ET.SubElement(mesh,tag('source'),id=name+'-positions')
            ET.SubElement(source,tag('float_array'),id=name+'-array',count=str(points.size)).text=' '.join(format(v,'.10g') for v in points.ravel())
            accessor=ET.SubElement(ET.SubElement(source,tag('technique_common')),tag('accessor'),source='#'+name+'-array',count=str(len(points)*3),stride='3')
            for axis in 'XYZ':ET.SubElement(accessor,tag('param'),name=axis,type='float')
            if uvs is not None:
                uvsource=ET.SubElement(mesh,tag('source'),id=name+'-uv')
                ET.SubElement(uvsource,tag('float_array'),id=name+'-uv-array',count=str(uvs.size)).text=' '.join(format(v,'.10g') for v in uvs.ravel())
                uvaccessor=ET.SubElement(ET.SubElement(uvsource,tag('technique_common')),tag('accessor'),source='#'+name+'-uv-array',count=str(len(points)*3),stride='2')
                for axis in 'ST':ET.SubElement(uvaccessor,tag('param'),name=axis,type='float')
            vertices=ET.SubElement(mesh,tag('vertices'),id=name+'-vertices');ET.SubElement(vertices,tag('input'),semantic='POSITION',source='#'+name+'-positions')
            attrs=dict(count=str(len(points)))
            if material:attrs['material']=material
            faces=ET.SubElement(mesh,tag('triangles'),**attrs);ET.SubElement(faces,tag('input'),semantic='VERTEX',source='#'+name+'-vertices',offset='0')
            if uvs is not None:ET.SubElement(faces,tag('input'),semantic='TEXCOORD',source='#'+name+'-uv',offset='1',set='0')
            ET.SubElement(faces,tag('p')).text=' '.join(str(i) for i in range(len(points)*3) for _ in range(2 if uvs is not None else 1))
            node=ET.SubElement(scene,tag('node'),id=name,name=name);inst=ET.SubElement(node,tag('instance_geometry'),url='#'+name+'-mesh')
            if binding is not None:inst.append(copy.deepcopy(binding))
            regions.append(dict(mesh=name,source_body=body.name,nodes=[names[i] for i in tetrahedra[cell]],triangles=len(points),
                                noncollinear=True,binding='Local connected tetrahedron; all locator pairs have breakable beams'))
    if abs(area_after/area_before-1)>1e-8:raise ValueError('Render subdivision changed CAD surface area')
    ET.SubElement(ET.SubElement(root,tag('scene')),tag('instance_visual_scene'),url='#cadRenderScene')
    ET.ElementTree(root).write(render_path,encoding='utf-8',xml_declaration=True)
    return dict(version=1,physical_file=physical_path.name,render_file=render_path.name,
                physical_sha256=sha256(physical_path),render_sha256=sha256(render_path),
                method='Exact Voronoi surface partition with local connected tetrahedral bindings',
                input_triangles=input_count,render_triangles=output_count,surface_area_before_m2=area_before,
                surface_area_after_m2=area_after,regions=regions)


def apply_skin(part,binding):
    nodes=node_table(part);groups={n:[] for n in nodes};rows=[['mesh','[group]:','nonFlexMaterials']]
    edges={tuple(sorted((e['a'],e['b']))) for e in beam_table(part)}
    for region in binding['regions']:
        selected=region['nodes']
        if len(set(selected))!=4 or not set(selected)<=set(nodes):raise ValueError('Invalid render locator group')
        if not all(tuple(sorted(edge)) in edges for edge in combinations(selected,2)):
            raise ValueError('Render locators lack a supporting beam')
        group='cad_'+region['mesh'];rows.append([region['mesh'],[group]])
        for name in selected:groups[name].append(group)
    for row in part['nodes'][1:]:
        if not isinstance(row,list):continue
        if len(row)==4:row.append({})
        previous=nodes[row[0]]['options'].get('group',[])
        if isinstance(previous,str):previous=[previous]
        row[4]['group']=[g for g in previous if not g.startswith(('cad_','mochi_part_'))]+groups[row[0]]
    part['flexbodies']=rows
    existing=[r for r in part.get('controller',[])[1:] if not isinstance(r,list) or r[0]!='cadSkin']
    part['controller']=[['fileName'],*existing,['cadSkin',{'regions':[
        dict(mesh=r['mesh'],nodes=r['nodes']) for r in binding['regions']]}]]
    return binding['regions']
