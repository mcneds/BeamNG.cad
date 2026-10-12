from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ParameterSet:
    name: str = "baseline"
    material: dict[str, Any] = field(default_factory=dict)
    spring_scale: float = 1.0
    damping_scale: float = 1.0
    projection: str = "none"
    calibration: str | None = None

    def validate(self):
        import math
        if not self.name.strip():
            raise ValueError("A candidate name is required")
        if self.projection != "none":
            raise ValueError(f"Unknown projection: {self.projection}")
        if self.calibration and (self.material or self.spring_scale != 1 or self.damping_scale != 1):
            raise ValueError('A calibration artifact already defines its properties; do not combine it with material/projection/scale overrides')
        for name in ("spring_scale", "damping_scale"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


@dataclass
class TestScenario:
    name: str
    duration: float
    gravity: float
    fixed_nodes: list[str] = field(default_factory=list)
    load_nodes: list[str] = field(default_factory=list)
    force_n: float = 0.0
    settle_s: float = 2.0
    ramp_s: float = 1.0
    hold_s: float = 3.0
    sample_hz: float = 200.0
    # Fractions of force_n in world XYZ; sum of vector magnitudes must be one.
    load_vectors: dict[str, list[float]] = field(default_factory=dict)
    expected_damage: bool = False
    cut_edges: list[list[str]] = field(default_factory=list)
    cut_at_s: float = 3.0
    capture: bool = False

    def resolved_load_vectors(self):
        return self.load_vectors or {name: [0.0, 0.0, -1/len(self.load_nodes)] for name in self.load_nodes}

    def validate(self):
        import math
        for key in ("duration", "gravity", "force_n", "settle_s", "ramp_s", "hold_s", "sample_hz"):
            if not math.isfinite(getattr(self, key)):
                raise ValueError(f"Scenario {key} must be finite")
        if self.duration <= 0 or not 0 < self.sample_hz <= 2000:
            raise ValueError("Duration must be positive and sample rate must be in (0, 2000]")
        if self.settle_s < 0 or self.ramp_s <= 0 or self.hold_s <= 0:
            raise ValueError("Invalid settle/ramp/hold durations")
        if self.load_nodes and self.settle_s+self.ramp_s+self.hold_s >= self.duration:
            raise ValueError("Loaded scenarios need time after release")
        if set(self.fixed_nodes) & set(self.load_nodes):
            raise ValueError("A loaded node cannot also be a fixed support")
        if self.cut_edges and (not self.expected_damage or not 0 < self.cut_at_s < self.duration):
            raise ValueError("Controlled cuts require expected damage and an in-range cut time")
        if any(len(e) != 2 or e[0] == e[1] for e in self.cut_edges):
            raise ValueError("Cut edges need two distinct node names")
        if len(set(self.load_nodes)) != len(self.load_nodes) or len(set(self.fixed_nodes)) != len(self.fixed_nodes):
            raise ValueError("Fixture node lists must not contain duplicates")
        if self.load_vectors:
            if set(self.load_vectors) != set(self.load_nodes):
                raise ValueError("Load vectors must match load nodes")
            vectors = list(self.load_vectors.values())
            if any(len(v) != 3 or not all(math.isfinite(x) for x in v) for v in vectors):
                raise ValueError("Load vectors require three finite components")
            if not math.isclose(sum(math.sqrt(sum(x*x for x in v)) for v in vectors), 1, abs_tol=1e-9):
                raise ValueError("Load vector magnitudes must sum to one")

    @classmethod
    def named(cls, name: str):
        if name == "idle":
            return cls(name, 15.0, -9.81)
        if name == "flex":
            return cls(name, 16.0, 0.0,
                       ["sp00l", "sp00r", "sp02l", "sp02r"],
                       ["sp01l", "sp01r"], 100.0)
        if name == "spring":
            return cls(name, 8.0, 0.0, ["a", "b", "c"], ["p"], 10.0,
                       settle_s=1.0, ramp_s=1.0, hold_s=2.0)
        if name in ("spring-break", "spring-yield"):
            scenario = cls.named("spring")
            scenario.name = name; scenario.force_n = 16 if name == "spring-break" else 10
            scenario.ramp_s = 4; scenario.hold_s = 1; scenario.duration = 8
            scenario.expected_damage = True; scenario.capture = True
            return scenario
        if name == "torsion":
            scenario = cls.named("flex")
            scenario.name = name
            scenario.load_vectors = {"sp01l": [0, 0, -.5], "sp01r": [0, 0, .5]}
            return scenario
        raise ValueError(f"Unknown scenario: {name}")


@dataclass
class HarnessProject:
    source: Path = ROOT.parent.parent / "Test Programs"
    game: Path = Path(r"D:\SteamLibrary\steamapps\common\BeamNG.drive")
    userpath: Path = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "BeamNGCadHarness" / "drive"
    runs: Path = ROOT / "runs"
    startup_timeout: float = 180.0
    test_timeout: float = 120.0
    build_timeout: float = 300.0

    @property
    def executable(self):
        return self.game / "Bin64" / "BeamNG.drive.x64.exe"

    @classmethod
    def load(cls, path: Path | None = None):
        if path is None:
            path = ROOT / "project.local.json"
        data = json.loads(path.read_text()) if path.exists() else {}
        for key in ("source", "game", "userpath", "runs"):
            if key in data:
                value = Path(os.path.expandvars(data[key]))
                data[key] = (path.parent / value).resolve() if not value.is_absolute() else value
        return cls(**data)

    def to_dict(self):
        return {k: str(v) if isinstance(v, Path) else v for k, v in asdict(self).items()}


@dataclass
class RunResult:
    run_id: str
    path: str
    status: str
    scenario: str
    candidate: str
    failure_reason: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
