"""Prepare selected CAD bodies for the existing frame generator. No SolidWorks access."""
import argparse
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import hashlib
import xml.etree.ElementTree as ET
from appearance_textures import texture_asset, mesh_uvs

NS = 'http://www.collada.org/2005/11/COLLADASchema'
COORDINATE_CONVENTION = 'solidworks-y-up-to-beamng-z-up-v1'
ET.register_namespace('', NS)
def element(parent, tag, text=None, **attrs):
    item = ET.SubElement(parent, '{'+NS+'}'+tag, attrs)
    if text is not None: item.text = str(text)
    return item

def rotate(point, mapping):
    x,y,z = point
    if mapping == 'XYZ': return x,y,z
    if mapping == 'X-ZY': return x,-z,y
    if mapping == '-ZYX': return -z,y,x
    axes = mapping.split(',')
    if len(axes) != 2 or any(a not in ('+X','-X','+Y','-Y','+Z','-Z') for a in axes) or axes[0][1] == axes[1][1]:
        raise ValueError('Choose distinct signed CAD up and forward axes: '+mapping)
    def axis(a): return tuple(((-1 if a[0]=='-' else 1) if i=='XYZ'.index(a[1]) else 0) for i in range(3))
    up = axis(axes[0]); back = tuple(-v for v in axis(axes[1]))
    left = (back[1]*up[2]-back[2]*up[1],back[2]*up[0]-back[0]*up[2],back[0]*up[1]-back[1]*up[0])
    return tuple(sum(a*b for a,b in zip(row,point)) for row in (left,back,up))

def read_stl(path, mapping='XYZ'):
    with Path(path).open('rb') as stream:
        header = stream.read(84)
        if len(header) != 84: raise ValueError('Truncated STL: '+str(path))
        count, = struct.unpack_from('<I',header,80)
        if Path(path).stat().st_size != 84 + count*50 or not count: raise ValueError('Invalid or empty binary STL')
        triangles=[]
        for _ in range(count):
            values=struct.unpack('<12fH',stream.read(50))
            tri=[rotate(values[i:i+3],mapping) for i in (3,6,9)]
            if not all(math.isfinite(v) for p in tri for v in p): raise ValueError('Non-finite mesh coordinate')
            triangles.append(tri)
        return triangles

def write_stl(path, triangles):
    with Path(path).open('wb') as stream:
        stream.write(b'beamng.cad assembly metres'.ljust(80,b'\0'))
        stream.write(struct.pack('<I',len(triangles)))
        for tri in triangles: stream.write(struct.pack('<12fH',0,0,0,*(v for p in tri for v in p),0))

