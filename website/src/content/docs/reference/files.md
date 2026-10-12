---
title: "Project files and build receipts"
description: "Project files and build receipts — beamng.cad documentation."
sidebar:
  order: 2
---

Save CAD, editable project companions and referenced exported/build assets together when archiving work. The JSON companion alone is not a complete project backup.

| Artifact | Purpose |
| --- | --- |
| `<assembly>.truemesh-prep.json` | Configuration-specific frame selections and hull settings |
| `<assembly>.beamng-project.json` | Vehicle ownership, references, templates, mounts and parameters |
| `<project>.inventory.json` | Last refreshed role/ownership/material inventory |
| `geometry.json` | Exported body identity, transforms, geometry, mass/appearance observations |
| `material-snapshot.json` | Captured mechanical properties and material provenance |
| `snapshot.json`, `review.json` | Generation source identity and approved fixtures |
| `manifest.json` | Generated exported-vehicle contract used by verification |
| `static_frame_build.json` | Standalone frame build receipt |
| `pilot-verification.json` | First vehicle pilot result |
| `study/quick-verification.json` | Separate quick frame screening history |
| `main.materials.json` | BeamNG render material definitions |
| Project ZIP and installation receipt | Packaged content and installed-copy evidence |

The exact location of a receipt depends on its workflow. Use the **Log**, **Open Build Folder**, and build manager rather than guessing the latest folder by name.

## Identity and hashes

Package identity is stable within a project. Display-name/image revisions retain the physical content and parent receipt. Importing/forking physics creates a new namespace.

Geometry, material, frame, generator and runtime hashes govern reuse. A filename remaining on disk does not prove it matches the current CAD. Modified sealed inputs block reuse or require a fresh generation.

## Distinguish formats

Workers validate the exported vehicle manifest and its version before consuming geometry or measurements.

## Retention

Passing tests can compact raw telemetry while retaining measurements, provenance and necessary images. Failed/cancelled runs retain diagnostics. A compact receipt does not imply raw samples are still available.

Detailed development evidence stays in the checkout's local archive. Only selected illustrations and summaries are published on this site.
