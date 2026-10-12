import bpy
import os
import subprocess
import tempfile
from collections import deque
from pathlib import Path
from mathutils import Vector


# ============================================================
# SETTINGS
# ============================================================

# Leave "" to use currently selected mesh objects.
FRAME_FILE = r"H:\beamng project programs\mochi blender work\frame.stl"

# Optional explicit external Python executable containing CGAL.
# Leave blank to use:
#
#     py -3.11
#
CGAL_PYTHON = r""


# ============================================================
# OUTPUT OBJECTS
# ============================================================

PRUNING_PROXY_NAME = "CGAL_PRUNING_PROXY"
FRAME_TARGET_NAME = "FRAME_SHRINK_TARGET"
SYMMETRY_PLANE_NAME = "GRID_SYMMETRY_PLANE"
GRID_NAME = "GRID_HULL"

# Standalone JBeamShellGenerator.py reads this evaluated mesh. The
# export includes Shrinkwrap, Mirror, and Weld even when those modifiers
# remain unapplied in Blender.
EXPORT_WRAPPED_HULL_OFF = True
WRAPPED_HULL_OFF_FILENAME = "mochi_hull.off"

# The proxy is useful for checking which volume the voxel flood
# fill treats as closed. It is not the Shrinkwrap target.
CREATE_PROXY_DEBUG_OBJECT = True
HIDE_FRAME_TARGET = True


# ============================================================
# COARSE SHRINKWRAP GRID
# ============================================================

GRID_I = 3      # X width
GRID_J = 5      # Z height
GRID_K = 7      # Y length

GRID_SHRINK_OFFSET = 0.01

# Applied after Shrinkwrap. Increase cautiously if narrow sliver
# faces remain; reduce it if intentional corners begin merging.
GRID_WELD_DISTANCE = 0.15

# Uses the X center of the full frame bounds. With symmetry
# enabled, GRID_I must be odd so a lattice plane lies exactly on
# the vehicle centerline. Toggle BISECT_FLIP to use the opposite
# source half if one side of the frame gives a cleaner fit.
ENFORCE_X_SYMMETRY = True
SYMMETRY_BISECT_FLIP = False
SYMMETRY_MERGE_DISTANCE = 0.0001

APPLY_SHRINKWRAP = False

HIDE_SOURCE_FRAME = False
DELETE_PREVIOUS = True


# ============================================================
# CGAL PRUNING PROXY
# ============================================================

# The single watertight proxy is used only for voxel/surface
# intersection and outside flood-fill classification. The final
# GRID_HULL shrinkwraps directly to FRAME_SHRINK_TARGET, which is
# built from the original evaluated frame triangle soup.
#
# alpha is calculated using the FULL CAR bounding-box diagonal:
#
#       alpha = full_car_diagonal / divisor
#
PRUNING_PROXY_DIVISOR = 7.0
PRUNING_PROXY_OFFSET_RATIO = 100.0


# ============================================================
# OBJECT HELPERS
# ============================================================

def delete_object(name):
    obj = bpy.data.objects.get(name)

    if obj is None:
        return

    mesh = obj.data if obj.type == "MESH" else None

    bpy.data.objects.remove(
        obj,
        do_unlink=True,
    )

    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def delete_objects_with_prefix(prefix):
    names = [
        obj.name
        for obj in bpy.data.objects
        if obj.name.startswith(prefix)
    ]

    for name in names:
        delete_object(name)


def select_only(objects):
    bpy.ops.object.select_all(
        action="DESELECT"
    )

    for obj in objects:
        obj.select_set(True)

    if objects:
        bpy.context.view_layer.objects.active = objects[0]


# ============================================================
# FRAME IMPORT
# ============================================================

