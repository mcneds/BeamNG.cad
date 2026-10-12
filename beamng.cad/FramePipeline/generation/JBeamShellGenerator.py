import argparse
import json
import math
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path


# ============================================================
# SOURCE / OUTPUT
# ============================================================

SCRIPT_DIRECTORY = Path(__file__).resolve().parent

# AlphaWrap.py writes this evaluated GRID_HULL mesh. It already contains
# the Shrinkwrap, Mirror, and Weld result, so this script needs neither
# Blender nor bpy.
DEFAULT_SOURCE_MESH = SCRIPT_DIRECTORY / "mochi_hull.off"
DEFAULT_OUTPUT_JBEAM = SCRIPT_DIRECTORY / "mochi_raw.jbeam"

PART_NAME = "mochi"
PART_DISPLAY_NAME = "Mochi"
SLOT_TYPE = "main"

SHELL_GROUP = "mochi_shell"
CAGE_GROUP = "mochi_cage"


# ============================================================
# COORDINATE EXPORT
# ============================================================

EXPORT_SCALE = 1.0
EXPORT_OFFSET = (0.0, 0.0, 0.0)
EXPORT_AXIS_SIGN = (1.0, 1.0, 1.0)


# ============================================================
# STRUCTURAL CAGE
# ============================================================

CAGE_STATION_COUNT = 7
PROFILE_SAMPLE_RADIUS = 0.70

CAGE_WIDTH_SCALE = 0.58
CAGE_LOWER_Z_FRACTION = 0.24
CAGE_UPPER_Z_FRACTION = 0.72

MIN_CAGE_WIDTH_FRACTION = 0.12
MIN_CAGE_HEIGHT_FRACTION = 0.16

USE_FRONT_TETRA_CAP = True
FRONT_CAP_SURFACE_BAND = 0.08
FRONT_CAP_INSET_FRACTION = 0.18

CROSS_CONNECT_ALL_STATION_NODES = True


# ============================================================
# SHELL ATTACHMENTS
# ============================================================

SHELL_ATTACHMENTS_PER_NODE = 3
ATTACHMENT_DISTANCE_WEIGHT = 1.5
MIN_TETRA_VOLUME_RATIO = 1e-6


# ============================================================
# JBEAM PHYSICAL SETTINGS
# ============================================================

SHELL_NODE_WEIGHT = 0.45
CAGE_NODE_WEIGHT = 1.8

SHELL_BEAM_SPRING = 450000
SHELL_BEAM_DAMP = 70
SHELL_BEAM_DEFORM = 9000
SHELL_BEAM_STRENGTH = 35000

CAGE_BEAM_SPRING = 1800000
CAGE_BEAM_DAMP = 120
CAGE_BEAM_DEFORM = 22000
CAGE_BEAM_STRENGTH = "FLT_MAX"

TETHER_BEAM_SPRING = 900000
TETHER_BEAM_DAMP = 90
TETHER_BEAM_DEFORM = 14000
TETHER_BEAM_STRENGTH = 70000

TRIANGLE_DRAG_COEF = 10


# ============================================================
# SMALL DEPENDENCY-FREE VECTOR TYPE
# ============================================================

@dataclass
class Vec3:
    x: float
    y: float
    z: float

    def __add__(self, other):
        return Vec3(
            self.x + other.x,
            self.y + other.y,
            self.z + other.z,
        )

    def __sub__(self, other):
        return Vec3(
            self.x - other.x,
            self.y - other.y,
            self.z - other.z,
        )

    def __mul__(self, scalar):
        return Vec3(
            self.x * scalar,
            self.y * scalar,
            self.z * scalar,
        )

    __rmul__ = __mul__

    def __truediv__(self, scalar):
        return Vec3(
            self.x / scalar,
            self.y / scalar,
            self.z / scalar,
        )

    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z

    def dot(self, other):
        return (
            self.x * other.x
            + self.y * other.y
            + self.z * other.z
        )

    def cross(self, other):
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    @property
    def length(self):
        return math.sqrt(self.dot(self))

    def lerp(self, other, factor):
        return self + (other - self) * factor


ZERO = Vec3(0.0, 0.0, 0.0)


# ============================================================
# OFF INPUT
# ============================================================

