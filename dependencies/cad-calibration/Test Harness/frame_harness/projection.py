"""Experimental elastic projections; mass, geometry and strength are invariants."""
from __future__ import annotations

import math
import numpy as np

MODES = ("modal_global", "local_capped")


def axial_columns(positions, endpoints):
    positions = np.asarray(positions, dtype=float)
    endpoints = np.asarray(endpoints, dtype=int)
    delta = positions[endpoints[:, 1]]-positions[endpoints[:, 0]]
    lengths = np.linalg.norm(delta, axis=1)
    if np.any(lengths <= 1e-10) or not np.all(np.isfinite(lengths)):
        raise ValueError("Invalid beam length")
    directions = delta/lengths[:, None]
    columns = np.zeros((3*len(positions), len(endpoints)))
    for edge, (a, b) in enumerate(endpoints):
        columns[3*a:3*a+3, edge] = directions[edge]
        columns[3*b:3*b+3, edge] = -directions[edge]
    return columns, lengths, directions


def modal_frequencies(columns, masses, springs):
    masses = np.asarray(masses, dtype=float)
    springs = np.asarray(springs, dtype=float)
    if np.any(masses <= 0) or np.any(springs < 0) or not np.all(np.isfinite(masses)) or not np.all(np.isfinite(springs)):
        raise ValueError("Masses must be positive and springs nonnegative and finite")
    weighted = columns / np.repeat(np.sqrt(masses), 3)[:, None]
    eigenvalues = np.linalg.eigvalsh((weighted*springs) @ weighted.T)
    return np.sqrt(np.maximum(eigenvalues, 0))/(2*np.pi)


def project_springs(columns, endpoints, masses, raw_springs, frequency_hz, mode):
    if mode not in MODES or not math.isfinite(frequency_hz) or frequency_hz <= 0:
        raise ValueError("Invalid projection mode or frequency limit")
    raw = np.asarray(raw_springs, dtype=float)
    masses = np.asarray(masses, dtype=float)
    endpoints = np.asarray(endpoints, dtype=int)
    modal_frequencies(columns, masses, raw)  # validate before local arithmetic
    incident = np.bincount(endpoints.ravel(), weights=np.repeat(raw, 2), minlength=len(masses))
    fraction = np.ones(len(masses))
    np.divide(masses*(2*np.pi*frequency_hz)**2, incident, out=fraction, where=incident > 0)
    fraction = np.minimum(fraction, 1)
    springs = raw.copy()
    if mode == "local_capped":
        springs *= np.minimum(fraction[endpoints[:, 0]], fraction[endpoints[:, 1]])
    highest = modal_frequencies(columns, masses, springs)[-1]
    if highest > frequency_hz:
        springs *= (frequency_hz/highest)**2
    return springs


def reduced_mass_damping(springs, masses, endpoints, ratio):
    if not math.isfinite(ratio) or ratio < 0:
        raise ValueError("Damping ratio must be finite and nonnegative")
    m = np.asarray(masses)[np.asarray(endpoints)]
    reduced = m[:, 0]*m[:, 1]/m.sum(axis=1)
    return 2*ratio*np.sqrt(np.asarray(springs)*reduced)


def elastic_tensor(springs, lengths, directions, volume):
    x, y, z = directions.T
    q = np.array([x*x, y*y, z*z, x*y, x*z, y*z]).T
    return (q.T*(springs*lengths**2/volume)) @ q