def import_mesh_file(filepath):
    filepath = os.path.abspath(filepath)

    if not os.path.isfile(filepath):
        raise FileNotFoundError(filepath)

    suffix = Path(filepath).suffix.lower()

    before = set(bpy.data.objects)

    bpy.ops.object.select_all(
        action="DESELECT"
    )

    if suffix == ".stl":

        try:
            bpy.ops.wm.stl_import(
                filepath=filepath
            )

        except Exception:
            bpy.ops.import_mesh.stl(
                filepath=filepath
            )

    elif suffix == ".obj":

        try:
            bpy.ops.wm.obj_import(
                filepath=filepath
            )

        except Exception:
            bpy.ops.import_scene.obj(
                filepath=filepath
            )

    elif suffix == ".ply":

        try:
            bpy.ops.wm.ply_import(
                filepath=filepath
            )

        except Exception:
            bpy.ops.import_mesh.ply(
                filepath=filepath
            )

    elif suffix == ".fbx":

        bpy.ops.import_scene.fbx(
            filepath=filepath
        )

    elif suffix in {".glb", ".gltf"}:

        bpy.ops.import_scene.gltf(
            filepath=filepath
        )

    else:
        raise ValueError(
            "Unsupported frame type.\n"
            "Use STL, OBJ, PLY, FBX, GLB or GLTF."
        )

    after = set(bpy.data.objects)

    imported = [
        obj
        for obj in after - before
        if obj.type == "MESH"
    ]

    if not imported:
        raise RuntimeError(
            "No mesh objects were imported."
        )

    return imported


def get_frame_objects():

    if FRAME_FILE.strip():

        objects = import_mesh_file(
            FRAME_FILE
        )

    else:

        objects = [
            obj
            for obj in bpy.context.selected_objects
            if obj.type == "MESH"
        ]

        if not objects:

            raise RuntimeError(
                "FRAME_FILE is blank and "
                "no mesh objects are selected."
            )

    return objects


# ============================================================
# BLENDER -> TRIANGLE SOUP
# ============================================================

def collect_triangle_soup(objects):

    depsgraph = (
        bpy.context.evaluated_depsgraph_get()
    )

    vertices = []
    triangles = []

    for source in objects:

        evaluated = source.evaluated_get(
            depsgraph
        )

        mesh = evaluated.to_mesh()

        try:

            mesh.calc_loop_triangles()

            base = len(vertices)
            matrix = evaluated.matrix_world

            for vertex in mesh.vertices:

                vertices.append(
                    (matrix @ vertex.co).copy()
                )

            for tri in mesh.loop_triangles:

                a = base + tri.vertices[0]
                b = base + tri.vertices[1]
                c = base + tri.vertices[2]

                va = vertices[a]
                vb = vertices[b]
                vc = vertices[c]

                # Ignore degenerate triangles.
                if (
                    (vb - va)
                    .cross(vc - va)
                    .length
                    > 1e-12
                ):

                    triangles.append(
                        (a, b, c)
                    )

        finally:

            evaluated.to_mesh_clear()

    if not vertices or not triangles:

        raise RuntimeError(
            "No usable triangle geometry found."
        )

    print(
        f"Source: {len(vertices):,} verts, "
        f"{len(triangles):,} triangles"
    )

    return vertices, triangles


# ============================================================
# GLOBAL FRAME BOUNDS
# ============================================================

def calculate_bounds(vertices):

    minimum = Vector((
        min(v.x for v in vertices),
        min(v.y for v in vertices),
        min(v.z for v in vertices),
    ))

    maximum = Vector((
        max(v.x for v in vertices),
        max(v.y for v in vertices),
        max(v.z for v in vertices),
    ))

    diagonal = (
        maximum - minimum
    ).length

    if diagonal <= 0:

        raise RuntimeError(
            "Zero-size frame bounding box."
        )

    return minimum, maximum, diagonal


# ============================================================
# OFF FILES
# ============================================================

def write_off(
    filepath,
    vertices,
    faces,
):

    with open(
        filepath,
        "w",
        encoding="utf-8",
    ) as file:

        file.write("OFF\n")

        file.write(
            f"{len(vertices)} "
            f"{len(faces)} "
            f"0\n"
        )

        for v in vertices:

            file.write(
                f"{float(v[0]):.17g} "
                f"{float(v[1]):.17g} "
                f"{float(v[2]):.17g}\n"
            )

        for face in faces:

            file.write(
                str(len(face))
                + " "
                + " ".join(
                    str(int(i))
                    for i in face
                )
                + "\n"
            )


