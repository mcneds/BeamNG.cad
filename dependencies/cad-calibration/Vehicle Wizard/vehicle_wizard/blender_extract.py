"""Executed by Blender's bundled Python, never by the desktop interpreter."""
import hashlib
import json
import sys
from pathlib import Path

import bpy
import numpy as np

args=sys.argv[sys.argv.index('--')+1:]
output=Path(args[0]);output.mkdir(parents=True,exist_ok=True)
scale=bpy.context.scene.unit_settings.scale_length
depsgraph=bpy.context.evaluated_depsgraph_get()
objects=[]
scene_objects=sorted((o for o in bpy.context.scene.objects if o.type=='MESH'),key=lambda o:o.name)
for i,obj in enumerate(scene_objects):
    evaluated=obj.evaluated_get(depsgraph);mesh=evaluated.to_mesh();mesh.calc_loop_triangles()
    key='m_'+hashlib.sha256(obj.name.encode()).hexdigest()[:16]
    xyz=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',xyz);xyz=xyz.reshape(-1,3)
    world=np.array(obj.matrix_world,dtype=float)
    xyz=(xyz@world[:3,:3].T+world[:3,3])*scale
    tri=np.array([t.vertices[:] for t in mesh.loop_triangles],dtype=np.int32)
    if np.linalg.det(world[:3,:3])<0:tri=tri[:,::-1]
    if not len(tri):evaluated.to_mesh_clear();continue
    # Full-resolution cached arrays preserve exact picking and geometry. No lossy source modification.
    np.savez_compressed(output/(key+'.npz'),vertices=xyz.astype(np.float32),faces=tri)
    color=list(obj.color[:3])
    if obj.active_material:color=list(obj.active_material.diffuse_color[:3])
    objects.append({'id':key,'name':obj.name,'collections':[c.name for c in obj.users_collection],
        'bounds':[xyz.min(axis=0).tolist(),xyz.max(axis=0).tolist()],'vertices':len(xyz),'triangles':len(tri),
        'color':color,'file':key+'.npz'})
    evaluated.to_mesh_clear()
    if i%100==0:print(f'Extracting {i+1}/{len(scene_objects)}',flush=True)
index={'version':1,'blender':bpy.app.version_string,'source':bpy.data.filepath,'scale_m':scale,
       'units':'metres','objects':objects,'triangles':sum(o['triangles'] for o in objects)}
(output/'index.json').write_text(json.dumps(index,indent=2),encoding='utf-8')
print(f'Imported {len(objects)} meshes, {index["triangles"]} triangles',flush=True)
