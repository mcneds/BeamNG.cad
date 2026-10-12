# CAD-based 4130 calibration — 4 October 2026

This historical calibration derives mass and targets from CAD tube bodies and fits the existing JBeam graph. Both 4130 cases passed the numerical criteria for the tested fixtures. **Neither recorded candidate qualified: rendered cut tests showed stretched mesh between disconnected frame sections.** See the maintained website for current generation behavior.

## What changed

The CAD audit resolves all 105 bodies, including tiny export seams, dangling facets and opposite-winding duplicate triangles. Recorded repairs change the aggregate signed volume by 0.001958%; they do not modify the source DAE. Summed CAD steel mass is **34.789158 kg**, versus the previous hull-derived **164.617722 kg**. Overlapping CAD bodies and omitted weld metal remain uncertainties.

Positive node weights reproduce CAD mass, center of mass and inertia to numerical precision. All **78 node coordinates and 435 beam connections** remain unchanged. Springs are fitted to an independent Timoshenko frame reference, first by beam families and then by individual weights. Yield capacities fit the two load-pattern onsets. The highest linear mode is 349.997 Hz under the chosen 350 Hz limit; damping ratio is 0.04. Exported candidates contain no fixed fixture nodes.

The reference follows measured hollow sections and bent centerlines, assumes fully joined members, and includes load/support offset moments. Analytical axial, bending and torsion checks pass the 2% tolerance. Its inferred joints and member approximations have not been verified against a physical frame.

Material condition is unknown. Density is 7,850 kg/m³, Young's modulus 205 GPa and Poisson ratio 0.29. Representative annealed and normalized cases use yield/UTS pairs of 360.6/560.5 MPa and 436.4/668.8 MPa from the [Admiral Steel typical-property table](https://www.admiralsteel.com/assets/pdf/catalog.pdf). These are assumptions, not guaranteed bounds for this frame.

## Measured response

The final evidence set contains **39 completed independent recordings**: three instrument checks, 17 tests per material case, and two controlled cuts. There are 49 archived records including ten superseded idle/cut recordings described below. All active recordings pass measurement-integrity checks; no active recording reports a flexbody load error. The Python suite passes 47 tests.

Values below are three-run means. “Torsion deflection” is displacement projected onto the signed load pattern, not a rotation; the 100 N pattern produces a 26.1641 N·m couple. Reported yield loads are total external actuator load, not force in an individual beam.

| Case / fixture | Deflection at 100 N | Elastic error against CAD reference | Reference first yield | Measured first yield | Yield error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Annealed / flex | 0.265750 mm | −0.0212% | 2,995.61 N | 3,014.78 N | +0.640% |
| Annealed / torsion | 0.120249 mm | −0.0483% | 4,599.91 N | 4,586.69 N | −0.287% |
| Normalized / flex | 0.265753 mm | −0.0201% | 3,625.30 N | 3,652.52 N | +0.751% |
| Normalized / torsion | 0.120256 mm | −0.0421% | 5,566.84 N | 5,546.79 N | −0.360% |

These are calibration matches for the same two load patterns used in fitting. They establish that the generated values behave as intended in Drive, not independent validation of every load direction or the real frame.

Both 12-second and 24-second progressive ramps were tested, with three independent slow-ramp recordings per fixture and condition. The largest yield/break threshold change between rates was 0.0169%; the largest three-run threshold range was 0.0061%. Idle tests showed no breaks or permanent beam deformation, approximately 0.957 mm RMS shape change and 0.002 m/s tail speed.

The instrument checks measured 9.99899 mm against 10 mm expected, yielding at 8.01250 N against 8 N, and breaking at 12.00200 N against 12 N.

## What the break tests do and do not establish

First numerical beam breaks occurred at approximately 4.191/5.441 kN for annealed flex/torsion and 5.023/6.520 kN for normalized flex/torsion. Those edges are internal supports (`sh0058–sp01r` and `sh0008–sp01l`). **None of the natural progressive tests separated the graph. These loads are not demonstrated tube-rupture loads.**

