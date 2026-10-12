import copy,itertools,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from rigid_revision import refit


class RigidRevisionTests(unittest.TestCase):
    def test_loaded_priority_preserves_geometry_boundary_and_stability(self):
        from rigid_bracing import budget_connections
        from frame_harness.build import node_table
        points=[(0.,0.,0.),(1.,0.,0.),(0.,1.,0.),(0.,0.,1.)]
        part=dict(nodes=[['id','posX','posY','posZ']]+[[n,*p,dict(nodeWeight=2)] for n,p in zip('abcd',points)],
                  beams=[['id1:','id2:']]+[[a,b,dict(beamSpring=100,beamDamp=1)] for a,b in itertools.combinations('abcd',2)])
        before=copy.deepcopy(part)
        selected,report=refit(part,{'arm':dict.fromkeys('abcd',2)},'arm',priority_nodes=['a'],priority=4.)
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual([r[:2] for r in part['beams']],[r[:2] for r in before['beams']])
        self.assertEqual(report['priority_nodes'],['a'])
        self.assertLessEqual(budget_connections(part,node_table(part),selected)['final_step_eigenvalue'],3.2)
        for invalid in (0,float('nan'),17):
            with self.assertRaises(ValueError):refit(copy.deepcopy(before),{'arm':dict.fromkeys('abcd',2)},'arm',priority=invalid)

    def test_more_internal_damping_keeps_stiffness_mass_and_topology(self):
        from rigid_bracing import budget_connections
        from frame_harness.build import node_table
        points=[(0.,0.,0.),(1.,0.,0.),(0.,1.,0.),(0.,0.,1.)]
        base=dict(nodes=[['id','posX','posY','posZ']]+[[n,*p,dict(nodeWeight=2)] for n,p in zip('abcd',points)],
                  beams=[['id1:','id2:']]+[[a,b,dict(beamSpring=100,beamDamp=1)] for a,b in itertools.combinations('abcd',2)])
        outputs=[]
        for allowance in (2.,2.8):
            part=copy.deepcopy(base)
            changed,report=refit(part,{'arm':dict.fromkeys('abcd',2)},'arm',damping_budget=allowance)
            self.assertEqual(part['nodes'],base['nodes'])
            self.assertEqual(report['requested_internal_step_budget'],allowance)
            outputs.append(copy.deepcopy(part))
            self.assertLessEqual(budget_connections(part,node_table(part),changed)['final_step_eigenvalue'],3.2)
        for a,b in zip(outputs[0]['beams'][1:],outputs[1]['beams'][1:]):
            self.assertEqual(a[:2],b[:2]);self.assertEqual(a[-1]['beamSpring'],b[-1]['beamSpring'])
            self.assertGreater(b[-1]['beamDamp'],a[-1]['beamDamp'])
        for a,b in zip(outputs[0]['torsionbars'][1:],outputs[1]['torsionbars'][1:]):
            self.assertEqual(a[:4],b[:4]);self.assertEqual(a[-1]['spring'],b[-1]['spring'])
            self.assertGreater(b[-1]['damp'],a[-1]['damp'])
        for bad in (float('nan'),1.9,3.3):
            with self.assertRaisesRegex(ValueError,'budget'):refit(base,{'arm':dict.fromkeys('abcd',2)},'arm',damping_budget=bad)

    def test_refit_cannot_add_a_suspension_spring_or_change_shared_hinge(self):
        points={'a':(0,0,0),'b':(1,0,0),'c':(0,1,0),'d':(0,0,1),'frame':(2,2,2)}
        edges=[[a,b,dict(beamSpring=100.,beamDamp=1.)] for a,b in itertools.combinations('abcd',2)]
        part=dict(nodes=[['id','posX','posY','posZ']]+[[n,*p,dict(nodeWeight=2)] for n,p in points.items()],
                  beams=[['id1:','id2:']]+edges+[['d','frame',dict(beamType='|BOUNDED',beamSpring=35000,beamDamp=2000)]],
                  hydros=[['id1:','id2:'],['c','frame',dict(beamSpring=500,beamDamp=5)]])
        before=copy.deepcopy(part)
        changed,report=refit(part,{'arm':dict.fromkeys('abcd',.1),'upright':dict(a=.2,b=.2)},'arm')
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual(part['hydros'],before['hydros'])
        self.assertEqual(part['beams'][-1],before['beams'][-1])
        self.assertEqual(part['beams'][1],before['beams'][1])
        self.assertEqual([r[:2] for r in part['beams']],[r[:2] for r in before['beams']])
        self.assertEqual(report['assembled_node_mass_kg'],8)
        self.assertTrue(all(set(r[:4])<=set('abcd') for r in part['torsionbars'][1:]))
        self.assertTrue(changed)


if __name__=='__main__':unittest.main()