def read_off(filepath):
    path = Path(filepath)

    if not path.is_file():
        raise FileNotFoundError(
            "Wrapped shell mesh was not found:\n"
            f"{path}\n\n"
            "Run the updated AlphaWrap.py once, or pass another OFF "
            "mesh path as the first argument."
        )

    tokens = []

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.split("#", 1)[0].strip()

            if line:
                tokens.extend(line.split())

    if not tokens or tokens[0] != "OFF":
        raise RuntimeError(f"Input is not a valid OFF mesh: {path}")

    cursor = 1
    vertex_count = int(tokens[cursor])
    face_count = int(tokens[cursor + 1])
    cursor += 3

    vertices = []

    for _ in range(vertex_count):
        vertices.append(Vec3(
            float(tokens[cursor]),
            float(tokens[cursor + 1]),
            float(tokens[cursor + 2]),
        ))
        cursor += 3

    triangles = []

    for _ in range(face_count):
        count = int(tokens[cursor])
        cursor += 1
        face = tuple(
            int(tokens[cursor + index])
            for index in range(count)
        )
        cursor += count

        if count < 3:
            continue

        for corner in range(1, count - 1):
            triangle = (face[0], face[corner], face[corner + 1])
            a, b, c = (vertices[index] for index in triangle)

            if (b - a).cross(c - a).length > 1e-10:
                triangles.append(triangle)

    if not vertices or not triangles:
        raise RuntimeError(f"OFF mesh has no usable surface: {path}")

    used = sorted({index for face in triangles for index in face})
    index_map = {old: new for new, old in enumerate(used)}

    return (
        [vertices[index] for index in used],
        [
            tuple(index_map[index] for index in face)
            for face in triangles
        ],
    )


def bounds(vertices):
    minimum = Vec3(
        min(vertex.x for vertex in vertices),
        min(vertex.y for vertex in vertices),
        min(vertex.z for vertex in vertices),
    )
    maximum = Vec3(
        max(vertex.x for vertex in vertices),
        max(vertex.y for vertex in vertices),
        max(vertex.z for vertex in vertices),
    )
    diagonal = (maximum - minimum).length

    if diagonal <= 1e-10:
        raise RuntimeError("The wrapped shell has zero-size bounds.")

    return minimum, maximum, diagonal


def triangle_edges(triangles):
    edges = set()

    for a, b, c in triangles:
        edges.add(tuple(sorted((a, b))))
        edges.add(tuple(sorted((b, c))))
        edges.add(tuple(sorted((c, a))))

    return sorted(edges)


def choose_reference_nodes(shell_vertices, shell_ids):
    """Choose six distinct shell nodes for BeamNG's reference frame.

    The triangulated shell is already infinitesimally rigid, so reference
    nodes can be ordinary structural nodes.  No internal cage is required.
    Targets mirror the former cage reference locations using normalized bounds.
    """

    minimum, maximum, _ = bounds(shell_vertices)
    size = maximum - minimum

    def target(x_fraction, y_fraction, z_fraction):
        return Vec3(
            minimum.x + size.x * x_fraction,
            minimum.y + size.y * y_fraction,
            minimum.z + size.z * z_fraction,
        )

    targets = (
        target(0.25, 0.45, 0.24),  # ref
        target(0.25, 0.65, 0.24),  # back
        target(0.75, 0.45, 0.24),  # left
        target(0.50, 0.45, 0.72),  # up
        target(0.75, 0.20, 0.24),  # left corner
        target(0.25, 0.20, 0.24),  # right corner
    )
    selected = []

    for desired in targets:
        available = [
            index
            for index in range(len(shell_vertices))
            if index not in selected
        ]
        selected.append(min(
            available,
            key=lambda index: (shell_vertices[index] - desired).length,
        ))

    return tuple(shell_ids[index] for index in selected)


# ============================================================
# INTERNAL TRIANGULAR CAGE
# ============================================================

def station_profile(vertices, station_y, sample_radius, fallback_count=12):
    sample = [
        vertex
        for vertex in vertices
        if abs(vertex.y - station_y) <= sample_radius
    ]

    if len(sample) < 4:
        sample = sorted(
            vertices,
            key=lambda vertex: abs(vertex.y - station_y),
        )[:min(fallback_count, len(vertices))]

    return sample


