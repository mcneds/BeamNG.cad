---
title: "Glossary"
description: "Glossary — beamng.cad documentation."
sidebar:
  order: 5
---

| Term | Meaning here |
| --- | --- |
| Body | One native solid or surface body within a CAD part instance |
| Component / owner | The project group responsible for geometry and physical mass |
| Persistent reference | Native identity used to resolve saved CAD selections after reopening |
| Companion assembly | Separate working assembly for reference/mate authoring |
| Hardpoint | Explicit location required by a mechanism or mounting definition |
| Node | Point with position and mass in the JBeam graph |
| Beam | Constraint acting between nodes; type determines its force law |
| Torsion bar | Four-node angular constraint; not necessarily a visible physical bar |
| Hull | Generated envelope/graph used by a representation |
| Fixture | Reviewed support/load sites for calibration or a test |
| COM | Centre of mass |
| Inertia tensor | Resistance to angular acceleration about specified axes |
| Prop | Rigid rendered mesh bound to a native node basis |
| Flexbody | Rendered mesh mapped to a set of physical nodes |
| Pressure wheel | Native BeamNG wheel/tire structure with generated nodes and pressure |
| Preload | Spring force already present at the selected reference pose |
| Motion ratio | Relationship between wheel travel and shock travel |
| Numerical conditioning | Adjustment within the discrete model's mass/stiffness/damping limits |
| Provenance | Recorded identities and hashes tying output to its inputs |
| Receipt | Saved result and provenance for a build, revision, verification or installation |
| Pilot | Limited initial screen, not the full acceptance suite |
| Qualification | Accepted result for an explicitly stated scope and exact artifact |
| Visual only | Appearance following a physical parent; may transfer mass or explicitly exclude it |
| FL / FR / RL / RR | Front left / front right / rear left / rear right from the seated driver's perspective |

Vehicle axes are **+X left, −Y forward, +Z up**, in metres. The CAD transform is applied once, preserving the assembly origin.
