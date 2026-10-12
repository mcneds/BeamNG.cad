/** Teaching models only. These do not invoke or reproduce the production solver. */


/** The handbook's automatic static setup equations, with explicit illustrative inputs. */
export function springSetup(mass: number, frequency: number, ratio: number, dampingRatio = 0.3) {
  if (![mass, frequency, ratio].every(v => Number.isFinite(v) && v > 0) || !Number.isFinite(dampingRatio) || dampingRatio < 0) throw new RangeError('Invalid spring model inputs.');
  const omega = 2 * Math.PI * frequency;
  return {
    stiffness: mass * omega * omega / (ratio * ratio),
    damping: 2 * dampingRatio * mass * omega / (ratio * ratio),
    preload: mass * 9.81 / ratio,
  };
}
