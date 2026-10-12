"""Headless Blender adapter for the preserved AlphaWrap geometry algorithm."""
import importlib.util
import json
from pathlib import Path
import sys

job = json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text(encoding='utf-8-sig'))
spec = importlib.util.spec_from_file_location('alpha_wrap', Path(__file__).parent / 'generation' / 'AlphaWrap.py')
wrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrap)
hull = job['hull']
wrap.FRAME_FILE = job['frame']
wrap.CGAL_PYTHON = job['cgal']
wrap.GRID_I, wrap.GRID_J, wrap.GRID_K = hull['Width'], hull['Height'], hull['Length']
wrap.GRID_SHRINK_OFFSET, wrap.GRID_WELD_DISTANCE = hull['Offset'], hull['Weld']
wrap.PRUNING_PROXY_DIVISOR = hull['ProxyDivisor']
wrap.PRUNING_PROXY_OFFSET_RATIO = hull.get('ProxyOffsetRatio', 100.0)
wrap.ENFORCE_X_SYMMETRY = hull['Symmetry']
wrap.SYMMETRY_BISECT_FLIP = hull.get('SymmetryBisectFlip', False)
wrap.SYMMETRY_MERGE_DISTANCE = hull.get('SymmetryMergeDistance', 0.0001)
wrap.WRAPPED_HULL_OUTPUT = job['off']
wrap.main()
