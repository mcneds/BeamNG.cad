import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from scipy.spatial.transform import Rotation
from test_components import box_geometry, module
from prepare_frame import write_stl


def sheet_geometry(folder, extent=(1., .8), offset=(0, 0, 0), density=2700.):
    folder.mkdir()
    x, y = np.asarray(extent) / 2
    points = np.array([[-x, -y, 0], [x, -y, 0], [x, y, 0], [-x, y, 0]]) + offset
    triangles = points[[[0, 1, 2], [0, 2, 3]]]
    cad = triangles[:, :, [0, 2, 1]].copy(); cad[:, :, 2] *= -1
    write_stl(folder / 'body.stl', cad)
    module.write(folder / 'geometry.json', {'Meshes': [{'Id': folder.name, 'Body': 'Sheet',
        'File': 'body.stl', 'BodyKind': 'surface', 'SurfaceAreaM2': float(4*x*y), 'DensityKgM3': density}]})
    return triangles


class SurfaceComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='surface-components-')
        self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def definition(self, **changes):
        sheet_geometry(self.root / 'sheet')
        return dict(Id='sheet', Name='Sheet', Template='panel', GeometryDirectory=str(self.root / 'sheet'),
                    Thickness=.002, SurfaceMassMode='thickness') | changes

    def test_sheet_matches_analytic_solid_plate_inertia_after_rotation_and_translation(self):
        triangles = sheet_geometry(self.root / 'analytic')
        rotation = Rotation.from_rotvec([.2, -.7, .6]).as_matrix()
        center = np.array([20., -30., 4.])
        mass, com, inertia, area = module.sheet_moments(triangles @ rotation.T + center, .002, 2700., .8)
        expected_mass = .8 * .002 * 2700
        expected = expected_mass / 12 * np.diag([.8**2 + .002**2, 1 + .002**2, 1 + .8**2])
        self.assertAlmostEqual(mass, expected_mass)
        np.testing.assert_allclose(com, center, atol=1e-12)
        np.testing.assert_allclose(inertia, rotation @ expected @ rotation.T, atol=1e-12)
        reversed_moments = module.sheet_moments(triangles[:, ::-1] @ rotation.T + center, .002, 2700., .8)
        np.testing.assert_allclose(reversed_moments[2], inertia, atol=1e-12)

    def test_thickness_panel_preserves_mass_com_inertia(self):
        component = self.definition()
        part, report = module.generate_component(component, [], self.root / 'result')
        self.assertAlmostEqual(report['mass']['actual_mass_kg'], 4.32)
        self.assertTrue(report['mass']['accepted'])
        self.assertLessEqual(report['mass']['inertia_relative_error'], .010000001)
        self.assertGreater(report['collision_triangles'], 0)
        self.assertGreater(report['mass']['minimum_node_mass_kg'], 0)
        self.assertEqual(report['mass_contributions']['sheet']['thickness_m'], .002)

    def test_thickness_and_material_must_be_explicit(self):
        component = self.definition(Thickness=0)
        with self.assertRaisesRegex(ValueError, 'thickness'): module.read_geometry(component)
        component['Thickness'] = .002
        path = self.root / 'sheet/geometry.json'; data = json.loads(path.read_text())
        data['Meshes'][0]['DensityKgM3'] = None; module.write(path, data)
        with self.assertRaisesRegex(ValueError, 'SolidWorks material'): module.read_geometry(component)
        component['SurfaceMassMode'] = 'ignore'
        self.assertEqual(module.read_geometry(component)[1][0], 0)

    def test_bad_native_area_cannot_silently_set_weight(self):
        triangles = sheet_geometry(self.root / 'bad')
        with self.assertRaisesRegex(ValueError, 'area differs'): module.sheet_moments(triangles, .002, 2700, 1.)

    def test_excluded_surface_has_no_physics_and_requires_parent(self):
        component = self.definition(SurfaceMassMode='ignore',Representation='visual_only')
        from component_representation import acknowledgement
        component['MassAcknowledgement']=acknowledgement(component)
        with self.assertRaisesRegex(ValueError, 'parent'): module.generate_component(component, [], self.root / 'missing')
        component['VisualParentId'] = 'frame'
        component['MassAcknowledgement']=acknowledgement(component)
        part, report = module.generate_component(component, [], self.root / 'visual')
        self.assertEqual(report['mass']['actual_mass_kg'], 0)
        self.assertEqual(report['qualification'], 'visual_only')
        self.assertEqual(module.node_table(part), {})
        self.assertEqual(module.beam_table(part), [])
        self.assertNotIn('triangles', part)
        self.assertEqual(part['flexbodies'][1][1], ['frame_visual_hosts'])
        with self.assertRaisesRegex(ValueError, 'physical parent'): module.generate_component(component, [{}], self.root / 'mount')

    def test_excluding_surface_preserves_solid_mass_and_inertia(self):
        component = self.definition(SurfaceMassMode='ignore')
        box_geometry(self.root / 'solid', (.4, .3, .2), (.1, .2, .3), mass=8.)
        solid = dict(GeometryDirectory=str(self.root / 'solid'))
        expected = module.read_geometry(solid)[1]
        sheet_path = self.root / 'sheet/geometry.json'; data = json.loads(sheet_path.read_text())
        solid_record = json.loads((self.root / 'solid/geometry.json').read_text())['Meshes'][0]
        solid_record['File'] = 'solid.stl'
        (self.root / 'sheet/solid.stl').write_bytes((self.root / 'solid/body.stl').read_bytes())
        data['Meshes'].append(solid_record); module.write(sheet_path, data)
        actual = module.read_geometry(component)[1]
        for a, b in zip(actual, expected): np.testing.assert_allclose(a, b, atol=1e-12)

    def test_parent_binding_keeps_existing_physics_and_groups(self):
        parent = {'nodes': [['id','posX','posY','posZ'], {'nodeWeight': 2, 'group': 'existing'},
                            ['a',0,0,0], ['b',1,0,0,{'group':['second'], 'nodeWeight':3}]],
                  'beams': [['id1:','id2:'], ['a','b',{'beamSpring':100}]]}
        before = copy.deepcopy(module.node_table(parent)); beams = copy.deepcopy(parent['beams'])
        parts = {'frame': parent, 'skin': {'nodes': [['id','posX','posY','posZ']]}}
        report = {'skin': {'qualification':'visual_only', 'visual_parent':'frame'}}
        self.assertEqual(module.bind_weightless_visuals(parts, report), {'frame_visual_hosts'})
        self.assertEqual(parent['beams'], beams)
        for name, node in module.node_table(parent).items():
            self.assertEqual(node['position'], before[name]['position'])
            self.assertEqual(node['options']['nodeWeight'], before[name]['options']['nodeWeight'])
            self.assertIn('frame_visual_hosts', node['options']['group'])
        self.assertIn('existing', module.node_table(parent)['a']['options']['group'])
        report['skin']['visual_parent'] = 'skin'
        with self.assertRaisesRegex(ValueError, 'physical parent'): module.bind_weightless_visuals(parts, report)


if __name__ == '__main__': unittest.main()