def create_cage(shell_vertices):
    if CAGE_STATION_COUNT < 2:
        raise ValueError("CAGE_STATION_COUNT must be at least 2.")

    minimum, maximum, _ = bounds(shell_vertices)
    size = maximum - minimum

    if size.y <= 1e-10:
        raise RuntimeError("The shell has no usable Y length.")

    station_step = size.y / (CAGE_STATION_COUNT - 1)
    sample_radius = station_step * PROFILE_SAMPLE_RADIUS
    center_x = (minimum.x + maximum.x) * 0.5

    cage_vertices = []
    cage_ids = []
    station_nodes = []

    for station_index in range(CAGE_STATION_COUNT):
        station_y = minimum.y + station_index * station_step
        sample = station_profile(
            shell_vertices,
            station_y,
            sample_radius,
        )
        sample_min_x = min(vertex.x for vertex in sample)
        sample_max_x = max(vertex.x for vertex in sample)
        sample_min_z = min(vertex.z for vertex in sample)
        sample_max_z = max(vertex.z for vertex in sample)

        local_width = max(
            sample_max_x - sample_min_x,
            size.x * MIN_CAGE_WIDTH_FRACTION,
        )
        local_height = max(
            sample_max_z - sample_min_z,
            size.z * MIN_CAGE_HEIGHT_FRACTION,
        )

        z_mid = (sample_min_z + sample_max_z) * 0.5
        profile_min_z = z_mid - local_height * 0.5
        half_width = local_width * 0.5 * CAGE_WIDTH_SCALE
        lower_z = (
            profile_min_z
            + local_height * CAGE_LOWER_Z_FRACTION
        )
        upper_z = (
            profile_min_z
            + local_height * CAGE_UPPER_Z_FRACTION
        )

        station = []
        definitions = (
            ("l", Vec3(center_x + half_width, station_y, lower_z)),
            ("r", Vec3(center_x - half_width, station_y, lower_z)),
            ("u", Vec3(center_x, station_y, upper_z)),
        )

        for suffix, coordinate in definitions:
            station.append(len(cage_vertices))
            cage_vertices.append(coordinate)
            cage_ids.append(f"cg{station_index:02d}{suffix}")

        station_nodes.append(tuple(station))

    if USE_FRONT_TETRA_CAP:
        band_limit = (
            minimum.y
            + station_step * FRONT_CAP_SURFACE_BAND
        )
        front_surface_vertices = [
            vertex
            for vertex in shell_vertices
            if vertex.y <= band_limit
        ]

        if not front_surface_vertices:
            front_surface_vertices = [
                min(shell_vertices, key=lambda vertex: vertex.y)
            ]

        front_surface_center = sum(
            front_surface_vertices,
            ZERO,
        ) / len(front_surface_vertices)
        front_surface_center.x = center_x

        next_station_center = sum(
            (cage_vertices[index] for index in station_nodes[1]),
            ZERO,
        ) / len(station_nodes[1])

        cap_coordinate = front_surface_center.lerp(
            next_station_center,
            FRONT_CAP_INSET_FRACTION,
        )

        cage_vertices = [cap_coordinate] + cage_vertices[3:]
        cage_ids = ["cg00t"] + cage_ids[3:]
        station_nodes = [
            (0,),
            *[
                tuple(index - 2 for index in station)
                for station in station_nodes[1:]
            ],
        ]

    cage_edges = set()

    for station in station_nodes:
        if len(station) == 1:
            continue

        if len(station) != 3:
            raise RuntimeError(
                "Cage stations must contain 1 cap node or 3 section nodes."
            )

        left, right, upper = station
        cage_edges.add(tuple(sorted((left, right))))
        cage_edges.add(tuple(sorted((right, upper))))
        cage_edges.add(tuple(sorted((upper, left))))

    for station_index in range(CAGE_STATION_COUNT - 1):
        current = station_nodes[station_index]
        following = station_nodes[station_index + 1]

        if (
            CROSS_CONNECT_ALL_STATION_NODES
            or len(current) != 3
            or len(following) != 3
        ):
            for first in current:
                for second in following:
                    cage_edges.add(tuple(sorted((first, second))))
        else:
            for local_index in range(3):
                cage_edges.add(tuple(sorted((
                    current[local_index],
                    following[local_index],
                ))))

            cage_edges.add(tuple(sorted((current[0], following[2]))))
            cage_edges.add(tuple(sorted((current[1], following[2]))))
            cage_edges.add(tuple(sorted((current[2], following[0]))))
            cage_edges.add(tuple(sorted((current[2], following[1]))))

    return (
        cage_vertices,
        cage_ids,
        station_nodes,
        sorted(cage_edges),
    )