def write_dae(path, meshes):
    path=Path(path)
    root=ET.Element('{'+NS+'}COLLADA',version='1.4.1')
    asset=element(root,'asset');element(asset,'unit',name='meter',meter='1');element(asset,'up_axis','Z_UP')
    images=element(root,'library_images');effects=element(root,'library_effects');materials=element(root,'library_materials');declared=set();assets={};texture_cache={}
    def appearance_material(appearance):
        color=appearance.get('BaseColor',[.35,.35,.35,1]);roughness=appearance.get('Roughness',.6);metallic=appearance.get('Metallic',0)
        if len(color)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in [*color,roughness,metallic]):
            raise ValueError('Invalid captured CAD appearance')
        source=appearance.get('TextureFile')
        if source and source not in texture_cache:texture_cache[source]=texture_asset(appearance)
        texture=texture_cache.get(source)
        values=json.dumps([color,roughness,metallic]+([texture[0]] if texture else []),separators=(',',':'))
        name='cad_appearance_'+hashlib.sha256(values.encode()).hexdigest()[:20] if appearance else 'mochi_frame_material'
        if name not in declared:
            effect=element(effects,'effect',id=name+'-effect');profile=element(effect,'profile_COMMON')
            if texture:
                filename,data=texture;image_id=filename.replace('.','_')
                if filename not in assets:
                    element(element(images,'image',id=image_id),'init_from',filename);assets[filename]=data
                surface=element(element(profile,'newparam',sid=name+'-surface'),'surface',type='2D');element(surface,'init_from',image_id)
                sampler=element(element(profile,'newparam',sid=name+'-sampler'),'sampler2D');element(sampler,'source',name+'-surface')
                element(sampler,'wrap_s','WRAP');element(sampler,'wrap_t','WRAP')
            technique=element(profile,'technique',sid='common');diffuse=element(element(technique,'lambert'),'diffuse')
            if texture:element(diffuse,'texture',texture=name+'-sampler',texcoord='UVMap')
            else:element(diffuse,'color',' '.join(map(str,color)))
            extra=element(element(effect,'extra'),'technique',profile='BEAMNG_CAD')
            element(extra,'roughness',roughness);element(extra,'metallic',metallic)
            if texture:
                element(extra,'base_color',' '.join(map(str,color)));element(extra,'base_color_map',texture[0])
                element(extra,'mapping','Captured vertex UVs or 100 mm box projection; native procedural mapping is not baked')
            material=element(materials,'material',id=name,name=name);element(material,'instance_effect',url='#'+name+'-effect');declared.add(name)
        return name
    geometries=element(root,'library_geometries')
    scene=element(element(root,'library_visual_scenes'),'visual_scene',id='Scene',name='Scene')
    for record,triangles in meshes:
        name=record['Id'];count=len(triangles)*3
        uvs=mesh_uvs(record,triangles)
        geometry=element(geometries,'geometry',id=name+'-mesh',name=name)
        mesh=element(geometry,'mesh');source=element(mesh,'source',id=name+'-positions')
        element(source,'float_array',' '.join(format(v,'.9g') for tri in triangles for p in tri for v in p),id=name+'-array',count=str(count*3))
        accessor=element(element(source,'technique_common'),'accessor',source='#'+name+'-array',count=str(count),stride='3')
        for axis in 'XYZ': element(accessor,'param',name=axis,type='float')
        if uvs is not None:
            uvsource=element(mesh,'source',id=name+'-uv')
            element(uvsource,'float_array',' '.join(format(v,'.9g') for p in uvs for v in p),id=name+'-uv-array',count=str(count*2))
            uvaccessor=element(element(uvsource,'technique_common'),'accessor',source='#'+name+'-uv-array',count=str(count),stride='2')
            for axis in 'ST':element(uvaccessor,'param',name=axis,type='float')
        vertices=element(mesh,'vertices',id=name+'-vertices');element(vertices,'input',semantic='POSITION',source='#'+name+'-positions')
        ranges=record.get('AppearanceGroups')
        if ranges is None:ranges=[dict(StartTriangle=0,TriangleCount=len(triangles),Appearance={})]
        end=0;bindings={}
        for group in ranges:
            start=group['StartTriangle'];length=group['TriangleCount']
            if type(start) is not int or type(length) is not int or start!=end or length<=0 or start+length>len(triangles):
                raise ValueError('CAD appearance triangle ranges do not cover the mesh exactly')
            end=start+length;material=appearance_material(group['Appearance']);symbol='slot_'+str(len(bindings))
            bindings[symbol]=material
            tris=element(mesh,'triangles',count=str(length),material=symbol)
            element(tris,'input',semantic='VERTEX',source='#'+name+'-vertices',offset='0')
            if uvs is not None:element(tris,'input',semantic='TEXCOORD',source='#'+name+'-uv',offset='1',set='0')
            element(tris,'p',' '.join(str(i) for i in range(start*3,end*3) for _ in range(2 if uvs is not None else 1)))
        if end!=len(triangles):raise ValueError('CAD appearance triangle ranges do not cover the mesh exactly')
        node=element(scene,'node',id=name,name=name,type='NODE');instance=element(node,'instance_geometry',url='#'+name+'-mesh')
        technique=element(element(instance,'bind_material'),'technique_common')
        for symbol,material in bindings.items():
            binding=element(technique,'instance_material',symbol=symbol,target='#'+material)
            if uvs is not None:element(binding,'bind_vertex_input',semantic='UVMap',input_semantic='TEXCOORD',input_set='0')
    element(element(root,'scene'),'instance_visual_scene',url='#Scene')
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
    for name,data in assets.items():(path.parent/name).write_bytes(data)

def dae_materials(data, vehicle_directory=None):
    """Read final DAE names after package remapping; all slots get matching BeamNG materials."""
    root=ET.fromstring(data);ns={'c':NS};effects={e.get('id'):e for e in root.findall('c:library_effects/c:effect',ns)};result={}
    for material in root.findall('c:library_materials/c:material',ns):
        effect=effects[material.find('c:instance_effect',ns).get('url')[1:]]
        extra=effect.find("c:extra/c:technique[@profile='BEAMNG_CAD']",ns)
        color_node=effect.find('.//c:diffuse/c:color',ns)
        if color_node is None and extra is not None:color_node=extra.find('c:base_color',ns)
        color=[float(v) for v in color_node.text.split()]
        roughness=float(extra.find('c:roughness',ns).text) if extra is not None else .6
        metallic=float(extra.find('c:metallic',ns).text) if extra is not None else 0
        name=material.get('name',material.get('id'))
        result[name]=dict(name=name,mapTo=name,**{'class':'Material'},Stages=[dict(baseColorFactor=color,roughnessFactor=roughness,metallicFactor=metallic)],doubleSided=True,dynamicCubemap=True,version=1.5)
        texture=extra.find('c:base_color_map',ns) if extra is not None else None
        if texture is not None:
            filename=texture.text
            result[name]['Stages'][0]['baseColorMap']=('/'+vehicle_directory.strip('/')+'/' if vehicle_directory else '')+filename
            result[name]['Stages'][0]['useAnisotropic']=True
        if color[3]<1:result[name].update(translucent=True,translucentBlendOp='PreMulAlpha',castShadows=False)
    return result

