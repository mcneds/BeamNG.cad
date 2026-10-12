import copy,itertools,sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from frame_reference import fit


class FrameReferenceTests(unittest.TestCase):
    def test_pivot_priority_preserves_rigid_motions_and_changes_only_internal_fit(self):
        from frame_harness.build import node_table
        xyz=np.array(list(itertools.product((-.5,.5),(-1.,1.),(0.,.7))))
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':3.}] for i,p in enumerate(xyz)],
              'beams':[['id1:','id2:']]+[[str(i),str(j),dict(beamSpring=100.,beamDamp=2.)]
                       for i,j in itertools.combinations(range(8),2)],
              'cadMountPatches':{'pivot':dict(mode='joint',parents=['0'])}}
        uniform=copy.deepcopy(part);fit(uniform,[str(i) for i in range(8)],300)
        fit(part,[str(i) for i in range(8)],300,4)
        self.assertEqual(part['nodes'],uniform['nodes'])
        self.assertFalse(np.allclose([r[-1]['beamSpring'] for r in part['beams'][1:]],
                                    [r[-1]['beamSpring'] for r in uniform['beams'][1:]]))
        K=np.zeros((24,24))
        for a,b,o in part['beams'][1:]:
            i,j=int(a),int(b);d=xyz[j]-xyz[i];d/=np.linalg.norm(d)
            g=np.zeros((8,3));g[i]=-d;g[j]=d;K+=o['beamSpring']*np.outer(g.ravel(),g.ravel())
        for axis in np.eye(3):
            for motion in (np.tile(axis,(8,1)),np.cross(np.tile(axis,(8,1)),xyz)):
                self.assertLess(np.linalg.norm(K@motion.ravel())/np.linalg.norm(K),1e-12)
        self.assertLessEqual(np.linalg.eigvalsh(K/3)[-1],(2*np.pi*300)**2*(1+1e-10))

    def test_added_pivot_braces_stay_inside_the_chassis(self):
        xyz=list(itertools.product((-.5,.5),(-1.,1.),(0.,.7)))
        omitted={frozenset(('0','1')),frozenset(('1','2')),frozenset(('0','2'))}
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':3.}] for i,p in enumerate(xyz)],
              'beams':[['id1:','id2:']]+[[str(i),str(j),dict(beamSpring=100.,beamDamp=2.)]
                       for i,j in itertools.combinations(range(8),2) if frozenset((str(i),str(j))) not in omitted],
              'cadMountPatches':{str(i):dict(mode='joint',parents=[str(i)]) for i in range(3)}}
        part['nodes'].append(['moving',2.,0.,0.,{'nodeWeight':2.}])
        external=['0','moving',dict(beamSpring=10000.,beamDamp=500.,beamType='|BOUNDED')]
        part['beams'].append(copy.deepcopy(external));before=copy.deepcopy(part['nodes'])
        _,report=fit(part,[str(i) for i in range(8)],300)
        self.assertEqual(report['added_chassis_beams'],3)
        self.assertEqual({frozenset(r[:2]) for r in part['beams'][-3:]},omitted)
        self.assertEqual([r for r in part['beams'][1:] if 'moving' in r[:2]],[external])
        self.assertEqual(part['nodes'],before)

    def test_existing_graph_preserves_geometry_mass_and_external_spring(self):
        xyz=list(itertools.product((-.5,.5),(-1.,1.),(0.,.7)))
        part={'nodes':[['id','posX','posY','posZ']]+[[str(i),*p,{'nodeWeight':3.}] for i,p in enumerate(xyz)],
              'beams':[['id1:','id2:']]+[[str(i),str(j),dict(beamSpring=100.,beamDamp=2.,beamStrength=1000.,beamDeform=500.)]
                       for i,j in itertools.combinations(range(8),2)]}
        part['nodes'].append(['moving',2.,0.,0.,{'nodeWeight':2.}])
        part['beams'].append(['0','moving',dict(beamSpring=10000.,beamDamp=500.,beamType='|BOUNDED')])
        before=copy.deepcopy(part)
        options,report=fit(part,[str(i) for i in range(8)],300)
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual([r[:2] for r in part['beams']],[r[:2] for r in before['beams']])
        self.assertEqual(part['beams'][-1],before['beams'][-1])
        self.assertGreater(report['minimum_internal_frequency_hz'],0)
        self.assertLessEqual(report['minimum_internal_frequency_hz'],300)
        self.assertEqual(len(options),28)
        self.assertFalse(report['material_response_qualified'])

    def test_mechanism_or_release_cannot_be_presented_as_rigid_frame(self):
        p={'nodes':[['id','posX','posY','posZ'],['a',0,0,0,{'nodeWeight':1.}],['b',1,0,0,{'nodeWeight':1.}],['c',0,1,0,{'nodeWeight':1.}],['d',0,0,1,{'nodeWeight':1.}]],
           'beams':[['id1:','id2:'],['a','b',{'beamSpring':10.,'breakGroup':'bolt'}]]}
        with self.assertRaisesRegex(ValueError,'release'):fit(p,['a','b','c','d'],300)
        p['beams'][1][-1].pop('breakGroup')
        with self.assertRaisesRegex(ValueError,'mechanism'):fit(p,['a','b','c','d'],300)


if __name__=='__main__':unittest.main()