def create_sparse_bottom_supports(shell_vertices):
    """Create a deformable three-station ladder below the shell interior."""

    minimum, maximum, _ = bounds(shell_vertices)
    size = maximum - minimum
    station_fractions = (0.12, 0.50, 0.88)
    sample_radius = size.y / 4.0
    support_vertices = []
    support_ids = []
    station_nodes = []
    lower_z = minimum.z + 0.20 * size.z

    for station_index, fraction in enumerate(station_fractions):
        station_y = minimum.y + fraction * size.y
        sample = station_profile(
            shell_vertices,
            station_y,
            sample_radius,
        )
        half_width = max(
            max(abs(vertex.x) for vertex in sample) * CAGE_WIDTH_SCALE,
            size.x * MIN_CAGE_WIDTH_FRACTION,
        )
        station = []

        for suffix, x in (("l", half_width), ("r", -half_width)):
            station.append(len(support_vertices))
            support_vertices.append(Vec3(x, station_y, lower_z))
            support_ids.append(f"sp{station_index:02d}{suffix}")

        station_nodes.append(tuple(station))

    support_edges = set()

    for left, right in station_nodes:
        support_edges.add(tuple(sorted((left, right))))

    for station_index in range(len(station_nodes) - 1):
        current_left, current_right = station_nodes[station_index]
        next_left, next_right = station_nodes[station_index + 1]
        support_edges.add(tuple(sorted((current_left, next_left))))
        support_edges.add(tuple(sorted((current_right, next_right))))

        # Alternate the bay diagonal so the ladder can rack and crumple by bay
        # without containing a dense tetrahedral internal cage.
        if station_index % 2 == 0:
            support_edges.add(tuple(sorted((current_left, next_right))))
        else:
            support_edges.add(tuple(sorted((current_right, next_left))))

    return (
        support_vertices,
        support_ids,
        station_nodes,
        sorted(support_edges),
    )


# ============================================================
# LOCAL FOUR-POINT SHELL ATTACHMENTS
# ============================================================

def tetrahedron_volume_six(a, b, c, d):
    return abs((b - a).dot((c - a).cross(d - a)))


def choose_attachment_nodes(
    shell_vertex,
    candidates,
    cage_vertices,
    global_diagonal,
):
    if SHELL_ATTACHMENTS_PER_NODE not in {3, 4}:
        raise ValueError("SHELL_ATTACHMENTS_PER_NODE must equal 3 or 4.")

    minimum_volume_six = (
        MIN_TETRA_VOLUME_RATIO
        * global_diagonal ** 3
        * 6.0
    )
    best_nodes = None
    best_score = -1.0

    for candidate_nodes in combinations(candidates, SHELL_ATTACHMENTS_PER_NODE):
        if SHELL_ATTACHMENTS_PER_NODE == 4:
            a, b, c, d = (
                cage_vertices[index]
                for index in candidate_nodes
            )
            volume_six = tetrahedron_volume_six(a, b, c, d)
        else:
            a, b, c = (
                cage_vertices[index]
                for index in candidate_nodes
            )
            volume_six = tetrahedron_volume_six(a, b, c, shell_vertex)

        if volume_six <= minimum_volume_six:
            continue

        longest_edge = max(
            (cage_vertices[first] - cage_vertices[second]).length
            for first, second in combinations(candidate_nodes, 2)
        )

        if longest_edge <= 1e-12:
            continue

        quality = volume_six / (longest_edge ** 3)
        mean_distance = sum(
            (shell_vertex - cage_vertices[index]).length
            for index in candidate_nodes
        ) / 4.0
        normalized_distance = mean_distance / global_diagonal
        score = quality / (
            1.0
            + ATTACHMENT_DISTANCE_WEIGHT * normalized_distance
        )

        if score > best_score:
            best_score = score
            best_nodes = candidate_nodes

    if best_nodes is None:
        raise RuntimeError(
            "No non-coplanar local support tetrahedron for shell vertex "
            f"{tuple(shell_vertex)}."
        )

    return tuple(best_nodes)


