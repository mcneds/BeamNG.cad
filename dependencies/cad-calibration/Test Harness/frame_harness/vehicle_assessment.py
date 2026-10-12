"""Separate implementation/motion evidence from handling and physical calibration.

These dimensions supplement the historical acceptance result; they never rewrite
it or qualify a build. Unknown checks remain in the implementation screen.
"""
HANDLING_CHECKS=frozenset({
    'straight_lateral_drift','straight_heading','turn_heading_requested','turn_heading_consistent',
    'low_drift','settled','stays_upright','20kmh_within_20s','stop_within_10m',
    'reverse_5m','turns_requested_direction',
})


def assess(result,motion_keys=(),*,validated=False,expected_motion=False):
    checks=result.get('checks',{})
    def dimension(names,scope):
        values={k:checks[k] for k in sorted(names) if k in checks}
        failed=[k for k,v in values.items() if not bool(v)]
        return dict(status='not_assessed' if not validated or not values else 'screen_failed' if failed else 'screen_passed',
            checks=values,failed_checks=failed,scope=scope)
    motion=set(motion_keys)-HANDLING_CHECKS
    groups=dict(
        implementation=dimension(set(checks)-motion-HANDLING_CHECKS,
            'Recorded build/fixture/control contracts and observed damage. A pass is not a proof of physical dynamics.'),
        kinematics=dimension(motion,
            'Rigid CAD mechanism at measured travel and actuator target. This does not independently predict travel over time.'),
        handling=dimension(set(checks)&HANDLING_CHECKS,
            'Observed driving and settling against historical performance gates. Do not alter authored geometry merely to pass these gates.'),
        physical_dynamics=dict(status='not_assessed',checks={},failed_checks=[],
            scope='Requires independent mass/inertia, spring/damper force laws and force/time-response evidence. Kinematic or handling success alone is insufficient.'))
    if validated and expected_motion and not motion:
        groups['kinematics'].update(status='screen_failed',failed_checks=['motion_evidence_missing'])
    return dict(version=1,recording_validated=validated,dimensions=groups,physical_qualification='not_established',
        acceptance_unchanged=True)
