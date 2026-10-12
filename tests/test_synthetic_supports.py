import copy
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    points = list(itertools.product([-.3, .3], [0, 2.], [.2, .7]))
    tubes = []
    for i, a in enumerate(points):
        for b in points[:i]:
            if sum(x != y for x, y in zip(a, b)) == 1:
                tubes.append(dict(kind='tube', a=a, b=b, radius=.02,
                                  wall=.002, analytic_volume_m3=.001))
    corners = {}
    for side, sign in [('L', 1), ('R', -1)]:
        corners['R'+side] = dict(shock_top=[sign*.5, .8, .9],
                                hinge_inner=[sign*.52, .8, .35],
                                hinge_outer=[sign*.72, .8, .35])
    return dict(components=[dict(id='frame', primitives=tubes)], hardpoints=corners)


def build(recipe):
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory)/'recipe.json'
        target = Path(directory)/'supported.json'
        source.write_text(json.dumps(recipe))
        subprocess.run([sys.executable, str(ROOT/'tools/make-synthetic-frame-supports.py'),
                        str(source), str(target)], check=True, capture_output=True)
        return json.loads(target.read_text())


def tubes(recipe, reflection=1):
    return sorted(tuple(sorted(tuple(np.round(np.array(shape[end])*[reflection, 1, 1], 9))
                               for end in ('a', 'b')))
                  for shape in recipe['components'][0]['primitives'])


class SyntheticSupportTests(unittest.TestCase):
    def test_symmetric_frame_gets_mirrored_supports(self):
        result = build(fixture())
        self.assertGreater(len(result['mount_supports']), 0)
        self.assertEqual(tubes(result), tubes(result, -1))

    def test_source_order_and_endpoint_direction_do_not_choose_other_braces(self):
        recipe = fixture()
        other = copy.deepcopy(recipe)
        other['components'][0]['primitives'].reverse()
        for shape in other['components'][0]['primitives']:
            shape['a'], shape['b'] = shape['b'], shape['a']
        self.assertEqual(tubes(build(recipe)), tubes(build(other)))

    def test_asymmetric_source_is_preserved_and_roots_stay_on_actual_tubes(self):
        recipe = fixture()
        recipe['components'][0]['primitives'].append(dict(kind='tube', a=[-.3, 0, .2],
            b=[-.3, 2, .7], radius=.02, wall=.002, analytic_volume_m3=.001))
        result = build(recipe)
        for support in result['mount_supports']:
            for root in support['roots']:
                distances = []
                for shape in recipe['components'][0]['primitives']:
                    a, b = np.array(shape['a']), np.array(shape['b'])
                    t = np.clip(np.dot(root-a, b-a)/np.dot(b-a, b-a), 0, 1)
                    distances.append(np.linalg.norm(root-(a+t*(b-a))))
                self.assertLess(min(distances), 1e-8)
        self.assertNotEqual(tubes(result), tubes(result, -1))
