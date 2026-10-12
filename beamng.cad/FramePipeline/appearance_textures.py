"""Portable CAD colour textures and explicit fallback UVs for STL captures.

STL snapshots have no native texture coordinates. Box projection uses a 100 mm
tile; this is an appearance approximation, never a physical/material property.
"""
import hashlib
import io
import math
from pathlib import Path
import warnings


def texture_asset(appearance):
    source = appearance.get('TextureFile')
    if not source:
        return None
    from PIL import Image
    data = Path(source).read_bytes()  # Missing textures must not silently become flat paint.
    with Image.open(io.BytesIO(data)) as image:
        if 'A' in image.getbands() or 'transparency' in image.info:
            raise ValueError('CAD colour texture contains alpha; explicit opacity export is required: ' + source)
        output = io.BytesIO()
        image.convert('RGB').save(output, format='PNG')
    data = output.getvalue()
    return 'cad_texture_' + hashlib.sha256(data).hexdigest()[:24] + '.color.png', data


def mesh_uvs(record, triangles):
    """Generate before moving/aligning props so the texture stays attached."""
    existing = record.get('TextureCoordinates')
    if existing is not None:
        if len(existing) != len(triangles)*3 or any(len(p)!=2 or not all(math.isfinite(v) for v in p) for p in existing):
            raise ValueError('Texture coordinates do not match CAD triangle vertices')
        return existing
    if not any(g['Appearance'].get('TextureFile') for g in record.get('AppearanceGroups', [])):
        return None
    warnings.warn('CAD texture mapping approximated with 100 mm box projection: ' + record['Id'], stacklevel=2)
    result = []
    for triangle in triangles:
        a,b,c = triangle
        u = [b[i]-a[i] for i in range(3)]; v = [c[i]-a[i] for i in range(3)]
        normal = [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        drop = max(range(3),key=lambda i:abs(normal[i]))
        axes = [i for i in range(3) if i!=drop]
        result.extend([[float(p[i])/.1 for i in axes] for p in triangle])
    return result


def dae_texture_assets(path):
    """Only collect assets actually referenced by this DAE, not stale scratch files."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path); ns = {'c':'http://www.collada.org/2005/11/COLLADASchema'}
    result = {}
    for entry in root.findall('c:library_images/c:image/c:init_from',ns):
        name = entry.text
        if not name or Path(name).name!=name or not name.startswith('cad_texture_'):
            raise ValueError('Nonportable CAD texture reference: '+str(name))
        result[name]=(Path(path).parent/name).read_bytes()
    return result
