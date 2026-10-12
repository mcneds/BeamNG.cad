"""Published UI references must preserve the tested geometry and point semantics."""
import importlib.util
import json
import math
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('publish_reference',ROOT/'tools/publish-reference-skeleton.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)


class ReferenceSkeletonTests(unittest.TestCase):
    def test_sides_are_named_while_facing_forward(self):
        for name in ('primary','alternate'):
            data=json.loads((ROOT/f'beamng.cad/FramePipeline/reference/{name}.json').read_text())
            for role,part in data['roles'].items():
                if not role.startswith(('fl_','fr_','rl_','rr_')) or not part['vertices']:continue
                mean_x=sum(p[0] for p in part['vertices'])/len(part['vertices'])
                self.assertGreater(mean_x*(1 if role[1]=='l' else -1),0,role)
    def test_packaged_assets_have_valid_meshes_and_catalog_requests(self):
        for name in ('primary','alternate'):
            data=json.loads((ROOT/f'beamng.cad/FramePipeline/reference/{name}.json').read_text())
            self.assertEqual(64,len(data['provenance']['manifest_sha256']))
            self.assertTrue(data['provenance']['files'])
            for role,part in data['roles'].items():
                self.assertEqual(publisher.CATALOG[role]['hardpoints'],[m['id'] for m in part['markers']])
                for edge in part['edges']:
                    self.assertTrue(all(0<=i<len(part['vertices']) for i in edge))
                for point in part['vertices']+[p for m in part['markers'] for p in m['positions']]:
                    self.assertEqual(3,len(point));self.assertTrue(all(math.isfinite(v) for v in point))
                for marker in part['markers']:
                    self.assertTrue(marker['source'] if marker['positions'] else marker['note'])

    def test_axis_is_two_declared_points_not_a_direction_vector(self):
        definition=dict(hardpoints={'FL':dict(hub=[.75,0,.29],hub_axis=[.85,0,.29])},fixed_mounts={},halfshafts={},shafts={})
        axis=next(m for m in publisher.markers('fl_wheel',definition) if m['id']=='wheel_axis')
        self.assertEqual([[.75,0,.29],[.85,0,.29]],axis['positions'])

    def test_coplanar_diagonals_are_not_physical_members(self):
        # Checked-in panel meshes are two triangles, but show the four boundary edges.
        data=json.loads((ROOT/'beamng.cad/FramePipeline/reference/primary.json').read_text())
        self.assertEqual(8,len(data['roles']['panel']['edges']))  # floor and nose

    def test_layouts_keep_distinct_rear_parts_and_missing_axes_explicit(self):
        primary=json.loads((ROOT/'beamng.cad/FramePipeline/reference/primary.json').read_text())
        alternate=json.loads((ROOT/'beamng.cad/FramePipeline/reference/alternate.json').read_text())
        self.assertIn('rl_trailing_arm',primary['roles']);self.assertNotIn('rl_upper_wishbone',primary['roles'])
        self.assertIn('rl_upper_wishbone',alternate['roles']);self.assertNotIn('rl_trailing_arm',alternate['roles'])
        markers={m['id']:m for m in primary['roles']['rl_trailing_arm']['markers']}
        self.assertEqual([[.4,1.33,.29]],markers['pivot_axis_a']['positions'])
        self.assertEqual(markers['spring_mount']['positions'],markers['damper_mount']['positions'])
        output=next(m for m in primary['roles']['engine']['markers'] if m['id']=='output_axis')
        self.assertEqual([],output['positions']);self.assertIn('Not explicitly located',output['note'])


if __name__=='__main__':unittest.main()
