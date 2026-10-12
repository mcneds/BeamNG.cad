# Local validation — 4 October 2026

Validated on Windows with BeamNG.drive 0.39.4.0, Python 3.14.7, NumPy 2.5.3 and Matplotlib 3.11.2. Thirteen offline tests passed, including launch failure, timeout, retry, input protection, fixture validation, rigid-motion removal and comparison safeguards. `doctor` passed. All twelve source files matched their archived hashes after testing.

The final nine live runs completed unattended, including startup through the Continue/mod-initialization gate, map loading, spawning, recording, report creation and shutdown. These are the runs used as evidence; exploratory runs with measurement defects were excluded.

| Test | Repeats | Result |
| --- | --- | --- |
| Known spring fixture | 1 | Approximately 10 mm deflection under 10 N, within 1% of the analytical check; supports stationary |
| Mochi idle | 3 | Completed 15 seconds, no broken beams; final shape RMS about 1.325 mm after removing rigid motion |
| Mochi flex baseline | 3 | 0.569494 mm mean deflection under 100 N; no broken beams; mass 164.6177 kg |
| Spring stiffness ×1.2 | 1 | 0.474629 mm deflection, about 16.7% lower than baseline |
| Damping ×2 | 1 | 0.569541 mm deflection; release probe-speed RMS about 22.9% lower; load-point settling 5.00 s versus baseline mean 8.31 s |

Stiffness changed deflection well beyond baseline variation. Damping changed release oscillation and settling without a meaningful static-deflection change. The stiffness candidate's small settling-time change did not exceed the baseline variation. Candidate runs are single sensitivity checks, not estimates of candidate uncertainty or a final tuning recommendation.

Fixed supports in the final flex runs showed at most about 1.1 micrometres of readback movement, below the 5 micrometre validation limit. Mean hold positions agreed with integrated velocities. All loaded holds settled. No beam rest-length change was recorded in the flex checks.

## Local evidence

Open [the combined comparison](comparisons/validation-20261004/index.html) for response overlays, repeat variation and links to each replay. [validation.json](comparisons/validation-20261004/validation.json) records the environment and spring check. These generated artifacts are local and Git-ignored.

- Idle baseline: `20261004T093206-idle-f81ad8`, `20261004T093250-idle-91f2fe`, `20261004T093335-idle-d29c84`.
- Flex baseline: `20261004T093852-flex-27e72f`, `20261004T093939-flex-dde2ae`, `20261004T094025-flex-ff18a6`.
- Stiffer: `20261004T094123-flex-2b32eb`.
- More damping: `20261004T094209-flex-a702d5`.
- Spring instrument check: `20261004T094340-spring-220bc4`.

## Measurement limits

Drive's position readback is cached between graphics updates. A body-relative coordinate API was unsuitable for world displacement, and mixing independently refreshed vehicle-origin and node positions created transient common translation. The final recorder uses the world-coordinate API relative to a fixed support for fixtures; idle analysis removes rigid motion. Invalid exploratory runs retain their logs and are marked `invalid_measurement`.

The final recorder keeps raw sampled positions and independent physics-rate velocities, reports the cadence limitation, checks position against integrated velocity, and rejects apparent fixed-support motion above the threshold. Replay interpolation and display exaggeration are not additional physics samples. Results demonstrate a repeatable feedback loop, not agreement with real material properties, strength or crash behaviour.
