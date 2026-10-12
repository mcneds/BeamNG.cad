import copy,sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from rigid_visuals import render

class RigidVisualTests(unittest.TestCase):
    def test_rest_mesh_and_physics_are_preserved_without_flexbody_locator(self):
        part=dict(nodes=[['id','posX','posY','posZ'],['a',2.,3.,4.,dict(nodeWeight=1)],
                         ['b',3.,3.,4.,dict(nodeWeight=2)],['c',2.,4.,4.,dict(nodeWeight=3)]],
                  beams=[['id1:','id2:'],['a','b',dict(beamSpring=500)]],
                  flexbodies=[['mesh','[group]:','nonFlexMaterials'],['tiny',['body'],[]]])
        before=copy.deepcopy(part);tri=np.array([[[2.1,3.2,4],[2.2,3.2,4],[2.1,3.3,4]]])
        output,report=render('body',part,dict(body=dict(a=1,b=2,c=3)),[(dict(Id='tiny'),tri)],['tiny'])
        self.assertEqual(part['nodes'],before['nodes']);self.assertEqual(part['beams'],before['beams'])
        self.assertEqual(len(part['flexbodies']),1);self.assertEqual(len(part['props']),2)
        ref=part['props'][1][2];origin=next(r[1:4] for r in part['nodes'][1:] if r[0]==ref)
        np.testing.assert_allclose(output[0][1]+origin,tri)
        render('body',part,dict(body=dict(a=1,b=2,c=3)),[(dict(Id='tiny'),tri)],['tiny'])
        self.assertEqual(len(part['props']),2)

if __name__=='__main__':unittest.main()
