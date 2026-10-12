import copy
import sys
import unittest
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
import components
from fixed_structure import attach


class FixedStructureTests(unittest.TestCase):
    def test_support_choice_avoids_nearby_tiny_mass_bottleneck(self):
        part=dict(nodes=[['id','posX','posY','posZ'],['child',0.,0.,0.,dict(nodeWeight=2.)]],beams=[['id1:','id2:']])
        parents=[]
        for prefix,scale,mass in [('light',.1,1e-5),('loaded',.2,2.)]:
            for i,xyz in enumerate(((-1,-1,-1),(1,1,-1),(1,-1,1),(-1,1,1))):
                name=prefix+str(i);parents.append(name)
                part['nodes'].append([name,*[v*scale for v in xyz],dict(nodeWeight=mass)])
        rows,_=attach(part,['child'],parents)
        self.assertTrue(all(row[1].startswith('loaded') for row in rows))

    def test_subgram_nodes_hold_gravity_without_changing_mass(self):
        part=dict(nodes=[['id','posX','posY','posZ']], beams=[['id1:','id2:']])
        parents=[]
        for i,p in enumerate(((-1,-1,-1),(1,1,-1),(1,-1,1),(-1,1,1))):
            parents.append('p'+str(i));part['nodes'].append([parents[-1],*p,dict(nodeWeight=2)])
        for i,m in enumerate((.0004,.001,.2)):
            part['nodes'].append(['c'+str(i),.1*i,.02,.1,dict(nodeWeight=m)])
        original=copy.deepcopy(part['nodes'])
        rows,report=attach(part,['c0','c1','c2'],parents)
        self.assertEqual(original,part['nodes'])
        self.assertEqual(12,len(rows))
        points={r[0]:np.array(r[1:4]) for r in part['nodes'][1:]}
        for i,m in enumerate((.0004,.001,.2)):
            k=np.zeros((3,3))
            for a,b,o in rows:
                if a!='c'+str(i):continue
                d=points[b]-points[a];d/=np.linalg.norm(d)
                k+=o['beamSpring']*np.outer(d,d)
            sag=np.linalg.solve(k,[0,0,-9.81*m])
            self.assertLess(np.linalg.norm(sag),.0001)
            self.assertLessEqual(np.linalg.eigvalsh(k/m)[-1],(2*np.pi*160)**2)

    def test_rejects_planar_support_and_shared_nodes(self):
        part=dict(nodes=[['id','posX','posY','posZ']]+[
            [n,x,y,0,dict(nodeWeight=1)] for n,x,y in
            [('c',0,0),('a',-1,0),('b',1,0),('d',0,1),('e',0,-1)]],beams=[['id1:','id2:']])
        with self.assertRaisesRegex(ValueError,'coplanar'):attach(part,['c'],['a','b','d','e'])
        with self.assertRaisesRegex(ValueError,'disjoint'):attach(part,['c'],['a','b','d','c'])


if __name__=='__main__':unittest.main()
