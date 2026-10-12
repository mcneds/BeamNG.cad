import copy
import unittest
import numpy as np
from frame_harness.reflection import constraint_groups,average_groups


class ReflectionTests(unittest.TestCase):
    def fixture(self):
        part=dict(cadGraphSymmetry=dict(center_x_m=0),
            nodes=[['id','posX','posY','posZ'],['l',-1.,0.,0.],['r',1.,0.,0.],['top',0.,0.,1.]],
            beams=[['id1:','id2:'],['l','top',{}],['r','top',{}],['l','r',{}]])
        sections={name:dict(a=[x,0,0],b=[x,0,1],area_m2=.01,Iy_m4=.001,Iz_m4=.0010001,
            J_m4=.0020001,radius_m=.1,method='circular Saint-Venant torsion') for name,x in [('left',-1.),('right',1.)]}
        sections['right']['Iy_m4'],sections['right']['Iz_m4']=sections['right']['Iz_m4'],sections['right']['Iy_m4']
        audits=[dict(name=n,volume_m3=.01,native_mass_kg=78.5) for n in sections]
        materials={n:dict(density_kg_m3=7850.,young_pa=205e9,poisson=.29,yield_pa=300e6,ultimate_pa=500e6) for n in sections}
        return part,sections,audits,materials

    def test_only_audited_reflection_ties_material_constraints(self):
        values=self.fixture();original=copy.deepcopy(values)
        groups,report=constraint_groups(*values)
        self.assertTrue(report['applied']);self.assertEqual(groups[0],groups[1]);self.assertNotEqual(groups[0],groups[2])
        np.testing.assert_array_equal(average_groups([2.,4.,7.],groups),[3.,3.,7.])
        self.assertEqual(values,original)
        # Chain rule for the grouped objective is a sum, not an average.
        gradient=np.array([1.,3.,5.]);reduced=np.bincount(groups,weights=gradient)
        np.testing.assert_array_equal(reduced,[4.,5.])

    def test_hull_symmetry_cannot_override_material_geometry_or_reference_asymmetry(self):
        for change in ('undeclared','missing','material','path','area','mass','unsupported'):
            with self.subTest(change=change):
                part,sections,audits,materials=self.fixture()
                if change=='undeclared':part.pop('cadGraphSymmetry')
                elif change=='missing':sections.pop('left')
                elif change=='material':materials['right']['young_pa']*=.9
                elif change=='path':sections['right']['a'][1]=.001
                elif change=='area':sections['right']['area_m2']*=1.01
                elif change=='mass':audits[0]['native_mass_kg']*=1.01
                else:sections['right']['method']='rectangular section'
                groups,report=constraint_groups(part,sections,audits,materials)
                self.assertFalse(report['applied']);np.testing.assert_array_equal(groups,np.arange(3))


if __name__=='__main__':unittest.main()