def validate_hull(hull):
    # Older assembly registries predate these advanced controls.
    for key, value in dict(ProxyOffsetRatio=100.0, SymmetryBisectFlip=False, SymmetryMergeDistance=0.0001).items():
        hull.setdefault(key, value)
    if any(type(hull[k]) is not int or not 2 <= hull[k] <= 100 for k in ('Width','Height','Length')):
        raise ValueError('Grid dimensions must be integers from 2 to 100')
    if hull['Symmetry'] and hull['Width'] % 2 != 1: raise ValueError('Symmetry requires an odd width grid')
    for key in ('Symmetry','SymmetryBisectFlip'):
        if type(hull[key]) is not bool: raise ValueError(key+' must be boolean')
    for key in ('Offset','Weld','ProxyDivisor','ProxyOffsetRatio','SymmetryMergeDistance'):
        if type(hull[key]) not in (int,float) or not math.isfinite(hull[key]) or hull[key] < 0: raise ValueError('Invalid '+key)
    if hull['ProxyDivisor'] == 0 or hull['ProxyOffsetRatio'] == 0: raise ValueError('Proxy divisor and offset ratio must be positive')
    if hull.get('CoordinateConvention') and (hull['CoordinateConvention'] != COORDINATE_CONVENTION or hull['Orientation'] != 'X-ZY'):
        raise ValueError('Unsupported coordinate convention or inconsistent mapping')
    rotate((0,0,0),hull['Orientation'])

def prepare(geometry, materials, output, blender, cgal):
    geometry,materials,output=Path(geometry).resolve(),Path(materials).resolve(),Path(output).resolve()
    package=json.loads(geometry.read_text(encoding='utf-8-sig'))
    if package['Format'] != 'beamng-cad-frame-geometry' or package['Version'] != 1 or package['Units'] != 'metres':
        raise ValueError('Unsupported geometry package')
    hull=package['Assignment']['Hull'];validate_hull(hull)
    if not package['Meshes']: raise ValueError('The frame selection is empty')
    native=package.get('MaterialSource')=='solidworks'
    files=('main.materials.json','vehicle_info_settings.json') if native else ('material.json','main.materials.json','vehicle_info_settings.json')
    if native and not (geometry.parent/'material-snapshot.json').is_file(): raise ValueError('Missing captured SolidWorks materials; export the selected bodies again')
    for file in files:
        if not (materials/file).is_file(): raise FileNotFoundError('Missing material/settings input: '+str(materials/file))
    if not Path(blender).is_file() or not Path(cgal).is_file(): raise FileNotFoundError('Configure Blender and CGAL Python in Settings')
    output.mkdir(parents=True,exist_ok=False)
    meshes=[]
    for record in package['Meshes']:
        path=(geometry.parent/record['File']).resolve()
        if path.parent != geometry.parent: raise ValueError('Mesh file must belong to geometry package')
        meshes.append((record,read_stl(path,hull['Orientation'])))
    write_stl(output/'frame.stl',[tri for _,tris in meshes for tri in tris])
    write_dae(output/'mochi.dae',meshes)
    for file in files: shutil.copy2(materials/file,output/file)
    visual_materials=json.loads((output/'main.materials.json').read_text(encoding='utf-8-sig'))
    visual_materials.update(dae_materials((output/'mochi.dae').read_bytes(),'vehicles/mochi'))
    (output/'main.materials.json').write_text(json.dumps(visual_materials,indent=2),encoding='utf-8')
    if native:
        shutil.copy2(geometry.parent/'material-snapshot.json',output/'material-snapshot.json')
        (output/'material.json').write_text(json.dumps({'source':'solidworks','snapshot':'material-snapshot.json'}),encoding='utf-8')
    shutil.copy2(geometry,output/'geometry.json')
    job={'frame':str(output/'frame.stl'),'off':str(output/'mochi_hull.off'),'cgal':cgal,'hull':hull}
    (output/'hull_job.json').write_text(json.dumps(job,indent=2),encoding='utf-8')
    subprocess.run([blender,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
        '--python',str(Path(__file__).parent/'alpha_worker.py'),'--',str(output/'hull_job.json')],check=True)
    if not (output/'mochi_hull.off').is_file(): raise RuntimeError('Hull worker produced no OFF mesh')
    print('Prepared frame: '+str(output),flush=True)

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    for name in ('geometry','materials','output','blender','cgal'): p.add_argument('--'+name,required=True)
    args=p.parse_args();prepare(args.geometry,args.materials,args.output,args.blender,args.cgal)