def create_shell_attachments(
    shell_vertices,
    cage_vertices,
    station_nodes,
):
    minimum, maximum, diagonal = bounds(shell_vertices)
    y_span = maximum.y - minimum.y
    bay_count = len(station_nodes) - 1
    attachments = []

    for shell_index, shell_vertex in enumerate(shell_vertices):
        normalized_y = (shell_vertex.y - minimum.y) / y_span
        bay_index = int(normalized_y * bay_count)
        bay_index = max(0, min(bay_count - 1, bay_index))
        candidates = (
            tuple(station_nodes[bay_index])
            + tuple(station_nodes[bay_index + 1])
        )
        selected = choose_attachment_nodes(
            shell_vertex,
            candidates,
            cage_vertices,
            diagonal,
        )

        for cage_index in selected:
            attachments.append((shell_index, cage_index))

    return attachments


# ============================================================
# DEPENDENCY-FREE RIGIDITY VALIDATION
# ============================================================

def matrix_rank(matrix, column_count, tolerance=1e-9):
    # Complete pivoting avoids amplifying nearly dependent early rows into
    # spurious rigid-body constraints. No physical parameters are changed.
    rows = [row[:] for row in matrix]
    rank = 0
    scale = max((abs(v) for row in rows for v in row), default=0.0)
    while rank < min(len(rows), column_count):
        pivot_row, pivot_col = max(
            ((i, j) for i in range(rank, len(rows)) for j in range(rank, column_count)),
            key=lambda ij: abs(rows[ij[0]][ij[1]]))
        if abs(rows[pivot_row][pivot_col]) <= tolerance * max(1.0, scale):
            break
        rows[rank], rows[pivot_row] = rows[pivot_row], rows[rank]
        for row in rows:
            row[rank], row[pivot_col] = row[pivot_col], row[rank]
        pivot = rows[rank]
        for i in range(rank + 1, len(rows)):
            row = rows[i]
            factor = row[rank] / pivot[rank]
            row[rank] = 0.0
            if factor:
                for j in range(rank + 1, column_count):
                    row[j] -= factor * pivot[j]
        rank += 1
    return rank


def rigidity_report(node_positions, beam_edges):
    node_count = len(node_positions)
    column_count = node_count * 3
    matrix = []

    for first, second in beam_edges:
        delta = node_positions[first] - node_positions[second]
        length = delta.length

        if length <= 1e-10:
            continue

        direction = delta / length
        row = [0.0] * column_count
        row[first * 3:first * 3 + 3] = tuple(direction)
        row[second * 3:second * 3 + 3] = tuple(direction * -1.0)
        matrix.append(row)

    rank = matrix_rank(matrix, column_count)
    nullity = column_count - rank
    expected_rank = max(0, column_count - 6)

    return {
        "rank": rank,
        "nullity": nullity,
        "expected_rank": expected_rank,
        "extra_modes": max(0, nullity - 6),
        "valid_beams": len(matrix),
    }


def structural_graph(shell_vertices, cage_vertices, shell_edges, cage_edges, attachments):
    base = len(shell_vertices)
    edges = set(shell_edges)
    edges.update(tuple(sorted((base+a, base+b))) for a,b in cage_edges)
    edges.update((a, base+b) for a,b in attachments)
    return shell_vertices+cage_vertices, sorted(edges)


def stabilize_local_attachments(shell_vertices, cage_vertices, station_nodes, shell_edges, cage_edges, attachments):
    """Repair only missing constraints in adjacent scaffold bays, before calibration."""
    positions, edges = structural_graph(shell_vertices,cage_vertices,shell_edges,cage_edges,attachments)
    report = rigidity_report(positions, edges)
    if not report['extra_modes']:
        return report
    minimum, maximum, _ = bounds(shell_vertices)
    bay_count = len(station_nodes)-1
    existing = set(attachments)
    candidates = []
    for i, vertex in enumerate(shell_vertices):
        bay = max(0, min(bay_count-1, int((vertex.y-minimum.y)/(maximum.y-minimum.y)*bay_count)))
        for j in station_nodes[bay]+station_nodes[bay+1]:
            if (i,j) not in existing:
                candidates.append(((vertex-cage_vertices[j]).length,i,j))
    for _, i, j in sorted(candidates):
        candidate = edges+[(i,len(shell_vertices)+j)]
        updated = rigidity_report(positions,candidate)
        if updated['rank'] <= report['rank']:
            continue
        attachments.append((i,j)); edges=candidate; report=updated
        if not report['extra_modes']:
            break
    if report['extra_modes']:
        raise RuntimeError(f"Generated graph retains {report['extra_modes']} internal motions after local stabilization. "
                           "Adjust hull resolution or selection; see the generation log and source hull.")
    attachments.sort()
    return report