`beamStrength` scales the fitted yield capacities by UTS/yield ratio. This provides an elastic capacity proxy; it does not model ductile strain to fracture, buckling, weld failure or fatigue. The [force–deflection plot](comparisons/4130-complete-20261004/force-deflection.png) distinguishes first yield from first numerical beam break. Global post-yield behavior is still unvalidated.

Mesh association now selects local surface-based locator neighborhoods with transverse support and connects them through existing shell edges. This fixes the previous missing-mesh errors. Mesh breaking is enabled on the 201 existing shell edges shared by CAD locator groups and disabled on the remaining numerical supports. This follows the distinction in [BeamNG's beam documentation](https://documentation.beamng.com/modding/vehicle/sections/beams/) between mesh-support beams and structural-only supports.

Controlled cuts at 35% and 65% of frame length sever all crossing edges, produce two graph components, and pull them apart under a small 1 N load. Both still leave stretched strips across the gap. See the [35% final view](runs/20261004T125555-mesh-cut-597f9b/attempt-0/final-front.png), [65% final view](runs/20261004T125634-mesh-cut-3fb88f/attempt-0/final-oblique.png), and [recorded image review](comparisons/4130-complete-20261004/mesh-review.json). Both material cases use identical mesh groups and breaking flags, so this association defect applies to both. The evidence does not prove that every possible binding on the unchanged graph must fail. Mesh segmentation or tighter locator grouping remains future work, followed by the same automated cut tests.

## Evidence and reproducibility

- [Study report](comparisons/4130-complete-20261004/index.html), [measured summary](comparisons/4130-complete-20261004/measured-summary.json), and [CSV table](comparisons/4130-complete-20261004/measurements.csv).
- [CAD audit](comparisons/4130-complete-20261004/geometry-audit.json), [reference geometry](comparisons/4130-complete-20261004/reference-geometry.png), and [source/export verification](comparisons/4130-complete-20261004/export-verification.json).
- [Annealed diagnostic mod](comparisons/4130-complete-20261004/4130-annealed/diagnostic-mod.zip) and [normalized diagnostic mod](comparisons/4130-complete-20261004/4130-normalized/diagnostic-mod.zip). Neither is a qualified replacement.

Six idle recordings were rerun after correcting spawn height for the JBeam reference-node datum. Two cuts were rerun after lifting the free fixture clear of the floor and correcting the separating-load direction; those cuts were rerun again after changing mesh-breaking permissions. All superseded recordings are retained. The study records these revisions and verifies unchanged graph, mass, stiffness, damping and yield/strength values for retained loaded tests. None of their broken edges had changed mesh-breaking flags. Report-only changes after testing do not change recorded measurements.

The image review is tied to exact PNG hashes. The failed review prevents a `qualified-mod.zip` from being produced. Automated launching, Continue handling, telemetry, screenshots and reports required no manual regeneration or screenshot exchange. Drive 0.39.4.0 was used without BeamNGpy.

Run a fresh study using the [README commands](README.md#cad-based-4130-calibration). This development study includes explicitly recorded revisions; use a new output directory for new code. `--resume` deliberately refuses changed source, configuration or implementation. Reports, telemetry and diagnostic exports are local Git-ignored artifacts; this document preserves the result in the repository.

## Installed in-game review vehicles

The normal BeamNG.drive profile now contains two separate review vehicles. Open the vehicle selector and search **4130**:

- **Mochi 4130 Annealed (Review)** — configuration **4130 Annealed - Calibrated Frame (Review)**.
- **Mochi 4130 Normalized (Review)** — configuration **4130 Normalized - Calibrated Frame (Review)**.

The ZIPs are installed in `%LOCALAPPDATA%\BeamNG\BeamNG.drive\current\mods`. Vehicle, part, mesh and material IDs are namespaced so both can coexist with older Mochi versions. Only names, descriptions and preview images change; calibration properties remain identical to the archived candidates. These remain diagnostic frames with the mesh-separation limitation above.

Both packages were loaded together in the isolated Drive profile. The vehicle-selector names, configurations and PNG previews resolved correctly; each spawned with 78 nodes, 435 beams, zero fixed nodes, 34.789158 kg mass and all 105 flexbodies loaded. See the [installation manifest](comparisons/4130-complete-20261004/review-mods/installation.json) and [live package validation](comparisons/4130-complete-20261004/review-mods/validation.json).