def read_off(filepath):

    tokens = []

    with open(
        filepath,
        "r",
        encoding="utf-8",
    ) as file:

        for line in file:

            line = (
                line
                .split("#", 1)[0]
                .strip()
            )

            if line:
                tokens.extend(
                    line.split()
                )

    if not tokens or tokens[0] != "OFF":

        raise RuntimeError(
            "Invalid OFF file."
        )

    cursor = 1

    nv = int(tokens[cursor])
    nf = int(tokens[cursor + 1])

    cursor += 3

    vertices = []

    for _ in range(nv):

        vertices.append((
            float(tokens[cursor]),
            float(tokens[cursor + 1]),
            float(tokens[cursor + 2]),
        ))

        cursor += 3

    faces = []

    for _ in range(nf):

        count = int(tokens[cursor])

        cursor += 1

        face = tuple(
            int(tokens[cursor + i])
            for i in range(count)
        )

        cursor += count

        if len(face) >= 3:
            faces.append(face)

    return vertices, faces


# ============================================================
# EXTERNAL PYTHON
# ============================================================

def external_python_command():

    if CGAL_PYTHON.strip():

        if not os.path.isfile(
            CGAL_PYTHON
        ):

            raise RuntimeError(
                "CGAL_PYTHON does not exist:\n"
                + CGAL_PYTHON
            )

        return [CGAL_PYTHON]

    return [
        "py",
        "-3.11",
    ]


def check_external_cgal():

    command = (
        external_python_command()
        + [
            "-c",
            (
                "import sys; "
                "import CGAL; "
                "print(sys.executable); "
                "print(sys.version)"
            ),
        ]
    )

    print()
    print(
        "Checking external CGAL environment..."
    )

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "External Python 3.11 "
            "could not import CGAL.\n\n"
            "Run this in PowerShell first:\n\n"
            "    py -3.11 -m pip install cgal\n\n"
            "STDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )

    print(result.stdout)


# ============================================================
# CGAL HELPER SCRIPT
# ============================================================

CGAL_HELPER = r'''
import sys
import traceback


def read_off(path):

    tokens = []

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        for line in file:

            line = (
                line
                .split("#", 1)[0]
                .strip()
            )

            if line:
                tokens.extend(
                    line.split()
                )

    if not tokens or tokens[0] != "OFF":

        raise RuntimeError(
            "Input is not OFF."
        )

    p = 1

    nv = int(tokens[p])
    nf = int(tokens[p + 1])

    p += 3

    vertices = []

    for _ in range(nv):

        vertices.append((
            float(tokens[p]),
            float(tokens[p + 1]),
            float(tokens[p + 2]),
        ))

        p += 3

    faces = []

    for _ in range(nf):

        n = int(tokens[p])

        p += 1

        face = [
            int(tokens[p + i])
            for i in range(n)
        ]

        p += n

        faces.append(face)

    return vertices, faces


def main():

    input_file = sys.argv[1]
    output_file = sys.argv[2]
    alpha = float(sys.argv[3])
    offset = float(sys.argv[4])

    print(
        "Importing CGAL...",
        flush=True,
    )

    from CGAL import CGAL_Alpha_wrap_3

    from CGAL.CGAL_Alpha_wrap_3 import (
        Point_3_Vector,
        Polygon_Vector,
        Int_Vector,
    )

    from CGAL.CGAL_Polyhedron_3 import (
        Polyhedron_3
    )

    from CGAL.CGAL_Kernel import (
        Point_3
    )

    print(
        "Reading source mesh...",
        flush=True,
    )

    verts, faces = read_off(
        input_file
    )

    print(
        "Input:",
        len(verts),
        "vertices,",
        len(faces),
        "faces",
        flush=True,
    )

    points = Point_3_Vector()
    points.reserve(
        len(verts)
    )

    for x, y, z in verts:

        points.append(
            Point_3(
                x,
                y,
                z,
            )
        )

    polygons = Polygon_Vector()
    polygons.reserve(
        len(faces)
    )

    for face in faces:

        polygon = Int_Vector()

        polygon.reserve(
            len(face)
        )

        for index in face:
            polygon.append(
                index
            )

        polygons.append(
            polygon
        )

    result = Polyhedron_3()

    print(
        "Running alpha wrap:",
        "alpha =",
        alpha,
        "offset =",
        offset,
        flush=True,
    )

    CGAL_Alpha_wrap_3.alpha_wrap_3(
        points,
        polygons,
        alpha,
        offset,
        result,
    )

    print(
        "Writing result...",
        flush=True,
    )

    result.write_to_file(
        output_file
    )

    print(
        "DONE",
        flush=True,
    )


if __name__ == "__main__":

    try:
        main()

    except Exception:

        traceback.print_exc()
        sys.exit(1)
'''


