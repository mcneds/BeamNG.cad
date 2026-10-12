"""Independent rigid-link motion check for the staged rear donor transfer.

Dimensions are the inspected donor's CAD joint centers, in metres, Y up.
No files or geometry in the donor or working companion are modified.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

PIVOT = np.array([.40005, .0762, -1.1259310840706043])
UPPER_IN = np.array([.1397, .18415, -1.923034])
LOWER_IN = np.array([.1397, .034925, -1.897634])
UPPER_OUT = np.array([.6330608081302492, .0179864728386218, -1.9123904459715015])
LOWER_OUT = np.array([.633256365570785, -.1309977043094391, -1.8971239027543032])
KNUCKLE_UPPER = np.array([.6338570071264096, .0167691498488134, -1.8468833499936097])
KNUCKLE_LOWER = np.array([.6341763415639443, -.1349368961339421, -1.8443156444257205])
TOE_IN = np.array([.1143, .0889, -1.992884])
TOE_OUT = np.array([.656860598380231, -.07289911410654085, -1.91502968888222])
WHEEL = np.array([.72152950212328, -.0596658856864762, -1.8467263824477451])
WHEEL_AXIS = np.array([-.9999032930330191, -.00187150947661895, .0137804946937103])
SHOCK_TOP = np.array([.458465030767677, .5898661073201716, -1.3946224725495762])
SHOCK_BOTTOM = np.array([.5404228600216749, .02105401123884443, -1.5638594228337799])
HINGE = (KNUCKLE_UPPER - KNUCKLE_LOWER)
HINGE /= np.linalg.norm(HINGE)


def pose(q):
    arm = Rotation.from_rotvec(q[:3])
    hinge = Rotation.from_rotvec(HINGE * q[3])
    move_arm = lambda p: PIVOT + arm.apply(p - PIVOT)
    move_knuckle = lambda p: move_arm(KNUCKLE_UPPER + hinge.apply(p - KNUCKLE_UPPER))
    return move_arm, move_knuckle, arm * hinge


def solve(dy):
    def residual(q):
        arm, knuckle, _ = pose(q)
        return np.array([
            np.linalg.norm(arm(UPPER_OUT) - UPPER_IN) - np.linalg.norm(UPPER_OUT - UPPER_IN),
            np.linalg.norm(arm(LOWER_OUT) - LOWER_IN) - np.linalg.norm(LOWER_OUT - LOWER_IN),
            np.linalg.norm(knuckle(TOE_OUT) - TOE_IN) - np.linalg.norm(TOE_OUT - TOE_IN),
            knuckle(TOE_OUT)[1] - TOE_OUT[1] - dy,
        ])

    fit = least_squares(residual, np.zeros(4), xtol=1e-13, ftol=1e-13, gtol=1e-13)
    error = float(np.max(np.abs(residual(fit.x))))
    if not fit.success or error > 1e-9:
        raise RuntimeError(f"Rigid-link continuation failed at {dy}: {error}")
    arm, knuckle, rotation = pose(fit.x)
    return dict(requested_m=dy, wheel_center=knuckle(WHEEL).tolist(),
                wheel_axis=rotation.apply(WHEEL_AXIS).tolist(),
                shock_length_m=float(np.linalg.norm(SHOCK_TOP - arm(SHOCK_BOTTOM))),
                residual_m=error, coordinates=fit.x.tolist())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    expected = [solve(dy) for dy in [.01, -.01, .03, -.03]]
    (args.folder / "rear-ideal-motion.json").write_text(json.dumps(expected, indent=2))
    actual_path = args.folder / "rear-motion-tests.json"
    if not actual_path.exists():
        print("PASS independent rigid-link solutions at +/-10 and +/-30 mm")
        return
    comparisons = []
    for row in json.loads(actual_path.read_text()):
        if row["test"] != "vertical_travel":
            continue
        reference = next(r for r in expected if r["requested_m"] == row["requested_m"])
        sign = np.array([-1, 1, 1]) if row["side"] == "rr" else np.ones(3)
        center_error = float(np.linalg.norm(np.array(reference["wheel_center"]) * sign - row["wheel_center"]))
        axis_error = float(np.linalg.norm(np.array(reference["wheel_axis"]) * sign - row["wheel_axis"]))
        comparisons.append(dict(side=row["side"], requested_m=row["requested_m"],
                                center_error_m=center_error, axis_error=axis_error,
                                passed=row["passed"] and center_error < 1e-5 and axis_error < 1e-5))
    (args.folder / "rear-motion-comparison.json").write_text(json.dumps(comparisons, indent=2))
    if len(comparisons) != 8 or not all(r["passed"] for r in comparisons):
        raise RuntimeError("Native rear motion does not match all eight independent rigid-link solutions")
    print("PASS both native rear corners match independent rigid-link solutions")


if __name__ == "__main__":
    main()
