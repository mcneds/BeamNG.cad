"""Preflight native CAD component graphs; this does not qualify frame physics."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
import components as c
from vehicle_templates import generate

p=argparse.ArgumentParser();p.add_argument('work',type=Path);p.add_argument('output',type=Path);p.add_argument('--cgal',required=True);a=p.parse_args()
project=json.loads((a.work/'project.json').read_text());definition=json.loads((a.work/'template.json').read_text())
frame=json.loads((a.work/'generation/source/mochi_raw.jbeam').read_text())['mochi']
a.output.mkdir(parents=True,exist_ok=False)
graph,part,wheels,checks,contract,meshes,bindings=generate(project,frame,definition,scratch=a.output,cgal=a.cgal)
c.write(a.output/'preflight.json',dict(nodes=len(graph.nodes),beams=len(graph.new_beams),components=graph.reports,kinematics=checks,device_contract=contract,mounts=graph.mounts))
print('NATIVE_CAD_GRAPH_PREFLIGHT',len(graph.nodes),len(graph.new_beams),len(graph.reports),flush=True)
