import copy,sys,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'beamng.cad/FramePipeline'))
from vehicle_templates import TemplateModel,Mechanism
from synthetic_vehicle import recipe
from vehicle_alignment import solve


class AlignmentTests(unittest.TestCase):
    def test_optional_alignment_changes_lengths_without_moving_geometry(self):
        model=TemplateModel(recipe('ball_radius_toe'));before=copy.deepcopy(model.definition)
        self.assertEqual(solve(model),{})
        model.data['parameters'].update(front_alignment_toe_in_deg=.3,rear_alignment_toe_in_deg=.4)
        result=solve(model)
        self.assertEqual(model.definition,before)
        for corner,row in result.items():
            linkage=Mechanism(model,corner)
            _,pose=linkage.solve(row['reference_hub_height_m']-linkage.p['hub'][2],row['reference_length_m']-row['original_length_m'])
            axis=pose['hub_axis']-pose['hub'];axis*=1 if axis[0]>=0 else -1
            toe=np.degrees(np.arctan2(axis[1],axis[0]))*(-1 if corner[1]=='L' else 1)
            self.assertAlmostEqual(toe,row['target_toe_in_deg'],places=6)
            self.assertLessEqual(abs(row['length_scale']-1),.02)

    def test_conflicting_or_nonfinite_settings_rejected(self):
        model=TemplateModel(recipe('ball_radius_toe'))
        model.data['parameters'].update(rear_alignment_toe_in_deg=.2,rear_toe_link_length_scale=1.01)
        with self.assertRaisesRegex(ValueError,'not both'):solve(model)
        model.data['parameters'].update(rear_alignment_toe_in_deg=float('nan'),rear_toe_link_length_scale=1.)
        with self.assertRaisesRegex(ValueError,'finite'):solve(model)


if __name__=='__main__':unittest.main()

