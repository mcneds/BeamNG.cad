import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('elastic_inputs',Path(__file__).resolve().parents[1]/'tools/audit-elastic-inputs.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class ElasticInputAuditTests(unittest.TestCase):
    def test_section_probe_distinguishes_one_skin_from_two_contours(self):
        def skin(radius):
            yz=np.array([[-1,-1],[1,-1],[1,1],[-1,1]])*radius
            a=np.column_stack([np.zeros(4),yz]);b=a+np.array([1.,0.,0.]);tris=[]
            for i in range(4):
                j=(i+1)%4;tris.extend([[a[i],a[j],b[j]],[a[i],b[j],b[i]]])
            return np.array(tris)
        outer=skin(.02);inner=skin(.015)
        self.assertEqual([s['contours'] for s in mod.section_probe(outer)['samples']],[1,1,1])
        both=mod.section_probe(np.concatenate([outer,inner]))
        self.assertEqual([s['contours'] for s in both['samples']],[2,2,2])
        # The section tracer joins cut endpoints at 0.1 micrometre precision.
        np.testing.assert_allclose(sorted(both['samples'][0]['enclosed_contour_areas_m2']),[.0009,.0016],rtol=0,atol=1e-8)

    def test_open_and_reversed_faces_cannot_pass_as_closed_material(self):
        v=np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]])
        t=v[np.array([[0,2,1],[0,1,3],[0,3,2],[1,2,3]])]
        self.assertTrue(mod.topology(t,1e-7)['closed_oriented_surface'])
        self.assertEqual(mod.topology(t[:-1],1e-7)['boundary_edges'],3)
        bad=t.copy();bad[0]=bad[0,::-1]
        self.assertEqual(mod.topology(bad,1e-7)['inconsistent_oriented_edges'],3)
        self.assertFalse(mod.topology(bad,1e-7)['closed_oriented_surface'])
        self.assertFalse(mod.topology(np.concatenate([t,t[:1]]),1e-7)['closed_oriented_surface'])

if __name__=='__main__':unittest.main()