# ============================================================
# RUN CGAL OUTSIDE BLENDER
# ============================================================

def run_external_alpha_wrap(
    vertices,
    triangles,
    alpha,
    offset,
    label,
):

    workdir = tempfile.mkdtemp(
        prefix=(
            "blender_alpha_wrap_"
            + label
            + "_"
        )
    )

    source_off = os.path.join(
        workdir,
        "frame_source.off",
    )

    result_off = os.path.join(
        workdir,
        "frame_alpha_wrap.off",
    )

    helper_py = os.path.join(
        workdir,
        "run_cgal_alpha_wrap.py",
    )

    write_off(
        source_off,
        vertices,
        triangles,
    )

    with open(
        helper_py,
        "w",
        encoding="utf-8",
    ) as file:

        file.write(
            CGAL_HELPER
        )

    command = (
        external_python_command()
        + [
            helper_py,
            source_off,
            result_off,
            repr(alpha),
            repr(offset),
        ]
    )

    print()
    print(
        f"Launching CGAL for {label}"
    )

    print(
        " ".join(command)
    )

    print()

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    print("CGAL STDOUT:")
    print(result.stdout)

    if result.stderr:

        print("CGAL STDERR:")
        print(result.stderr)

    if result.returncode != 0:

        raise RuntimeError(
            "\nCGAL helper process failed or crashed.\n\n"
            f"Region/wrap: {label}\n"
            f"Return code: {result.returncode}\n\n"
            "Temporary files were left here:\n"
            f"{workdir}\n\n"
            "STDOUT:\n"
            f"{result.stdout}\n\n"
            "STDERR:\n"
            f"{result.stderr}"
        )

    if not os.path.isfile(result_off):

        raise RuntimeError(
            "CGAL exited successfully "
            "but produced no output OFF."
        )

    return read_off(
        result_off
    )


# ============================================================
# CREATE BLENDER OBJECT
# ============================================================

def make_mesh_object(
    name,
    vertices,
    faces,
):

    mesh = bpy.data.meshes.new(
        name + "_MESH"
    )

    mesh.from_pydata(
        vertices,
        [],
        faces,
    )

    mesh.update()

    obj = bpy.data.objects.new(
        name,
        mesh,
    )

    bpy.context.collection.objects.link(
        obj
    )

    # Keep target visibly faceted while tuning.
    for poly in mesh.polygons:
        poly.use_smooth = False

    return obj


# ============================================================
# SINGLE CGAL PRUNING PROXY
# ============================================================

def create_pruning_proxy(
    source_vertices,
    source_triangles,
    global_diagonal,
):

    divisor = float(
        PRUNING_PROXY_DIVISOR
    )

    offset_ratio = float(
        PRUNING_PROXY_OFFSET_RATIO
    )

    if divisor <= 0:
        raise ValueError(
            "PRUNING_PROXY_DIVISOR must be > 0."
        )

    if offset_ratio <= 0:
        raise ValueError(
            "PRUNING_PROXY_OFFSET_RATIO must be > 0."
        )

    alpha = (
        global_diagonal
        / divisor
    )

    offset = (
        alpha
        / offset_ratio
    )

    print()
    print("=" * 70)
    print("SINGLE CGAL PRUNING PROXY")
    print("=" * 70)
    print(
        "  divisor =",
        divisor,
    )
    print(
        "  alpha   =",
        alpha,
    )
    print(
        "  offset  =",
        offset,
    )

    proxy_vertices, proxy_faces = (
        run_external_alpha_wrap(
            source_vertices,
            source_triangles,
            alpha,
            offset,
            "pruning_proxy",
        )
    )

    proxy_obj = None

    if CREATE_PROXY_DEBUG_OBJECT:

        delete_object(
            PRUNING_PROXY_NAME
        )

        proxy_obj = make_mesh_object(
            PRUNING_PROXY_NAME,
            proxy_vertices,
            proxy_faces,
        )

        proxy_obj.show_in_front = True

    return (
        proxy_obj,
        proxy_vertices,
        proxy_faces,
    )


# ============================================================
# TRIANGLE / VOXEL INTERSECTION
# ============================================================

