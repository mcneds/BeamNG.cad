import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'beamng.cad/FramePipeline'),str(ROOT/'dependencies/cad-calibration/Test Harness')]
from tire_resolution import refine,DEFAULT_RAYS
from tire_revision import revise

class TireResolutionTests(unittest.TestCase):
    def options(self):return dict(numRays=16,nodeWeight=.1,hubNodeWeight=.08,radius=.28,hubRadius=.127,tireWidth=.18,hubWidth=.15,pressurePSI=12,wheelSideBeamSpring=10200,collision=True)

    def test_refinement_preserves_mass_inertia_and_all_authored_coefficients(self):
        o=self.options();saved=copy.deepcopy(o)
        for rays in (12,16,24,32):
            result,audit=refine(o,rays)
            self.assertAlmostEqual(2*rays*(result['nodeWeight']+result['hubNodeWeight']),32*(.1+.08))
            self.assertAlmostEqual(2*rays*(result['nodeWeight']*.28**2+result['hubNodeWeight']*.127**2),audit['spin_inertia_kg_m2'])
            self.assertEqual({k:v for k,v in result.items() if k not in ('numRays','nodeWeight','hubNodeWeight')},{k:v for k,v in o.items() if k not in ('numRays','nodeWeight','hubNodeWeight')})
            self.assertEqual(refine(result,rays)[0],result)
        self.assertEqual(o,saved)
        self.assertLess(refine(o,DEFAULT_RAYS)[1]['polygon_sagitta_m'],.0025)

    def test_invalid_resolution_and_mass_fail(self):
        for rays in (True,11,33,24.,float('nan')):
            with self.assertRaises(ValueError):refine(self.options(),rays)
        for value in (0,-1,float('nan')):
            with self.assertRaises(ValueError):refine(dict(self.options(),nodeWeight=value),24)

    def test_package_revision_changes_only_wheel_resolution_and_revokes_evidence(self):
        wheels={c:dict(tire_contract=dict(tread_nodes=32,hub_nodes=32,reinforcement_l_beams=32),mass_allocation={}) for c in ('FL','FR','RL','RR')}
        m=dict(wheels=wheels,expected_wheel_names=list(wheels),template_definition={'parameters':{}},limitations=[],verification={'status':'passed'},physical_evidence={})
        part=dict(beams=[['a','b',{'beamSpring':14010,'beamDamp':1860}]],nodes=[['a',0,0,0,{'nodeWeight':2}]],pressureWheels=[['name']]+[[c,self.options()] for c in wheels],props=[['steering','mesh']])
        before=copy.deepcopy(part);new,manifest=revise(part,m)
        for key in ('beams','nodes','props'):self.assertEqual(new[key],before[key])
        self.assertEqual(part,before);self.assertNotIn('verification',manifest);self.assertNotIn('physical_evidence',manifest)
        self.assertEqual(manifest['template_definition']['parameters']['tire_rays'],DEFAULT_RAYS)
        for row in new['pressureWheels'][1:]:self.assertEqual(row[-1]['numRays'],DEFAULT_RAYS)

if __name__=='__main__':unittest.main()
