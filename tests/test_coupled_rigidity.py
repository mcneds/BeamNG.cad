import copy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from coupled_rigidity import fit,logdet_objective


class CoupledRigidityTests(unittest.TestCase):
    def test_unimproved_iteration_limit_does_not_export_candidate(self):
        from scipy.optimize import OptimizeResult
        part,options,_=self.fixture();before=copy.deepcopy(part)
        def stopped(fun,x,**kwargs):
            return OptimizeResult(x=x,fun=fun(x)[0],success=False,status=1,nit=1000,message='iteration limit')
        with patch('motion_objective.front_columns',return_value=(np.eye(12)[:,:2],{})),patch('coupled_rigidity.minimize',side_effect=stopped):
            with self.assertRaisesRegex(ValueError,'iteration limit'):fit(part,options,400,'motion',{})
        self.assertEqual(part,before)

    def test_motion_fit_preserves_free_hinge_and_physical_spring(self):
        part,options,points=self.fixture();before=copy.deepcopy(part)
        gradients=np.random.default_rng(3).normal(size=(12,2))
        with patch('motion_objective.front_columns',return_value=(gradients,{'test':True})):
            report=fit(part,options,400,'motion',{})
        self.assertEqual(report['nullity'],7)
        self.assertLess(report['objective_final'],report['objective_initial'])
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual(part['beams'][-1],before['beams'][-1])
        for row,old in zip(part['beams'][1:-1],before['beams'][1:-1]):
            self.assertEqual(row[:2],old[:2])
            self.assertEqual(row[-1]['beamStrength'],old[-1]['beamStrength'])
            self.assertGreater(row[-1]['beamSpring'],0)
        self.assertLessEqual(report['maximum_internal_frequency_hz'],400*(1+1e-10))

    def fixture(self):
        points=np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]])
        part={'nodes':[['id','posX','posY','posZ']]+[[n,*p,{'nodeWeight':3.}] for n,p in zip('abcd',points)],
              'beams':[['id1:','id2:']]+[[a,b,{'beamSpring':100000.,'beamDamp':4.,'beamStrength':30000.}] for a,b in ('ab','ac','bc','ad','bd')]}
        options=[r[-1] for r in part['beams'][1:]]
        part['beams'].append(['c','d',{'beamType':'|BOUNDED','beamSpring':1000.,'beamDamp':7.}])
        return part,options,points

    def test_free_hinge_and_physical_spring_are_preserved(self):
        part,options,points=self.fixture();before=copy.deepcopy(part)
        report=fit(part,options,400)
        self.assertEqual(report['nullity'],7)  # six global modes plus intended hinge rotation
        self.assertEqual(part['nodes'],before['nodes'])
        self.assertEqual(part['beams'][-1],before['beams'][-1])
        self.assertEqual([r[:2] for r in part['beams']],[r[:2] for r in before['beams']])
        matrix=np.zeros((12,12))
        for row in part['beams'][1:-1]:
            a,b=['abcd'.index(n) for n in row[:2]];d=points[b]-points[a];d/=np.linalg.norm(d)
            col=np.zeros((4,3));col[a]=-d;col[b]=d
            matrix+=row[-1]['beamSpring']*np.outer(col.ravel(),col.ravel())/3
            self.assertEqual(row[-1]['beamStrength'],30000.)
        hinge=np.zeros((4,3));hinge[2,2]=1
        np.testing.assert_allclose(matrix@hinge.ravel(),0,atol=1e-8)
        eigen=np.linalg.eigvalsh(matrix)
        self.assertLessEqual(eigen[-1],(2*math.pi*400)**2*(1+1e-10))
        self.assertEqual(np.count_nonzero(eigen>1),5)

    def test_unselected_or_unsupported_options_fail_closed(self):
        part,options,_=self.fixture()
        with self.assertRaisesRegex(ValueError,'missing'):fit(part,options+[{}],400)
        with self.assertRaisesRegex(ValueError,'normal'):fit(part,options+[part['beams'][-1][-1]],400)
        for frequency in (99,601,float('nan')):
            with self.assertRaisesRegex(ValueError,'frequency'):fit(part,options,frequency)

    def test_logdet_gradient_and_free_hinge(self):
        b=np.random.default_rng(0).normal(size=(4,8));x=np.linspace(.4,1.,8)
        value,derivative=logdet_objective(x,b)
        numerical=[]
        for i in range(len(x)):
            delta=np.zeros_like(x);delta[i]=1e-6
            numerical.append((logdet_objective(x+delta,b)[0]-logdet_objective(x-delta,b)[0])/2e-6)
        np.testing.assert_allclose(derivative,numerical,rtol=1e-6,atol=1e-7)
        part,options,_=self.fixture();before=copy.deepcopy(part)
        report=fit(part,options,400,'logdet')
        self.assertEqual(report['nullity'],7)
        self.assertLessEqual(report['maximum_internal_frequency_hz'],400*(1+1e-10))
        self.assertEqual(part['beams'][-1],before['beams'][-1])


if __name__=='__main__':unittest.main()
