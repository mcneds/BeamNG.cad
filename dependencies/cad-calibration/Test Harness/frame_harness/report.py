from __future__ import annotations

import html
import json
from contextlib import contextmanager
from contextvars import ContextVar
from collections import defaultdict
from pathlib import Path

import numpy as np

from .build import write_json

_telemetry_cache = ContextVar('telemetry_cache', default=None)


@contextmanager
def telemetry_cache():
    """One recording's arrays shared by response, damage and optional rendering."""
    token = _telemetry_cache.set({})
    try:
        yield
    finally:
        _telemetry_cache.reset(token)


def rigid_align(points, reference):
    """Remove rigid motion, retaining deformation (proper rotation, no reflection)."""
    center, target = points.mean(axis=0), reference.mean(axis=0)
    u, _, vt = np.linalg.svd((points-center).T @ (reference-target))
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    return (points-center) @ (u @ correction @ vt) + target


def load_csv(path, columns=None):
    cache = _telemetry_cache.get()
    if cache is not None:
        key = Path(path).resolve()
        if key not in cache:
            with key.open(encoding='utf-8') as stream:
                header = stream.readline().strip().split(',')
                values = np.loadtxt(stream, delimiter=',', ndmin=2)
            cache[key] = header, values
        header, values = cache[key]
        return values if columns is None else values[:, [header.index(n) for n in columns]]
    with path.open(encoding="utf-8") as stream:
        header = stream.readline().strip().split(",")
    usecols = [header.index(name) for name in columns] if columns else None
    return np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2, usecols=usecols)


