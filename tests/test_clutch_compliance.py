from pathlib import Path
import sys
import unittest
import math
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'beamng.cad/FramePipeline'))
from clutch_compliance import current_budget,energy,passive_angle


class ClutchComplianceTests(unittest.TestCase):
    def budget(self):
        effective=1.672256595569664e-5;omega=2*math.pi*120
        return dict(effective_inertia_kg_m2=effective,maximum_gearing=24,
            frequency_limit_hz=120,damping_nm_s_rad=2*.3*effective*omega,step_seconds=.0005)

    def test_current_ratio_retains_same_discrete_stability_margin(self):
        values=[]
        for gearing in (6.4,8,12,24):
            b=current_budget(self.budget(),.15,gearing);values.append(b['spring'])
            # Independent semi-implicit oscillator with worst native tangent.
            dt=.0005;k=2*b['spring']/b['effective_inertia'];d=b['damp']/b['effective_inertia']
            matrix=np.array([[1-dt*dt*k,dt*(1-dt*d)],[-dt*k,1-dt*d]])
            self.assertLess(max(abs(np.linalg.eigvals(matrix))),1)
            self.assertAlmostEqual(b['step_eigenvalue'],.5945116454926169)
        self.assertGreater(values[0],values[-1]*10)

    def test_stiffness_changes_never_inject_stored_energy(self):
        for angle in (-50,-1.2,-.7,0,.125,.8,2,50):
            for old,new in ((.7,30),(30,.7),(4.7,4.7)):
                adjusted=passive_angle(angle,old,new)
                self.assertLessEqual(energy(adjusted,new),energy(angle,old)+1e-10)
                if new>old:self.assertAlmostEqual(energy(adjusted,new),energy(angle,old),places=9)

    def test_out_of_range_ratio_rejected(self):
        for gearing in (0,-1,25,float('nan')):
            with self.assertRaises(ValueError):current_budget(self.budget(),.15,gearing)


if __name__=='__main__':unittest.main()
