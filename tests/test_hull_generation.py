import importlib.util
import sys
from pathlib import Path
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('shell_generation',ROOT/'beamng.cad/FramePipeline/generation/JBeamShellGenerator.py')
shell=importlib.util.module_from_spec(spec);sys.modules[spec.name]=shell;spec.loader.exec_module(shell)

class HullGenerationTests(unittest.TestCase):
    def graph(self, scale=(1,1,1)):
        vertices,triangles=shell.read_off(ROOT/'tests/fixtures/internal-motion.off')
        vertices=[shell.Vec3(*(v*s for v,s in zip(p,scale))) for p in vertices]
        cage,ids,stations,edges=shell.create_sparse_bottom_supports(vertices)
        attachments=shell.create_shell_attachments(vertices,cage,stations)
        return vertices,triangles,cage,ids,stations,edges,attachments

    def assert_independent_rank(self, positions, edges):
        positions=np.array([tuple(p) for p in positions]);rows=[]
        for a,b in edges:
            d=positions[a]-positions[b];d/=np.linalg.norm(d)
            row=np.zeros_like(positions);row[a]=d;row[b]=-d;rows.append(row.ravel())
        self.assertEqual(np.linalg.matrix_rank(rows,tol=1e-9),3*len(positions)-6)

    def test_actual_failed_generation_repaired_with_one_local_beam(self):
        v,t,c,ids,stations,ce,a=self.graph();se=shell.triangle_edges(t)
        positions,edges=shell.structural_graph(v,c,se,ce,a)
        self.assertEqual(shell.rigidity_report(positions,edges)['extra_modes'],1)
        original=set(a);before=[tuple(p) for p in positions]
        result=shell.stabilize_local_attachments(v,c,stations,se,ce,a)
        self.assertEqual(result['extra_modes'],0);self.assertEqual(len(set(a)-original),1)
        positions,edges=shell.structural_graph(v,c,se,ce,a)
        self.assertEqual([tuple(p) for p in positions],before)
        self.assert_independent_rank(positions,edges)
        stable=list(a);shell.stabilize_local_attachments(v,c,stations,se,ce,a)
        self.assertEqual(a,stable)

    def test_varied_generations_have_aligned_constrained_reference_nodes(self):
        for scale in ((1,1,1),(1.05,.97,1.02),(.7,1.2,.8)):
            v,t,c,ids,stations,ce,a=self.graph(scale);se=shell.triangle_edges(t)
            shell.stabilize_local_attachments(v,c,stations,se,ce,a)
            names=['sh%04d'%i for i in range(len(v))]
            refs=shell.aligned_reference_nodes(v,names,c,ids,stations,ce,a)
            points=dict(zip(names+ids,v+c));ref=points[refs[0]]
            for name,axis in zip(refs[1:],(1,0,2)):
                delta=tuple(points[name]-ref)
                self.assertGreater(delta[axis],0)
                self.assertTrue(all(abs(value)<1e-10 for i,value in enumerate(delta) if i!=axis))
            positions,edges=shell.structural_graph(v,c,se,ce,a)
            self.assert_independent_rank(positions,edges)
            self.assertEqual(shell.rigidity_report(positions,edges)['nullity'],6)

if __name__=='__main__':unittest.main()