def aligned_reference_nodes(shell_vertices, shell_ids, cage_vertices, cage_ids, station_nodes, cage_edges, attachments):
    """Use exact axis-aligned refnodes; new helpers get three independent constraints."""
    middle = len(station_nodes)//2
    reference = cage_vertices[station_nodes[middle][1]]
    back_y = cage_vertices[station_nodes[min(middle+1,len(station_nodes)-1)][1]].y
    minimum, maximum, diagonal = bounds(shell_vertices)
    targets = [reference, Vec3(reference.x,back_y,reference.z),
               cage_vertices[station_nodes[middle][0]],
               Vec3(reference.x,reference.y,minimum.z+.72*(maximum.z-minimum.z))]
    result = []
    for label, target in zip(('ref','back','left','up'),targets):
        positions = shell_vertices+cage_vertices
        names = shell_ids+cage_ids
        match = next((i for i,p in enumerate(positions) if (p-target).length <= diagonal*1e-10),None)
        if match is not None:
            result.append(names[match]); continue
        # Greedy nearest independent directions yield a full-rank three-row
        # attachment block for this added node without moving the existing graph.
        basis = []; neighbors = []
        for i in sorted(range(len(positions)), key=lambda i: ((positions[i]-target).length,i)):
            delta = positions[i]-target
            if delta.length <= diagonal*1e-10: continue
            vector = delta/delta.length
            for unit in basis: vector = vector-unit*vector.dot(unit)
            if vector.length <= 1e-7: continue
            basis.append(vector/vector.length);neighbors.append(i)
            if len(neighbors)==3: break
        if len(neighbors)!=3: raise RuntimeError("Cannot constrain aligned reference node "+label)
        index=len(cage_vertices);cage_vertices.append(target);cage_ids.append('axis_'+label)
        for neighbor in neighbors:
            if neighbor < len(shell_vertices): attachments.append((neighbor,index))
            else: cage_edges.append(tuple(sorted((neighbor-len(shell_vertices),index))))
        result.append(cage_ids[index])
    ref,back,left,up = targets
    if back.y<=ref.y or left.x<=ref.x or up.z<=ref.z:
        raise RuntimeError("Reference nodes do not define the BeamNG left/back/up directions")
    return tuple(result)


# ============================================================
# JBEAM WRITING
# ============================================================

def export_coordinate(coordinate):
    offset = Vec3(*EXPORT_OFFSET)
    transformed = (coordinate + offset) * EXPORT_SCALE

    return (
        transformed.x * EXPORT_AXIS_SIGN[0],
        transformed.y * EXPORT_AXIS_SIGN[1],
        transformed.z * EXPORT_AXIS_SIGN[2],
    )


def number(value):
    return f"{float(value):.9g}"


def jbeam_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, str):
        return json.dumps(value)

    return number(value)


def property_row(**properties):
    entries = ", ".join(
        f"{json.dumps(key)}:{jbeam_value(value)}"
        for key, value in properties.items()
    )
    return "        {" + entries + "}"


