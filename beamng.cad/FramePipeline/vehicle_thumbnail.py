"""Offline selector thumbnail from captured CAD; never invents missing geometry."""
import io
import json
from pathlib import Path
import numpy as np


def ensure(contents,project):
    prefix='vehicles/'+project['Identity']['namespace']+'/'
    existing=contents.get(prefix+'default.jpg') or contents.get(prefix+'base.jpg')
    if existing:
        contents.setdefault(prefix+'default.jpg',existing);contents.setdefault(prefix+'base.jpg',existing)
        return
    sources=[Path(c.get('AppearanceDirectory') or c.get('GeometryDirectory') or '')/'geometry.json' for c in project.get('Components',[])]
    # Template-only receipts have no captured CAD. Keep their caller-supplied image.
    if not sources or not all(p.is_file() for p in sources):return
    from vehicle_revisions import appearance_meshes
    faces=[];colors=[]
    for comp in project['Components']:
        for record,triangles in appearance_meshes(comp)[0]:
            triangles=np.asarray(triangles);facecolors=np.tile([.55,.58,.62,1.],(len(triangles),1))
            for group in record.get('AppearanceGroups',[]):
                appearance=group['Appearance'];color=appearance.get('BaseColor',[.55,.58,.62,1.])
                # Preview the source image's mean colour, not fabricated weave UVs.
                if appearance.get('TextureFile'):
                    from PIL import Image,ImageStat
                    with Image.open(appearance['TextureFile']) as image:color=[v/255 for v in ImageStat.Stat(image.convert('RGB')).mean]+[color[3]]
                at=group['StartTriangle'];facecolors[at:at+group['TriangleCount']]=color
            faces.append(triangles);colors.append(facecolors)
    triangles=np.concatenate(faces);colors=np.concatenate(colors)
    direction=np.array([1.,-1.7,.9]);direction/=np.linalg.norm(direction)
    right=np.cross([0.,0.,1.],direction);right/=np.linalg.norm(right);up=np.cross(direction,right)
    vertices=triangles.reshape(-1,3);center=(vertices.min(0)+vertices.max(0))*.5
    projected=(triangles-center)@np.array([right,up,direction]).T
    normal=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);length=np.linalg.norm(normal,axis=1)
    normal/=np.maximum(length[:,None],1e-20)
    colors[:,:3]*=(.45+.55*np.abs(normal@direction))[:,None]
    order=np.argsort(projected[:,:,2].mean(1));xy=projected[order,:,:2]
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.collections import PolyCollection
    figure=Figure(figsize=(9.6,6),dpi=100,facecolor='#e8edf2');FigureCanvasAgg(figure)
    axes=figure.add_axes([.02,.06,.96,.92]);axes.set_facecolor('#e8edf2')
    axes.add_collection(PolyCollection(xy,facecolors=colors[order],edgecolors='none',antialiaseds=False))
    axes.autoscale_view();axes.set_aspect('equal');axes.margins(.06);axes.axis('off')
    figure.text(.97,.025,'CAD preview',ha='right',color='#4b5563',fontsize=10)
    output=io.BytesIO();figure.savefig(output,format='jpg',dpi=100);figure.clear()
    for name in ('default.jpg','base.jpg'):contents[prefix+name]=output.getvalue()
