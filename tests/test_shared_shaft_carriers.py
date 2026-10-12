import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_vehicle_template_graph import fixture,c,generate


class SharedShaftCarrierTests(unittest.TestCase):
    def test_shared_center_preserves_mass_position_and_plunge_without_attachment_beams(self):
        for variant in ('primary','independent_rear'):
            with self.subTest(variant=variant):
                project,frame,spec,cad=fixture(variant)
                spec['parameters']['shared_halfshaft_carrier_nodes']=True
                with patch.object(c,'read_geometry',side_effect=cad):graph,*_=generate(project,frame,spec)
                for owner,declaration in spec['halfshafts'].items():
                    node=owner+'_outer';joint=next(j for j in graph.joints if j['id']==node)
                    self.assertEqual(joint['kind'],'shared_ball');self.assertEqual(joint['nodes'],[node])
                    np.testing.assert_allclose(graph.point(node),declaration['outer'],atol=1e-12)
                    self.assertIn(node,graph.mass_allocations[joint['parent']])
                    self.assertIn(node,graph.mass_allocations[owner])
                    mass=sum(a.get(node,0) for a in graph.mass_allocations.values())
                    self.assertAlmostEqual(graph.nodes[node]['options']['nodeWeight'],mass)
                    plunge=next(j for j in graph.joints if j['id']==owner+'_plunge')
                    self.assertEqual(plunge['travel_m'],2*declaration['plunge_m'])
                    self.assertFalse(any(j['kind']=='spherical' and j['id']==node for j in graph.joints))
                for owner,allocation in graph.mass_allocations.items():
                    if owner in spec['halfshafts']:
                        comp=next(v for v in project['Components'] if v['Id']==owner)
                        self.assertAlmostEqual(sum(allocation.values()),cad(comp)[1][0])

    def test_default_keeps_existing_joint_topology(self):
        project,frame,spec,cad=fixture('primary')
        with patch.object(c,'read_geometry',side_effect=cad):graph,*_=generate(project,frame,spec)
        for owner in spec['halfshafts']:
            self.assertEqual(next(j for j in graph.joints if j['id']==owner+'_outer')['kind'],'spherical')


if __name__=='__main__':unittest.main()