def write_jbeam(
    filepath,
    source_path,
    shell_vertices,
    shell_ids,
    triangles,
    shell_edges,
    cage_vertices,
    cage_ids,
    station_nodes,
    cage_edges,
    attachments,
    report,
    reference_nodes=None,
):
    path = Path(filepath).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if reference_nodes is None:
        raise ValueError("Axis-aligned reference nodes must be generated before writing JBeam")
    ref_id, back_id, left_id, up_id = reference_nodes
    front_station = station_nodes[0]

    lines = []
    add = lines.append
    add("{\n")
    add(f"  {json.dumps(PART_NAME)}: {{\n")
    add("    \"information\": {\n")
    add("      \"authors\": \"Generated by JBeamShellGenerator.py\",\n")
    add(f"      \"name\": {json.dumps(PART_DISPLAY_NAME)},\n")
    add("      \"value\": 15000\n")
    add("    },\n")
    add(f"    \"slotType\": {json.dumps(SLOT_TYPE)},\n")
    add("    \"refNodes\": [\n")
    add("      [\"ref:\", \"back:\", \"left:\", \"up:\", \"leftCorner:\", \"rightCorner:\"],\n")
    add(
        "      ["
        + ", ".join(json.dumps(item) for item in (
            ref_id,
            back_id,
            left_id,
            up_id,
            cage_ids[front_station[0]],
            cage_ids[front_station[1]],
        ))
        + "]\n"
    )
    add("    ],\n")

    add("    \"nodes\": [\n")
    add("      [\"id\", \"posX\", \"posY\", \"posZ\"],\n")
    add(property_row(
        nodeWeight=SHELL_NODE_WEIGHT,
        collision=True,
        selfCollision=True,
        nodeMaterial="|NM_METAL",
        group=SHELL_GROUP,
    ) + ",\n")

    for node_id, coordinate in zip(shell_ids, shell_vertices):
        x, y, z = export_coordinate(coordinate)
        add(
            f"      [{json.dumps(node_id)}, {number(x)}, "
            f"{number(y)}, {number(z)}],\n"
        )

    add(property_row(
        nodeWeight=CAGE_NODE_WEIGHT,
        collision=False,
        selfCollision=False,
        nodeMaterial="|NM_METAL",
        group=CAGE_GROUP,
    ) + ",\n")

    for node_index, (node_id, coordinate) in enumerate(
        zip(cage_ids, cage_vertices)
    ):
        x, y, z = export_coordinate(coordinate)
        comma = "," if node_index < len(cage_ids) - 1 else ""
        add(
            f"      [{json.dumps(node_id)}, {number(x)}, "
            f"{number(y)}, {number(z)}]{comma}\n"
        )

    add("    ],\n")
    add("    \"beams\": [\n")
    add("      [\"id1:\", \"id2:\"],\n")
    add("      // Triangulated outer shell\n")
    add(property_row(
        beamSpring=SHELL_BEAM_SPRING,
        beamDamp=SHELL_BEAM_DAMP,
        beamDeform=SHELL_BEAM_DEFORM,
        beamStrength=SHELL_BEAM_STRENGTH,
    ) + ",\n")

    beam_lines = []

    for first, second in shell_edges:
        beam_lines.append(
            f"      [{json.dumps(shell_ids[first])}, "
            f"{json.dumps(shell_ids[second])}]"
        )

    beam_lines.append("      // Sparse deformable bottom support scaffold")
    beam_lines.append(property_row(
        beamSpring=CAGE_BEAM_SPRING,
        beamDamp=CAGE_BEAM_DAMP,
        beamDeform=CAGE_BEAM_DEFORM,
        beamStrength=CAGE_BEAM_STRENGTH,
    ))

    for first, second in cage_edges:
        beam_lines.append(
            f"      [{json.dumps(cage_ids[first])}, "
            f"{json.dumps(cage_ids[second])}]"
        )

    beam_lines.append("      // Local shell-to-support attachments, including rank repairs")
    beam_lines.append(property_row(
        beamSpring=TETHER_BEAM_SPRING,
        beamDamp=TETHER_BEAM_DAMP,
        beamDeform=TETHER_BEAM_DEFORM,
        beamStrength=TETHER_BEAM_STRENGTH,
    ))

    for shell_index, cage_index in attachments:
        beam_lines.append(
            f"      [{json.dumps(shell_ids[shell_index])}, "
            f"{json.dumps(cage_ids[cage_index])}]"
        )

    data_indices = [
        index
        for index, line in enumerate(beam_lines)
        if not line.lstrip().startswith("//")
    ]
    last_data_index = data_indices[-1]

    for index, line in enumerate(beam_lines):
        comma = "," if index in data_indices and index != last_data_index else ""
        add(line + comma + "\n")

    add("    ],\n")
    add("    \"triangles\": [\n")
    add("      [\"id1:\", \"id2:\", \"id3:\"],\n")
    add(property_row(
        dragCoef=TRIANGLE_DRAG_COEF,
        groundModel="metal",
        triangleType="NORMALTYPE",
    ) + ",\n")

    for triangle_index, (first, second, third) in enumerate(triangles):
        comma = "," if triangle_index < len(triangles) - 1 else ""
        add(
            f"      [{json.dumps(shell_ids[first])}, "
            f"{json.dumps(shell_ids[second])}, "
            f"{json.dumps(shell_ids[third])}]{comma}\n"
        )

    add("    ],\n")
    add("    \"generatorData\": {\n")
    add(f"      \"sourceMesh\": {json.dumps(Path(source_path).name)},\n")
    add(f"      \"shellNodes\": {len(shell_ids)},\n")
    add(f"      \"internalSupportNodes\": {len(cage_ids)},\n")
    add(f"      \"rigidityRank\": {report['rank']},\n")
    add(f"      \"rigidityNullity\": {report['nullity']},\n")
    add(f"      \"extraInternalModes\": {report['extra_modes']}\n")
    add("    }\n")
    add("  }\n")
    add("}\n")

    with path.open("w", encoding="utf-8", newline="\n") as file:
        file.writelines(lines)

    return path


