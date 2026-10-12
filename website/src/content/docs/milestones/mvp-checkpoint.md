---
title: "9 October: MVP checkpoint"
description: "9 October: MVP checkpoint — beamng.cad documentation."
sidebar:
  order: 2
---

**Historical result — both native-mate vehicle fixtures remained unqualified.**

Fresh production builds of the trailing-arm/geared-AWD and rear-wishbone/RWD synthetic fixtures passed settling, supported drivetrain and articulation. Both failed acceleration on straight-line drift.

| Synthetic fixture | CAD mass | Lateral drift | Limit |
| --- | ---: | ---: | ---: |
| Trailing arm / geared AWD | 332.778023 kg | 2.821 m | 0.5 m |
| Rear wishbone / RWD | 299.017497 kg | 1.690 m | 0.5 m |

There was zero commanded steering and no broken beam in either acceleration recording. Each acceptance sequence stopped after four of 24 planned recordings.

## What this established

The build and initial motion paths worked for those fixtures. The stronger driving check still failed. Neither a clean-looking vehicle nor zero broken beams was sufficient for acceptance.

Attachment tests also stopped near a travel guard during force-driven release. The [following investigation](/milestones/release-test/) separated that recorder limitation from actual internal instability.

Local source: `docs/mvp-checkpoint-20261009.md`, with detailed identities and hashes in `docs/evidence/mvp-checkpoint-20261009.json`. These are retained in the checkout rather than published in full.

