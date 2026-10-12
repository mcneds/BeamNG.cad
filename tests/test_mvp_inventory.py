import copy
import json
from pathlib import Path
import tempfile
import unittest
from test_components import box_geometry, module
from test_surface_components import sheet_geometry
from mvp_inventory import inventory


class MvpInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mvp-inventory-');self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def project(self):
        box_geometry(self.root/'engine',(.4,.5,.6),mass=12.)
        return dict(Components=[dict(Id='engine',Name='My engine',MvpRole='engine',Template='bulk',BodyIds=['engine'],
                    GeometryDirectory=str(self.root/'engine'),Selections=[dict(Kind='body',Reference='persistent')])],Anchors=[],Connections=[])
    def test_tags_keep_native_ownership_and_do_not_qualify_mechanisms(self):
        project=self.project();result=inventory(project,'vehicle.SLDASM.beamng-project.json')
        self.assertEqual(result['components'][0]['selections'],project['Components'][0]['Selections'])
        self.assertEqual(result['components'][0]['mass_kg'],12)
        roles={r['id']:r for r in result['roles']}
        self.assertEqual(roles['engine']['status'],'tagged');self.assertEqual(roles['cvt']['status'],'missing')
        self.assertFalse(result['tagging_complete']);self.assertEqual(result['qualification'],'unqualified')
        self.assertTrue(result['components'][0]['files_sha256'])
    def test_missing_geometry_and_duplicate_single_roles_are_visible(self):
        project=self.project();duplicate=copy.deepcopy(project['Components'][0]);duplicate.update(Id='copy',Name='Other',GeometryDirectory='')
        project['Components'].append(duplicate);result=inventory(project)
        self.assertEqual(next(r for r in result['roles'] if r['id']=='engine')['status'],'duplicate')
        self.assertIn('multiple component owners',' '.join(result['errors']))
        self.assertEqual(result['components'][1]['geometry_status'],'missing')
    def test_surfaces_can_be_tagged_before_thickness_is_known(self):
        project=self.project();sheet_geometry(self.root/'sheet')
        project['Components'].append(dict(Id='panel',Name='Roof',MvpRole='panel',Template='panel',BodyIds=['sheet'],GeometryDirectory=str(self.root/'sheet')))
        result=inventory(project);sheet=result['components'][1]
        self.assertEqual(sheet['geometry_status'],'exported');self.assertEqual(sheet['mass_status'],'needs_input')
        self.assertIn('thickness',sheet['mass_issue']);self.assertEqual(result['errors'],[])
    def test_associations_are_candidates_with_explicit_joint_review(self):
        project=self.project();frame=copy.deepcopy(project['Components'][0]);frame.update(Id='frame',BodyIds=['frame'],MvpRole='frame',Template='calibrated_frame',GeometryDirectory='')
        project['Components'].append(frame)
        project['Anchors']=[dict(Id='a',Name='A',ComponentId='engine',Status='resolved'),dict(Id='b',Name='B',ComponentId='frame',Status='resolved')]
        project['Connections']=[dict(Id='mount',AnchorA='a',AnchorB='b')]
        result=inventory(project);relation=next(a for a in result['planned_associations'] if a['from_role']=='frame' and a['to_role']=='engine')
        self.assertEqual(relation['candidate_connections'],['mount'])
        self.assertEqual(relation['status'],'review_hardpoints_and_joint')
        self.assertTrue(any(r['id']=='rl_trailing_arm' for r in result['roles']))
        self.assertTrue(any(a['from_role']=='rear_final_drive' and a['to_role']=='front_propshaft' for a in result['planned_associations']))
    def test_geometry_tampering_changes_inventory_hash(self):
        project=self.project();before=inventory(project)
        path=self.root/'engine/geometry.json';data=json.loads(path.read_text());data['Meshes'][0]['MassKg']=13;module.write(path,data)
        after=inventory(project)
        self.assertNotEqual(before['components'][0]['files_sha256'],after['components'][0]['files_sha256'])
    def test_templates_change_required_groups_and_associations_without_losing_tags(self):
        project=self.project();project['Components'][0]['MvpRole']='rl_trailing_arm'
        default=inventory(project);self.assertTrue(any(r['id']=='rl_trailing_arm' for r in default['roles']))
        project['MvpTemplates']=[dict(Category='rear_suspension',Template='double_wishbone'),dict(Category='drivetrain',Template='cvt_rear_drive')]
        changed=inventory(project);roles={r['id'] for r in changed['roles']}
        self.assertNotIn('rl_trailing_arm',roles);self.assertIn('rl_upper_wishbone',roles)
        self.assertIn('rl_upright',roles);self.assertNotIn('front_propshaft',roles);self.assertNotIn('fl_halfshaft',roles)
        self.assertIn('fl_wheel',roles);self.assertIn('rear_diff',roles)
        self.assertEqual(changed['outside_current_setup'],['engine'])
        self.assertEqual(changed['components'][0]['selections'],default['components'][0]['selections'])
        self.assertTrue(all(a['from_role']!='rl_trailing_arm' and a['to_role']!='rl_trailing_arm' for a in changed['planned_associations']))
    def test_unknown_template_cannot_fall_back_to_a_different_layout(self):
        project=self.project();project['MvpTemplates']=[dict(Category='rear_suspension',Template='unknown')]
        with self.assertRaisesRegex(ValueError,'Unknown Rear suspension'):inventory(project)
    def test_multiple_propshaft_sections_are_tags_requiring_a_reviewed_chain(self):
        project=self.project();project['Components'][0]['MvpRole']='front_propshaft'
        box_geometry(self.root/'shaft2',(.03,.6,.03),mass=1.)
        project['Components'].append(dict(Id='shaft2',Name='Second shaft',MvpRole='front_propshaft',Template='bulk',
            BodyIds=['shaft2'],GeometryDirectory=str(self.root/'shaft2')))
        result=inventory(project);role=next(r for r in result['roles'] if r['id']=='front_propshaft')
        self.assertEqual(role['status'],'tagged');self.assertEqual(result['errors'],[])
        self.assertEqual(result['shaft_chain_review'][0]['sections'],['engine','shaft2'])
        self.assertEqual(result['shaft_chain_review'][0]['status'],'needs_reviewed_chain')
        self.assertTrue(any(r['id']=='shaft_carrier' and not r['required'] for r in result['roles']))
    def test_every_catalog_option_only_requests_defined_groups_and_links(self):
        import itertools
        from mvp_inventory import configuration
        catalog=json.loads((module.HERE/'template_catalog.json').read_text());known={r['id'] for r in catalog['mvp_roles']}
        for choices in itertools.product(*(g['options'] for g in catalog['mvp_template_sets'])):
            project={'MvpTemplates':[dict(Category=g['id'],Template=o['id']) for g,o in zip(catalog['mvp_template_sets'],choices)]}
            _,roles,links=configuration(catalog,project)
            self.assertTrue(roles<=known)
            self.assertTrue(all(a['from_role'] in roles and a['to_role'] in roles for a in links))


if __name__=='__main__':unittest.main()
