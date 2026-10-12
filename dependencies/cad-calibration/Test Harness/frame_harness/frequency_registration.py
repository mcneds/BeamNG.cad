"""Reconstruct full chassis rigid registration from bounded sufficient statistics."""
import numpy as np


def fits(original, weights, statistics):
    original = np.asarray(original, float)
    weights = np.asarray(weights, float)
    statistics = np.asarray(statistics, float)
    if (original.ndim != 2 or original.shape[1] != 3 or weights.shape != (len(original),)
            or statistics.ndim != 2 or statistics.shape[1] != 12
            or not all(np.isfinite(x).all() for x in (original, weights, statistics))
            or np.any(weights <= 0)):
        raise ValueError('Invalid full chassis registration statistics')
    weights = weights/weights.sum()
    center = weights @ original
    if np.linalg.matrix_rank(original-center, tol=1e-8) < 2:
        raise ValueError('Collinear chassis reference')
    covariance = statistics[:, 3:].reshape(-1, 3, 3)
    u, s, vt = np.linalg.svd(covariance)
    if np.any(s[:, 1] < 1e-12):
        raise ValueError('Collapsed chassis registration')
    correction = np.broadcast_to(np.eye(3), covariance.shape).copy()
    correction[:, 2, 2] = np.linalg.det(u @ vt)
    rotation = u @ correction @ vt
    translation = statistics[:, :3] - center @ rotation
    return rotation, translation
