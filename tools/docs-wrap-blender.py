"""Capture real production wrap stages for the documentation. Run with Blender --background."""
import bpy
import importlib.util
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('frame_wrap', root/'beamng.cad/FramePipeline/generation/AlphaWrap.py')
wrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrap)
job = json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
output = Path(job['output']); output.mkdir(parents=True, exist_ok=True)
wrap.FRAME_FILE = job['frame']
wrap.CGAL_PYTHON = job['cgal']
wrap.PRUNING_PROXY_DIVISOR = job['divisor']
wrap.PRUNING_PROXY_OFFSET_RATIO = job['ratio']
wrap.GRID_I, wrap.GRID_J, wrap.GRID_K = job.get('grid', [3,5,7])
wrap.GRID_SHRINK_OFFSET = .01
wrap.GRID_WELD_DISTANCE = .15
wrap.ENFORCE_X_SYMMETRY = False
wrap.WRAPPED_HULL_OUTPUT = str(output/'hull.off')
wrap.main()

def capture(obj, evaluated):
    if evaluated:
        bpy.context.view_layer.update()
        obj = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = obj.to_mesh()
    try:
        mesh.calc_loop_triangles()
        return dict(positions=[[round(v,7) for v in obj.matrix_world@p.co] for p in mesh.vertices],
                    triangles=[list(t.vertices) for t in mesh.loop_triangles],
                    edges=[list(e.vertices) for e in mesh.edges])
    finally: obj.to_mesh_clear()

grid = bpy.data.objects[wrap.GRID_NAME]
stages = {'proxy':capture(bpy.data.objects[wrap.PRUNING_PROXY_NAME],False), 'grid':capture(grid,False), 'hull':capture(grid,True)}
grid.modifiers['MergeCloseShrinkwrapVertices'].show_viewport=False
stages['projected']=capture(grid,True)
if job.get('includeSource'):stages['cad']=capture(bpy.data.objects[wrap.FRAME_TARGET_NAME],False)
(output/'stages.json').write_text(json.dumps(stages,separators=(',',':')))
print('DOCS_CAPTURE '+str(output/'stages.json'),flush=True)