def triangulate_polygon_mesh(
    vertices,
    faces,
):

    vector_vertices = [
        Vector(vertex)
        for vertex in vertices
    ]

    triangles = []

    for face in faces:

        if len(face) < 3:
            continue

        first = vector_vertices[
            face[0]
        ]

        for corner in range(
            1,
            len(face) - 1,
        ):

            triangle = (
                first,
                vector_vertices[face[corner]],
                vector_vertices[face[corner + 1]],
            )

            edge_a = (
                triangle[1]
                - triangle[0]
            )

            edge_b = (
                triangle[2]
                - triangle[0]
            )

            if edge_a.cross(edge_b).length <= 1e-12:
                continue

            triangle_min = Vector((
                min(point.x for point in triangle),
                min(point.y for point in triangle),
                min(point.z for point in triangle),
            ))

            triangle_max = Vector((
                max(point.x for point in triangle),
                max(point.y for point in triangle),
                max(point.z for point in triangle),
            ))

            triangles.append((
                triangle,
                triangle_min,
                triangle_max,
            ))

    return triangles


def projections_are_separate(
    axis,
    triangle,
    box_half_size,
):

    if axis.length_squared <= 1e-24:
        return False

    projections = [
        point.dot(axis)
        for point in triangle
    ]

    radius = (
        box_half_size.x * abs(axis.x)
        + box_half_size.y * abs(axis.y)
        + box_half_size.z * abs(axis.z)
    )

    epsilon = 1e-10

    return (
        min(projections) > radius + epsilon
        or max(projections) < -radius - epsilon
    )


def triangle_intersects_box(
    triangle_record,
    box_min,
    box_max,
):

    (
        triangle,
        triangle_min,
        triangle_max,
    ) = triangle_record

    # Cheap bounding-box rejection before the SAT tests.
    if (
        triangle_max.x < box_min.x
        or triangle_min.x > box_max.x
        or triangle_max.y < box_min.y
        or triangle_min.y > box_max.y
        or triangle_max.z < box_min.z
        or triangle_min.z > box_max.z
    ):
        return False

    box_center = (
        box_min + box_max
    ) * 0.5

    box_half_size = (
        box_max - box_min
    ) * 0.5

    local_triangle = tuple(
        point - box_center
        for point in triangle
    )

    edges = (
        local_triangle[1] - local_triangle[0],
        local_triangle[2] - local_triangle[1],
        local_triangle[0] - local_triangle[2],
    )

    box_axes = (
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, 0.0, 1.0)),
    )

    triangle_normal = (
        edges[0].cross(edges[1])
    )

    test_axes = [
        *box_axes,
        triangle_normal,
    ]

    for edge in edges:
        for box_axis in box_axes:
            test_axes.append(
                edge.cross(box_axis)
            )

    for axis in test_axes:

        if projections_are_separate(
            axis,
            local_triangle,
            box_half_size,
        ):
            return False

    return True


def box_intersects_proxy(
    box_min,
    box_max,
    proxy_triangles,
):

    return any(
        triangle_intersects_box(
            triangle,
            box_min,
            box_max,
        )
        for triangle in proxy_triangles
    )


# ============================================================
# OUTSIDE-PRUNED VOXEL SURFACE
# ============================================================