# ============================================================
# MAIN
# ============================================================

def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Convert an evaluated wrapped-shell OFF mesh into a "
            "rigidified BeamNG JBeam."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=str(DEFAULT_SOURCE_MESH),
        help="Input wrapped shell OFF mesh.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_OUTPUT_JBEAM),
        help="Output JBeam path.",
    )
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    source_path = Path(arguments.source).resolve()
    output_path = Path(arguments.output).resolve()

    print()
    print("=" * 70)
    print("WRAPPED OFF SHELL -> RIGIDIFIED JBEAM")
    print("=" * 70)

    shell_vertices, triangles = read_off(source_path)
    shell_ids = [
        f"sh{index:04d}"
        for index in range(len(shell_vertices))
    ]
    shell_edges = triangle_edges(triangles)

    (
        cage_vertices,
        cage_ids,
        station_nodes,
        cage_edges,
    ) = create_sparse_bottom_supports(shell_vertices)

    attachments = create_shell_attachments(
        shell_vertices,
        cage_vertices,
        station_nodes,
    )

    stabilize_local_attachments(shell_vertices,cage_vertices,station_nodes,shell_edges,cage_edges,attachments)
    reference_nodes = aligned_reference_nodes(shell_vertices,shell_ids,cage_vertices,cage_ids,station_nodes,cage_edges,attachments)
    all_positions, structural_edges = structural_graph(shell_vertices,cage_vertices,shell_edges,cage_edges,attachments)
    report = rigidity_report(all_positions, structural_edges)
    if report['extra_modes'] or report['nullity'] != 6:
        raise RuntimeError("Aligned graph failed final rigidity validation: " + str(report))

    written_path = write_jbeam(
        output_path,
        source_path,
        shell_vertices,
        shell_ids,
        triangles,
        shell_edges,
        cage_vertices,
        cage_ids,
        station_nodes,
        cage_edges,
        attachments,
        report,
        reference_nodes,
    )

    print(f"Source mesh:         {source_path}")
    print(f"Shell nodes:         {len(shell_vertices):,}")
    print(f"Collision triangles: {len(triangles):,}")
    print(f"Shell beams:         {len(shell_edges):,}")
    print(f"Support nodes:       {len(cage_vertices):,}")
    print(f"Support beams:       {len(cage_edges):,}")
    print(f"Attachment beams:    {len(attachments):,}")
    print(f"Rigidity rank:       {report['rank']:,}")
    print(f"Expected rank:       {report['expected_rank']:,}")
    print(f"Nullity:             {report['nullity']:,}")
    print(f"Extra internal DOF:  {report['extra_modes']:,}")
    print(f"JBeam written to:    {written_path}")

    if report["extra_modes"]:
        raise RuntimeError(
            "The generated structure still has internal mechanisms."
        )

    if report["nullity"] != 6:
        raise RuntimeError(
            "Unexpected rigidity result: a free rigid structure must "
            "have exactly six global modes."
        )

    print()
    print("PASS: only the six global rigid-body modes remain.")
    print("=" * 70)


if __name__ == "__main__":
    main()
