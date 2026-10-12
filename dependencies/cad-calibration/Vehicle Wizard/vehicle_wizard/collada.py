"""Small geometry-only COLLADA writer: independent of Blender's removed exporter."""
from xml.sax.saxutils import escape
import numpy as np
from .assembly import mesh_arrays,Cancelled
from .project import transform


def export_meshes(project,path,progress=print,cancel=None):
    owners=project.owners();components=project.data['components'];records=[]
    with open(path,'w',encoding='utf-8',newline='\n') as f:
        material=project.data['model']+'_metal'
        f.write('<?xml version="1.0" encoding="utf-8"?><COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1"><asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>')
        f.write(f'<library_effects><effect id="{material}_fx"><profile_COMMON><technique sid="common"><lambert><diffuse><color>0.45 0.48 0.52 1</color></diffuse></lambert></technique></profile_COMMON></effect></library_effects><library_materials><material id="{material}" name="{material}"><instance_effect url="#{material}_fx"/></material></library_materials><library_geometries>')
        for i,obj in enumerate(project.index()['objects']):
            if cancel and cancel.is_set():raise Cancelled('Mesh export cancelled')
            key=owners.get(obj['id'])
            if not key or components[key]['role']=='ignore':continue
            vertices,faces=mesh_arrays(project,obj);vertices=transform(vertices,project.object_transform(obj['id']))
            name=project.data['model']+'_'+obj['id'];sid=name+'_pos'
            f.write(f'<geometry id="{name}" name="{name}"><mesh><source id="{sid}"><float_array id="{sid}_array" count="{vertices.size}">')
            f.write(' '.join(format(float(x),'.8g') for x in vertices.ravel()))
            f.write(f'</float_array><technique_common><accessor source="#{sid}_array" count="{len(vertices)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source><vertices id="{name}_verts"><input semantic="POSITION" source="#{sid}"/></vertices><triangles count="{len(faces)}" material="{material}"><input semantic="VERTEX" source="#{name}_verts" offset="0"/><p>')
            f.write(' '.join(str(int(x)) for x in faces.ravel()))
            f.write('</p></triangles></mesh></geometry>');records.append((name,key))
            if i%100==0:progress(f'Export mesh {i+1} / {len(project.index()["objects"])}')
        f.write('</library_geometries><library_visual_scenes><visual_scene id="Scene" name="Scene">')
        for name,_ in records:f.write(f'<node id="{escape(name)}" name="{escape(name)}"><instance_geometry url="#{name}"><bind_material><technique_common><instance_material symbol="{material}" target="#{material}"/></technique_common></bind_material></instance_geometry></node>')
        f.write('</visual_scene></library_visual_scenes><scene><instance_visual_scene url="#Scene"/></scene></COLLADA>')
    return records