def create_pruned_voxel_grid(
    proxy_vertices,
    proxy_faces,
    i,
    j,
    k,
    name,
    symmetry_center_x,
):

    if i < 2 or j < 2 or k < 2:
        raise ValueError(
            "GRID_I, GRID_J and GRID_K "
            "must all be >= 2."
        )

    if ENFORCE_X_SYMMETRY and i % 2 == 0:
        raise ValueError(
            "GRID_I must be odd when "
            "ENFORCE_X_SYMMETRY is True."
        )

    proxy_vectors = [
        Vector(vertex)
        for vertex in proxy_vertices
    ]

    proxy_min, proxy_max, _ = calculate_bounds(
        proxy_vectors
    )

    if ENFORCE_X_SYMMETRY:

        # Ensure the odd X lattice has a plane exactly at the
        # requested vehicle center while still enclosing the
        # complete (possibly slightly asymmetric) CGAL proxy.
        x_half_extent = max(
            symmetry_center_x - proxy_min.x,
            proxy_max.x - symmetry_center_x,
        )

        proxy_min.x = (
            symmetry_center_x
            - x_half_extent
        )

        proxy_max.x = (
            symmetry_center_x
            + x_half_extent
        )

    step = Vector((
        (proxy_max.x - proxy_min.x) / (i - 1),
        (proxy_max.y - proxy_min.y) / (k - 1),
        (proxy_max.z - proxy_min.z) / (j - 1),
    ))

    proxy_triangles = triangulate_polygon_mesh(
        proxy_vertices,
        proxy_faces,
    )

    cells = {
        (ix, iy, iz)
        for ix in range(i - 1)
        for iy in range(k - 1)
        for iz in range(j - 1)
    }

    intersecting_cells = set()

    def lattice_coordinate(
        ix,
        iy,
        iz,
    ):

        return Vector((
            proxy_min.x + ix * step.x,
            proxy_min.y + iy * step.y,
            proxy_min.z + iz * step.z,
        ))

    for cell in cells:

        ix, iy, iz = cell

        box_min = lattice_coordinate(
            ix,
            iy,
            iz,
        )

        box_max = lattice_coordinate(
            ix + 1,
            iy + 1,
            iz + 1,
        )

        if box_intersects_proxy(
            box_min,
            box_max,
            proxy_triangles,
        ):
            intersecting_cells.add(cell)

    neighbor_directions = (
        (-1, 0, 0),
        (1, 0, 0),
        (0, -1, 0),
        (0, 1, 0),
        (0, 0, -1),
        (0, 0, 1),
    )

    def is_boundary_cell(cell):

        ix, iy, iz = cell

        return (
            ix == 0
            or ix == i - 2
            or iy == 0
            or iy == k - 2
            or iz == 0
            or iz == j - 2
        )

    outside_empty_cells = {
        cell
        for cell in cells
        if is_boundary_cell(cell)
        and cell not in intersecting_cells
    }

    flood_queue = deque(
        outside_empty_cells
    )

    while flood_queue:

        cell = flood_queue.popleft()

        for dx, dy, dz in neighbor_directions:

            neighbor = (
                cell[0] + dx,
                cell[1] + dy,
                cell[2] + dz,
            )

            if (
                neighbor in cells
                and neighbor not in intersecting_cells
                and neighbor not in outside_empty_cells
            ):
                outside_empty_cells.add(
                    neighbor
                )
                flood_queue.append(
                    neighbor
                )

    retained_cells = (
        cells
        - outside_empty_cells
    )

    enclosed_empty_cells = (
        retained_cells
        - intersecting_cells
    )

    if not retained_cells:
        raise RuntimeError(
            "Voxel pruning removed every cell."
        )

    vertices = []
    vertex_indices = {}
    faces = []

    def add_lattice_vertex(key):

        if key in vertex_indices:
            return vertex_indices[key]

        index = len(vertices)

        vertices.append(
            tuple(lattice_coordinate(*key))
        )

        vertex_indices[key] = index

        return index

    surface_definitions = (
        (
            (-1, 0, 0),
            ((0, 0, 0), (0, 0, 1),
             (0, 1, 1), (0, 1, 0)),
        ),
        (
            (1, 0, 0),
            ((1, 0, 0), (1, 1, 0),
             (1, 1, 1), (1, 0, 1)),
        ),
        (
            (0, -1, 0),
            ((0, 0, 0), (1, 0, 0),
             (1, 0, 1), (0, 0, 1)),
        ),
        (
            (0, 1, 0),
            ((0, 1, 0), (0, 1, 1),
             (1, 1, 1), (1, 1, 0)),
        ),
        (
            (0, 0, -1),
            ((0, 0, 0), (0, 1, 0),
             (1, 1, 0), (1, 0, 0)),
        ),
        (
            (0, 0, 1),
            ((0, 0, 1), (1, 0, 1),
             (1, 1, 1), (0, 1, 1)),
        ),
    )

    for cell in sorted(retained_cells):

        ix, iy, iz = cell

        for direction, corner_offsets in surface_definitions:

            neighbor = (
                ix + direction[0],
                iy + direction[1],
                iz + direction[2],
            )

            if neighbor in retained_cells:
                continue

            face = tuple(
                add_lattice_vertex((
                    ix + offset[0],
                    iy + offset[1],
                    iz + offset[2],
                ))
                for offset in corner_offsets
            )

            faces.append(face)

    delete_object(
        name
    )

    grid_obj = make_mesh_object(
        name,
        vertices,
        faces,
    )

    print()
    print("=" * 70)
    print("OUTSIDE-PRUNED VOXEL GRID")
    print("=" * 70)
    print(
        f"Total cells:              {len(cells):,}"
    )
    print(
        f"Proxy-intersecting cells: {len(intersecting_cells):,}"
    )
    print(
        f"Enclosed empty retained:  {len(enclosed_empty_cells):,}"
    )
    print(
        f"Outside empty removed:    {len(outside_empty_cells):,}"
    )
    print(
        f"Retained cells:           {len(retained_cells):,}"
    )
    print(
        f"Surface vertices:         {len(vertices):,}"
    )
    print(
        f"Surface faces:            {len(faces):,}"
    )

    return grid_obj


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print(
        "OUTSIDE-PRUNED DIRECT-FRAME SHRINKWRAP"
    )
    print("=" * 70)

    if ENFORCE_X_SYMMETRY and GRID_I % 2 == 0:
        raise ValueError(
            "GRID_I must be odd when "
            "ENFORCE_X_SYMMETRY is True."
        )

    # --------------------------------------------------------
    # Cleanup
    # --------------------------------------------------------

    if DELETE_PREVIOUS:

        delete_object(
            PRUNING_PROXY_NAME
        )

        delete_object(
            FRAME_TARGET_NAME
        )

        delete_object(
            GRID_NAME
        )

        delete_object(
            SYMMETRY_PLANE_NAME
        )

        # Remove outputs left by the obsolete piecewise-alpha
        # versions without touching the imported source frame.
        delete_object(
            "CAR_ALPHA_TOOL"
        )

        delete_object(
            "AW_DETAIL"
        )

        delete_objects_with_prefix(
            "AW_CLOSURE_"
        )

        delete_objects_with_prefix(
            "AW_REGION_"
        )

    # --------------------------------------------------------
    # Get source frame
    # --------------------------------------------------------

    source_objects = (
        get_frame_objects()
    )

    (
        vertices,
        triangles,
    ) = collect_triangle_soup(
        source_objects
    )

    (
        global_min,
        global_max,
        global_diagonal,
    ) = calculate_bounds(
        vertices
    )

    print()
    print("Full frame bounds:")

    print(
        "  minimum  =",
        global_min,
    )

    print(
        "  maximum  =",
        global_max,
    )

    print(
        "  diagonal =",
        global_diagonal,
    )

    symmetry_center_x = (
        global_min.x
        + global_max.x
    ) * 0.5

    # --------------------------------------------------------
    # Verify CGAL once.
    # --------------------------------------------------------

    check_external_cgal()

    # --------------------------------------------------------
    # Generate one watertight CGAL proxy used only for pruning.
    # --------------------------------------------------------

    (
        proxy_obj,
        proxy_vertices,
        proxy_faces,
    ) = create_pruning_proxy(
        vertices,
        triangles,
        global_diagonal,
    )

    # --------------------------------------------------------
    # Combined original-frame Shrinkwrap target.
    # --------------------------------------------------------

    delete_object(
        FRAME_TARGET_NAME
    )

    frame_target = make_mesh_object(
        FRAME_TARGET_NAME,
        vertices,
        triangles,
    )

    frame_target.hide_render = True
    frame_target.hide_set(
        HIDE_FRAME_TARGET
    )

    # --------------------------------------------------------
    # Remove only non-intersecting cells reachable from outside.
    # --------------------------------------------------------

    grid_obj = create_pruned_voxel_grid(
        proxy_vertices,
        proxy_faces,
        GRID_I,
        GRID_J,
        GRID_K,
        GRID_NAME,
        symmetry_center_x,
    )

    # --------------------------------------------------------
    # Shrinkwrap the pruned surface to the ORIGINAL frame.
    # --------------------------------------------------------

    shrinkwrap_modifier = grid_obj.modifiers.new(
        name="ShrinkwrapToOriginalFrame",
        type="SHRINKWRAP",
    )

    shrinkwrap_modifier.target = frame_target

    shrinkwrap_modifier.wrap_method = (
        "NEAREST_SURFACEPOINT"
    )

    shrinkwrap_modifier.offset = (
        GRID_SHRINK_OFFSET
    )

    # Bisect the evaluated Shrinkwrap result at the exact frame
    # center and mirror one half. This guarantees identical
    # topology and positions on both sides before the final Weld.
    if ENFORCE_X_SYMMETRY:

        symmetry_merge_distance = float(
            SYMMETRY_MERGE_DISTANCE
        )

        if symmetry_merge_distance < 0:
            raise ValueError(
                "SYMMETRY_MERGE_DISTANCE must be >= 0."
            )

        delete_object(
            SYMMETRY_PLANE_NAME
        )

        symmetry_plane = bpy.data.objects.new(
            SYMMETRY_PLANE_NAME,
            None,
        )

        bpy.context.collection.objects.link(
            symmetry_plane
        )

        symmetry_plane.location = (
            symmetry_center_x,
            0.0,
            0.0,
        )

        symmetry_plane.empty_display_type = (
            "PLAIN_AXES"
        )

        symmetry_plane.hide_render = True
        symmetry_plane.hide_set(True)

        mirror_modifier = grid_obj.modifiers.new(
            name="EnforceXSymmetry",
            type="MIRROR",
        )

        mirror_modifier.mirror_object = (
            symmetry_plane
        )

        mirror_modifier.use_axis[0] = True
        mirror_modifier.use_axis[1] = False
        mirror_modifier.use_axis[2] = False

        mirror_modifier.use_bisect_axis[0] = True
        mirror_modifier.use_bisect_axis[1] = False
        mirror_modifier.use_bisect_axis[2] = False

        mirror_modifier.use_bisect_flip_axis[0] = bool(
            SYMMETRY_BISECT_FLIP
        )

        mirror_modifier.use_clip = True
        mirror_modifier.use_mirror_merge = True
        mirror_modifier.merge_threshold = (
            symmetry_merge_distance
        )

    # Shrinkwrap can project neighboring grid vertices to nearly
    # identical positions, producing very thin faces. Keep Weld
    # last so it also cleans the center seam after Mirror.
    weld_distance = float(
        GRID_WELD_DISTANCE
    )

    if weld_distance < 0:
        raise ValueError(
            "GRID_WELD_DISTANCE must be >= 0."
        )

    weld_modifier = grid_obj.modifiers.new(
        name="MergeCloseShrinkwrapVertices",
        type="WELD",
    )

    weld_modifier.merge_threshold = (
        weld_distance
    )

    if APPLY_SHRINKWRAP:

        select_only([
            grid_obj
        ])

        bpy.context.view_layer.objects.active = (
            grid_obj
        )

        bpy.ops.object.modifier_apply(
            modifier=shrinkwrap_modifier.name
        )

    # --------------------------------------------------------
    # Export evaluated wrapped shell for standalone tools.
    # --------------------------------------------------------

    if EXPORT_WRAPPED_HULL_OFF:

        if not globals().get("WRAPPED_HULL_OUTPUT") and not bpy.data.filepath:
            raise RuntimeError(
                "Save the Blender file before exporting the wrapped "
                "hull OFF mesh."
            )

        (
            wrapped_vertices,
            wrapped_triangles,
        ) = collect_triangle_soup([grid_obj])

        wrapped_hull_path = (
            Path(globals()["WRAPPED_HULL_OUTPUT"]) if globals().get("WRAPPED_HULL_OUTPUT") else
            Path(bpy.data.filepath).parent / WRAPPED_HULL_OFF_FILENAME
        )

        write_off(
            str(wrapped_hull_path),
            wrapped_vertices,
            wrapped_triangles,
        )

        print(
            "Wrapped hull OFF:",
            wrapped_hull_path,
        )

    # --------------------------------------------------------
    # Visibility
    # --------------------------------------------------------

    if HIDE_SOURCE_FRAME:

        for obj in source_objects:
            obj.hide_set(True)

    select_only([
        grid_obj
    ])

    print()
    print("=" * 70)
    print("DONE")
    print("=" * 70)

    print(
        "Shrinkwrap target:",
        frame_target.name,
    )

    if proxy_obj is not None:
        print(
            "Pruning proxy:",
            proxy_obj.name,
        )

    print()
    print(
        "Tune PRUNING_PROXY_DIVISOR and the GRID dimensions "
        "at the top of the script."
    )


if __name__ == "__main__":
    main()