def probe_response(telemetry, metadata, scenario):
    """Work-conjugate displacement: sum of node motion dotted with load fractions."""
    names = scenario["load_nodes"]
    size = len(names)
    raw = load_csv(telemetry/"probes.csv", ("t", "cid", "x", "y", "z", "vx", "vy", "vz", "force_n"))
    data = raw[:len(raw)//size*size].reshape(-1, size, 9)
    if not len(data) or not np.all(np.isfinite(data)):
        raise ValueError("Missing or nonfinite probe telemetry")
    lookup = {n["name"]: n for n in metadata["nodes"]}
    expected_ids = [lookup[name]["cid"] for name in names]
    if not np.all(data[:, :, 1] == expected_ids) or not np.all(data[:, :, 0] == data[:, :1, 0]):
        raise ValueError("Probe identities or timestamps differ")
    t = data[:, 0, 0]
    if np.any(np.diff(t) <= 0):
        raise ValueError("Probe timestamps are not strictly increasing")
    vectors = scenario.get("load_vectors") or {name: [0, 0, -1/size] for name in names}
    pattern = np.array([vectors[name] for name in names])
    initial = np.array([lookup[name]["initial"] for name in names])
    displacement = np.einsum("tnk,nk->t", data[:, :, 2:5]-initial, pattern)
    velocity = np.einsum("tnk,nk->t", data[:, :, 5:8], pattern)
    force = data[:, :, 8].sum(axis=1)
    force_consistent = None  # Old recordings have magnitudes only.
    with (telemetry/"probes.csv").open(encoding="utf-8") as stream:
        header = stream.readline().strip().split(",")
    if all(name in header for name in ("fx", "fy", "fz")):
        components = load_csv(telemetry/"probes.csv", ("fx", "fy", "fz"))[:len(data)*size].reshape(-1, size, 3)
        expected_amplitude = scenario["force_n"]*np.clip((t-scenario["settle_s"])/scenario["ramp_s"], 0, 1)
        release = scenario["settle_s"]+scenario["ramp_s"]+scenario["hold_s"]
        expected_amplitude[t >= release] = 0
        force_consistent = bool(np.allclose(components, expected_amplitude[:, None, None]*pattern, rtol=1e-6, atol=1e-5))
    return {"t": t, "data": data, "initial": initial, "pattern": pattern,
            "displacement": displacement, "velocity": velocity, "force": force,
            "force_consistent": force_consistent}


def graphics_velocity_check(telemetry, metadata, response, scenario, check_end):
    """Independent graphics-cadence positions versus physics-rate velocities.

    Remove only the initial coordinate offset, using the unloaded interval.
    Position lag is bounded by measured refresh cadence, never fitted to make
    a recording pass. An unsettled hold remains a separate physical failure.
    """
    size=len(scenario['load_nodes'])
    raw=load_csv(telemetry/'gfx.csv')
    if len(raw)%size: raise ValueError('Incomplete graphics probe frame')
    data=raw.reshape(-1,size,raw.shape[1]);t=data[:,0,0]
    if len(t)<3 or not np.isfinite(data).all() or np.any(np.diff(t)<=0):
        raise ValueError('Missing or invalid graphics-cadence telemetry')
    if not np.all(data[:,:,1]==response['data'][0,:,1]) or not np.all(data[:,:,0]==t[:,None]):
        raise ValueError('Graphics probe identities or timestamps differ')
    if t[-1]<scenario['duration']-.25 or np.max(np.diff(t))>.25:
        raise ValueError('Incomplete graphics-cadence recording')
    positions=data[:,:,2:5]-response['initial']
    pt=response['t'];velocity=response['velocity'].copy()
    moving=metadata.get('moving_measurement_anchor')
    if moving:
        # Free fixtures have no fixed world anchor. Validate relative deformation
        # with position AND velocity in the same moving-node frame, rather than
        # adding a graphics origin to a differently cached node position.
        anchor=next(n for n in metadata['nodes'] if n['name']==moving)
        positions=positions-(data[:,:,5:8]-anchor['initial'])
        av=load_csv(telemetry/'probes.csv',('avx','avy','avz')).reshape(-1,size,3)
        velocity-=np.einsum('tnk,nk->t',av,response['pattern'])
    position=np.einsum('tnk,nk->t',positions,response['pattern'])
    integral=np.r_[0,np.cumsum((velocity[1:]+velocity[:-1])*.5*np.diff(pt))]
    integrated=np.interp(t,pt,integral)
    baseline=(t>=0)&(t<min(.5,scenario['settle_s']))
    window=(t>=max(0,check_end-.5))&(t<check_end)
    if baseline.sum()<2 or window.sum()<2: raise ValueError('Insufficient coordinate-check samples')
    offset=float(np.mean((position-integrated)[baseline]))
    error=float(np.max(abs((position-integrated-offset)[window])))
    cadence=float(np.max(np.diff(t)))
    speeds=abs(velocity[(pt>=max(0,check_end-.5-cadence))&(pt<=check_end)])
    amplitude=float(np.max(abs(position[window]-np.mean(position[baseline]))))
    tolerance=max(2e-6,amplitude*.01)+float(np.max(speeds))*(cadence+float(np.max(np.diff(pt))))
    return dict(position_velocity_consistent=error<=tolerance,
                position_velocity_check_scope=('relative to moving node '+moving if moving else 'fixed world frame')+'; graphics samples against physics velocity integral with measured cadence bound',
                coordinate_check_end_s=check_end,
                coordinate_error_m=error,coordinate_tolerance_m=tolerance,position_refresh_max_gap_s=cadence,
                initial_coordinate_offset_m=offset)


def load_run(run):
    directory = json.loads((run / "telemetry_location.json").read_text())["directory"]
    telemetry = run / directory
    metadata = json.loads((telemetry / "metadata.json").read_text())
    raw = load_csv(telemetry / "nodes.csv", ("t", "cid", "x", "y", "z", "vx", "vy", "vz"))
    count = len(metadata["nodes"])
    complete = len(raw) // count
    if not complete:
        raise ValueError("No complete telemetry frame")
    data = raw[:complete*count].reshape(complete, count, 8)
    ids = np.array([n["cid"] for n in metadata["nodes"]])
    if not np.all(data[:, :, 1] == ids) or not np.all(data[:, :, 0] == data[:, :1, 0]):
        raise ValueError("Node telemetry has inconsistent identities or timestamps")
    if not np.all(np.isfinite(data)):
        raise ValueError("Nonfinite node telemetry")
    t = data[:, 0, 0]
    if np.any(np.diff(t) <= 0):
        raise ValueError("Telemetry timestamps are not strictly increasing")
    experiment = json.loads((run / "experiment.json").read_text())
    return telemetry, metadata, data, experiment


def settling_time(t, displacement, release, tolerance):
    indices = np.flatnonzero(t >= release)
    if not len(indices):
        return None
    bad = indices[np.abs(displacement[indices]) > tolerance]
    first = bad[-1]+1 if len(bad) else indices[0]
    # Require one full second of evidence inside the band.
    if first >= len(t) or t[-1]-t[first] < 1:
        return None
    return float(t[first]-release)


def create_report(run: Path, *, render=True):
    run = run.resolve()
    telemetry, meta, data, experiment = load_run(run)
    scenario = experiment["scenario"]
    t, position, velocity = data[:, 0, 0], data[:, :, 2:5], data[:, :, 5:8]
    reference = np.array([n["initial"] for n in meta["nodes"]])
    mass = np.array([n["mass"] for n in meta["nodes"]])
    aligned = np.array([rigid_align(p, reference) for p in position]) if scenario["name"] == "idle" else position
    deformation = aligned-reference
    distances = np.linalg.norm(deformation, axis=2)
    rms_shape = np.sqrt(np.mean(distances**2, axis=1))
    speed_rms = np.sqrt(np.mean(np.sum(velocity**2, axis=2), axis=1))
    tail = t >= max(0, t[-1]-2)
    completion_file = telemetry / "completion.json"
    completion = json.loads(completion_file.read_text()) if completion_file.exists() else {}
    metrics = {
        "recording_status": completion.get("status", "incomplete"),
        "recorded_seconds": float(t[-1]),
        "requested_seconds": scenario["duration"],
        "measured_mass_kg": float(mass.sum()),
        "peak_shape_rms_m": float(rms_shape.max()),
        "final_shape_rms_m": float(np.mean(rms_shape[tail])),
        "peak_node_displacement_m": float(distances.max()),
        "tail_world_speed_rms_m_s": float(np.sqrt(np.mean(speed_rms[tail]**2))),
        "physics_peak_node_speed_m_s": completion.get("peak_node_speed_m_s"),
        "physics_peak_beam_length_change_m": completion.get("peak_beam_length_change_m"),
        "samples": len(t), "actual_sample_hz": float((len(t)-1)/(t[-1]-t[0])) if len(t)>1 else 0,
        "max_sample_gap_s": float(np.diff(t).max()) if len(t)>1 else None,
        "physics_dt_s": meta["physics_dt"],
        "shape_measurement": "rigid motion removed" if scenario["name"] == "idle" else "fixed world fixture",
        "position_readback_note": "Raw positions can repeat between graphics updates; sampling frequency is not position refresh frequency. Velocity is the high-rate motion channel.",
        "position_reference": meta.get("position_reference", "vehicle origin"),
    }
    supports = [i for i, node in enumerate(meta["nodes"]) if node["fixed"]]
    if supports:
        metrics["support_max_motion_m"] = float(distances[:, supports].max())
    cids = {n["cid"]: i for i,n in enumerate(meta["nodes"])}
    edges = np.array([[cids[b["id1"]], cids[b["id2"]]] for b in meta["beams"]], dtype=int)
    beam_data = load_csv(telemetry / "beams.csv", ("t", "cid", "length", "rest_length", "native_force", "broken"))
    nbeams = len(meta["beams"])
    beam_data = beam_data[:len(beam_data)//nbeams*nbeams].reshape(-1,nbeams,6)
    if len(beam_data):
        initial_lengths = np.array([b["initial_length"] for b in meta["beams"]])
        metrics.update({"broken_beams": int(beam_data[-1,:,5].sum()),
                        "peak_absolute_length_strain": float(np.max(np.abs(beam_data[:,:,2]-initial_lengths)/np.maximum(initial_lengths,1e-12))),
                        "max_rest_length_change_m": float(np.max(np.abs(beam_data[:,:,3]-beam_data[0,:,3])))})
    probe_t, deflection, force = t, np.zeros_like(t), np.zeros_like(t)
    if scenario["load_nodes"]:
        response = probe_response(telemetry, meta, scenario)
        probes = response["data"]
        probe_t = response["t"]
        deflection = response["displacement"]
        force = response["force"]
        release=scenario["settle_s"]+scenario["ramp_s"]+scenario["hold_s"]
        hold=(probe_t>=release-0.5)&(probe_t<release)
        end=probe_t>=probe_t[-1]-1
        held=float(np.mean(deflection[hold])) if hold.any() else None
        # An independent physics-rate velocity integral catches coordinate mistakes.
        # Compare over the settled hold, not across graphics-cadence transient steps.
        integrated = np.cumsum(response["velocity"]*np.diff(probe_t, prepend=0))
        integrated_held = float(np.mean(integrated[hold])) if hold.any() else None
        coordinate_error = abs(held-integrated_held) if held is not None else None
        position_consistent = bool(coordinate_error is not None and coordinate_error <= max(2e-6, abs(held)*.01))
        if scenario.get('expected_damage'):
            events_path=telemetry/'events.json'
            damage_events=json.loads(events_path.read_text()) if events_path.exists() else []
            first_damage=min((e['time'] for e in damage_events if e['type'] in ('persistent_deformation','beam_broke','controlled_cut')),default=release)
            check_end=max(scenario['settle_s'],first_damage-.1)
            intact=(probe_t>=max(0,check_end-.5))&(probe_t<check_end)
            changed=np.r_[True,np.abs(np.diff(deflection))>1e-12]
            updates=probe_t[changed & (probe_t<check_end)]
            # Bound the positional lag by the observed graphics refresh interval.
            cadence=min(.1,float(np.max(np.diff(updates)))) if len(updates)>1 else 0.
            error=float(abs(np.mean(deflection[intact]-integrated[intact]))) if intact.any() else None
            amplitude=float(np.max(abs(deflection[intact]))) if intact.any() else 0.
            speed=float(np.max(abs(response['velocity'][intact]))) if intact.any() else 0.
            tolerance=max(2e-6,amplitude*.01)+cadence*speed
            position_consistent=bool(error is not None and error<=tolerance)
            metrics.update(position_velocity_check_scope='intact interval before first damage; cadence-bounded position lag',
                           intact_coordinate_check_end_s=check_end,intact_coordinate_error_m=error,
                           intact_coordinate_tolerance_m=tolerance)
        coordinate_check=None
        if meta.get('telemetry_version',0)>=3:
            coordinate_check=graphics_velocity_check(telemetry,meta,response,scenario,
                scenario['duration'] if meta.get('moving_measurement_anchor') else
                check_end if scenario.get('expected_damage') else release)
            position_consistent=coordinate_check['position_velocity_consistent']
            metrics.update(coordinate_check)
        settled=bool(held is not None and np.ptp(deflection[hold])<=max(1e-5,abs(held)*0.02))
        ring=probe_t>=release
        probe_speed_squared = np.sum(probes[:, :, 5:8]**2, axis=2)
        metrics.update({"held_deflection_m": held, "hold_settled": settled,
                        "applied_force_consistent": response["force_consistent"],
                        "velocity_integrated_held_deflection_m": integrated_held,
                        "position_velocity_hold_difference_m": coordinate_error,
                        "position_velocity_consistent": position_consistent,
                        "apparent_stiffness_n_m": scenario["force_n"]/held if held is not None and held>1e-9 else None,
                        "residual_load_point_deflection_m": float(np.mean(deflection[end])),
                        "ringdown_rms_m": float(np.sqrt(np.mean(deflection[ring]**2))) if ring.any() else None,
                        "ringdown_probe_speed_rms_m_s": float(np.sqrt(np.mean(probe_speed_squared[ring]))) if ring.any() else None,
                        "probe_samples": len(probe_t),
                        "probe_position_change_samples": int(np.count_nonzero(np.any(np.diff(probes[:, :, 2:5], axis=0) != 0, axis=(1, 2)))),
                        "settling_time_s": settling_time(probe_t,deflection,release,max(1e-5,abs(held or 0)*0.05))})
        if scenario["name"] == "torsion":
            width = abs(response["initial"][0, 0]-response["initial"][1, 0])
            angle = 2*held/width if held is not None else None
            moment = scenario["force_n"]*width/2
            metrics.update(torsional_moment_nm=moment, held_twist_rad=angle,
                           torsional_stiffness_nm_rad=moment/angle if angle and angle > 0 else None)
        if scenario["name"] == "spring":
            expected=0.01/experiment["parameters"]["spring_scale"]
            metrics["spring_expected_deflection_m"]=expected
            metrics["spring_relative_error"]=abs(held-expected)/expected if held is not None else None
    projection_file = run / "projection_report.json"
    if projection_file.exists():
        projection = json.loads(projection_file.read_text())
        for key in ("projection", "highest_linear_mode_hz", "tensor_magnitude_retention", "tensor_directional_shape_error"):
            metrics[key] = projection[key]
    write_json(run / "metrics.json", metrics)
    if not render:
        return metrics
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Line3DCollection
    figure, axes=plt.subplots(3,1,figsize=(10,9),layout="constrained")
    axes[0].plot(t,rms_shape*1000,label="RMS shape change")
    axes[0].plot(t,distances.max(axis=1)*1000,label="Worst node",alpha=.7)
    axes[0].set_ylabel("Deformation (mm)"); axes[0].legend()
    axes[1].plot(t,speed_rms); axes[1].set_ylabel("World RMS speed (m/s)")
    axes[2].plot(probe_t,deflection*1000,color="tab:blue"); axes[2].set_ylabel("Load-pattern displacement (mm)")
    force_axis=axes[2].twinx(); force_axis.plot(probe_t,force,color="tab:orange",alpha=.5); force_axis.set_ylabel("Applied load (N)")
    for ax in axes: ax.grid(alpha=.2); ax.set_xlabel("Simulation time (s)")
    figure.suptitle(f'{experiment["parameters"]["name"]} / {scenario["name"]} — measured in BeamNG.drive')
    figure.savefig(run/"response.png",dpi=140); plt.close(figure)

    indices=[0,int(np.argmax(rms_shape)),int(np.argmin(abs(t-(scenario["settle_s"]+scenario["ramp_s"]+scenario["hold_s"])))),len(t)-1]
    figure=plt.figure(figsize=(12,9),layout="constrained")
    center=reference.mean(axis=0); radius=max(float(np.ptp(np.concatenate([reference,aligned.reshape(-1,3)]),axis=0).max())*.55,0.1)
    for panel,index in enumerate(indices):
        ax=figure.add_subplot(2,2,panel+1,projection="3d")
        ax.add_collection3d(Line3DCollection(reference[edges],colors="lightgray",linewidths=.5))
        ax.add_collection3d(Line3DCollection(aligned[index][edges],colors="#2d6ca2",linewidths=.6))
        ax.scatter(*aligned[index].T,c=distances[index]*1000,cmap="magma",s=10,vmin=0,vmax=max(distances.max()*1000,.001))
        ax.set(xlim=(center[0]-radius,center[0]+radius),ylim=(center[1]-radius,center[1]+radius),zlim=(center[2]-radius,center[2]+radius))
        ax.set_box_aspect((1,1,1)); ax.view_init(24,-55); ax.set_title(f"t={t[index]:.3f}s; actual scale")
        ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)"); ax.set_zlabel("Z (m)")
    figure.suptitle("Recorded frame motion · gray = initial shape")
    figure.savefig(run/"deformation.png",dpi=140); plt.close(figure)
    stride=max(1,int(round(len(t)/500)))
    replay={"times":t[::stride].round(6).tolist(),"frames":aligned[::stride].round(7).tolist(),
            "initial":reference.tolist(),"edges":edges.tolist(),"names":[n["name"] for n in meta["nodes"]]}
    template=(Path(__file__).parent/"replay.html").read_text(encoding="utf-8")
    page=template.replace("__REPLAY_DATA__",json.dumps(replay).replace("<","\\u003c"))
    page=page.replace("__TITLE__",html.escape(f'{experiment["parameters"]["name"]} / {scenario["name"]}'))
    page=page.replace("__METRICS__",html.escape(json.dumps(metrics,indent=2)))
    page=page.replace("__STATUS__",html.escape(f"Recording: {metrics['recording_status']} · {t[-1]:.3f} / {scenario['duration']:.3f} seconds"))
    (run/"report.html").write_text(page,encoding="utf-8")
    return metrics


def compare_runs(runs, output):
    runs = list(runs)
    if len({path.resolve() for path in runs}) != len(runs):
        raise ValueError("The same run cannot count as multiple repeats")
    if not runs:
        raise ValueError("No runs to compare")
    groups=defaultdict(list)
    for path in runs:
        path=path.resolve()
        result=json.loads((path/"result.json").read_text())
        if result["status"] != "completed":
            raise ValueError(f"Cannot rank incomplete run: {path.name} ({result['status']})")
        experiment=json.loads((path/"experiment.json").read_text())
        manifest=json.loads((path/"build_manifest.json").read_text())
        metrics=json.loads((path/"metrics.json").read_text())
        if metrics.get("position_velocity_consistent") is False:
            raise ValueError(f"Position/velocity cross-check failed: {path.name}")
        if metrics.get("applied_force_consistent") is False:
            raise ValueError(f"Applied load cross-check failed: {path.name}")
        if metrics.get("support_max_motion_m", 0) > 5e-6:
            raise ValueError(f"Fixed-support readback moved: {path.name}")
        key=(experiment["scenario"]["name"],experiment["parameters"]["name"])
        groups[key].append((path,experiment,metrics,manifest))
    # Insertion order chooses the first candidate per scenario as baseline.
    baselines={}; rows=[]
    selected=("held_deflection_m","held_twist_rad","torsional_stiffness_nm_rad","ringdown_rms_m","ringdown_probe_speed_rms_m_s","settling_time_s","final_shape_rms_m","tail_world_speed_rms_m_s","broken_beams","tensor_directional_shape_error")
    for (scenario,candidate),records in groups.items():
        baselines.setdefault(scenario,records)
        baseline=baselines[scenario]
        reference_scenario=baseline[0][1]["scenario"]
        for record in records:
            if record[1]["parameters"] != records[0][1]["parameters"]:
                raise ValueError("Candidate name reused with different parameters; give each candidate a unique name")
            if record[3].get("jbeam_sha256") != records[0][3].get("jbeam_sha256"):
                raise ValueError("Repeated candidate has different built JBeam; start a new candidate group")
            if record[1]["scenario"]!=reference_scenario:
                raise ValueError("Cannot compare different loads, durations, fixtures, or sampling settings")
            a=record[3]["nodes"]; b=baseline[0][3]["nodes"]
            if a.keys()!=b.keys() or any(a[n]["position"]!=b[n]["position"] for n in a):
                raise ValueError("Node geometry differs; start a separate comparison group")
        for metric in selected:
            values=[r[2][metric] for r in records if isinstance(r[2].get(metric),(int,float))]
            base=[r[2][metric] for r in baseline if isinstance(r[2].get(metric),(int,float))]
            if not values or not base: continue
            mean,base_mean=float(np.mean(values)),float(np.mean(base))
            noise=float(max(np.ptp(base),3*np.std(base,ddof=1))) if len(base)>1 else None
            delta=mean-base_mean
            meaningful=abs(delta)>max(noise,abs(base_mean)*.01,1e-8) if noise is not None else None
            rows.append({"scenario":scenario,"candidate":candidate,"metric":metric,"mean":mean,
                         "repeats":len(values),"baseline_mean":base_mean,"delta":delta,
                         "baseline_variation":noise,"meaningful_change":meaningful})
    output=output.resolve(); output.mkdir(parents=True,exist_ok=True)
    write_json(output/"comparison.json",{"runs":[str(p.resolve()) for p in runs],"rows":rows,
        "interpretation":"First candidate per scenario is baseline. Change detection is descriptive, not proof of physical improvement."})
    lines=["<!doctype html><meta charset='utf-8'><title>Frame comparison</title>",
           "<style>body{font:15px system-ui;margin:2rem}table{border-collapse:collapse}td,th{padding:.5rem;border:1px solid #ccc}</style>",
           "<h1>Frame comparison</h1><p>First candidate per scenario is the baseline. Changes are not automatically improvements.</p>",
           "<p>Change threshold: greater than the baseline range, three baseline standard deviations, and 1% of the baseline mean. At least two baseline repeats are required. Candidate uncertainty needs candidate repeats too.</p>",
           "<table><tr><th>Scenario</th><th>Candidate</th><th>Metric</th><th>Mean</th><th>Delta</th><th>Evidence</th></tr>"]
    for r in rows:
        evidence="Baseline not repeated" if r["meaningful_change"] is None else "Change exceeds baseline variation" if r["meaningful_change"] else "No meaningful change"
        values=[r["scenario"],r["candidate"],r["metric"],f'{r["mean"]:.6g}',f'{r["delta"]:+.6g}',evidence]
        lines.append("<tr>"+"".join(f"<td>{html.escape(str(v))}</td>" for v in values)+"</tr>")
    lines.append("</table><h2>Recorded responses</h2><p>Positions may refresh at graphics cadence. Velocity records resolve faster motion. Each curve is an individual run.</p>")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for index, scenario in enumerate(baselines):
        figure, axes = plt.subplots(2, 1, figsize=(11, 7), layout="constrained")
        for color, ((group_scenario, candidate), records) in enumerate(groups.items()):
            if group_scenario != scenario:
                continue
            for repeat, (path, experiment, _, _) in enumerate(records):
                telemetry, meta, data, _ = load_run(path)
                label = candidate if repeat == 0 else None
                t = data[:, 0, 0]
                if experiment["scenario"]["load_nodes"]:
                    response = probe_response(telemetry, meta, experiment["scenario"])
                    axes[0].plot(response["t"], response["displacement"]*1000, label=label, color=f"C{color%10}", alpha=.65)
                    axes[0].set_ylabel("Load-pattern displacement (mm)")
                else:
                    reference = np.array([n["initial"] for n in meta["nodes"]])
                    shape = np.array([rigid_align(p, reference)-reference for p in data[:, :, 2:5]])
                    axes[0].plot(t, np.sqrt(np.mean(np.sum(shape**2, axis=2), axis=1))*1000, label=label, color=f"C{color%10}", alpha=.65)
                    axes[0].set_ylabel("RMS shape change (mm)")
                axes[1].plot(t, np.sqrt(np.mean(np.sum(data[:, :, 5:8]**2, axis=2), axis=1)), color=f"C{color%10}", alpha=.65)
        for ax in axes:
            ax.set_xlabel("Simulation time (s)"); ax.grid(alpha=.2)
        axes[0].legend(); axes[1].set_ylabel("World RMS speed (m/s)")
        figure.suptitle(scenario)
        filename = f"response-{index}.png"
        figure.savefig(output/filename, dpi=140); plt.close(figure)
        lines.append(f'<img style="max-width:100%" src="{filename}" alt="{html.escape(scenario)} response comparison">')
    lines.append("<h2>Individual runs</h2><ul>")
    for path in runs:
        lines.append(f'<li><a href="{html.escape((path.resolve()/"report.html").as_uri(), quote=True)}">{html.escape(path.name)}</a></li>')
    lines.append("</ul>")
    (output/"index.html").write_text("\n".join(lines),encoding="utf-8")
    return output/"index.html"
