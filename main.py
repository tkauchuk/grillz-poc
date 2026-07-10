"""
Grillz Design Platform — Single-Service POC
===========================================

FastAPI backend that performs the 3D geometric processing (trimesh) AND
serves the interactive Three.js CAD frontend from ./static.

Run locally:
    pip install -r requirements.txt
    python main.py                 # or: uvicorn main:app --host 0.0.0.0 --port 8000

Deploy (Render / Railway / HF Spaces):
    Start command:  uvicorn main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import logging
import os
from typing import List

import numpy as np
import trimesh
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from scipy import sparse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grillz")

app = FastAPI(
    title="Grillz Design Platform API",
    description="Generates watertight, 3D-printable grillz shells from painted tooth geometry.",
    version="1.0.0",
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


# --------------------------------------------------------------------------- #
#  Request model
# --------------------------------------------------------------------------- #
class GrillRequest(BaseModel):
    """Painted tooth surface (open triangle mesh) + shell parameters (mm)."""

    vertices: List[List[float]] = Field(..., description="Nx3 vertex positions in mm (world space)")
    faces: List[List[int]] = Field(..., description="Mx3 triangle vertex indices")
    inner_clearance: float = Field(0.10, ge=0.0, le=2.0, description="Fit gap between tooth and grill interior (mm)")
    shell_thickness: float = Field(0.80, ge=0.10, le=5.0, description="Nominal metal wall thickness (mm)")
    back_side_thinner_ratio: float = Field(0.45, ge=0.0, le=0.90, description="Max thickness reduction on lingual (-Y facing) and biting surfaces")
    smooth_iterations: int = Field(3, ge=0, le=10, description="Laplacian smoothing passes on the outer shell (0 = keep raw anatomical detail)")


# --------------------------------------------------------------------------- #
#  Geometry pipeline
# --------------------------------------------------------------------------- #
def _validate_input(vertices: np.ndarray, faces: np.ndarray) -> None:
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3:
        raise HTTPException(400, "vertices must be an Nx3 array with at least 3 points")
    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) < 1:
        raise HTTPException(400, "faces must be an Mx3 array with at least 1 triangle")
    if not np.isfinite(vertices).all():
        raise HTTPException(400, "vertices contain NaN or infinite values")
    if faces.min() < 0 or faces.max() >= len(vertices):
        raise HTTPException(400, "face indices out of range")
    extent = vertices.max(axis=0) - vertices.min(axis=0)
    if float(extent.max()) <= 1e-9:
        raise HTTPException(400, "input geometry is degenerate (zero extent)")


def _safe_vertex_normals(mesh: trimesh.Trimesh) -> np.ndarray:
    """Vertex normals with NaN/zero-length guards (degenerate fans get +Z)."""
    normals = np.array(mesh.vertex_normals, dtype=np.float64, copy=True)
    bad = ~np.isfinite(normals).all(axis=1)
    normals[bad] = [0.0, 0.0, 1.0]
    lengths = np.linalg.norm(normals, axis=1)
    zero = lengths < 1e-12
    normals[zero] = [0.0, 0.0, 1.0]
    lengths[zero] = 1.0
    return normals / lengths[:, None]


def _boundary_edges(mesh: trimesh.Trimesh) -> np.ndarray:
    """Directed boundary edges (edges referenced by exactly one face),
    returned in the winding order they appear in their face."""
    unique_idx = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
    return mesh.edges[unique_idx]


def _adjacency_matrix(faces: np.ndarray, n_vertices: int) -> sparse.csr_matrix:
    rows = np.concatenate([faces[:, 0], faces[:, 1], faces[:, 2],
                           faces[:, 1], faces[:, 2], faces[:, 0]])
    cols = np.concatenate([faces[:, 1], faces[:, 2], faces[:, 0],
                           faces[:, 0], faces[:, 1], faces[:, 2]])
    data = np.ones(len(rows), dtype=np.float64)
    adj = sparse.coo_matrix((data, (rows, cols)), shape=(n_vertices, n_vertices)).tocsr()
    adj.sum_duplicates()
    adj.data[:] = 1.0  # binary adjacency regardless of shared-edge multiplicity
    return adj


def _laplacian_smooth(points: np.ndarray, adjacency: sparse.csr_matrix,
                      fixed_mask: np.ndarray, iterations: int, lam: float = 0.5) -> np.ndarray:
    """Uniform-weight Laplacian smoothing; vertices in fixed_mask stay pinned
    (the shell rim must not move or the stitched wall would tear)."""
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    degree[degree == 0] = 1.0
    smoothed = points.copy()
    for _ in range(iterations):
        average = adjacency.dot(smoothed) / degree[:, None]
        relaxed = (1.0 - lam) * smoothed + lam * average
        relaxed[fixed_mask] = smoothed[fixed_mask]
        smoothed = relaxed
    return smoothed


def build_grill_shell(vertices: np.ndarray, faces: np.ndarray,
                      inner_clearance: float, shell_thickness: float,
                      back_side_thinner_ratio: float, smoothing_iterations: int) -> trimesh.Trimesh:
    """
    Turn an open painted tooth surface into a watertight grill shell:

      1. Inner surface  = tooth surface offset outward by `inner_clearance`
         along vertex normals (the fit gap).
      2. Outer surface  = inner surface offset by a *variable* thickness:
         vertices whose normals align with -Y (lingual / back side) are
         thinned by up to `back_side_thinner_ratio` for bite comfort.
      3. Laplacian smoothing (outer surface only) for a jewelry polish.
      4. Stitching: every boundary edge of the open surface is bridged with
         a quad (two triangles) between inner and outer shells, producing a
         closed, watertight manifold ready for casting/printing.
    """
    base = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    normals = _safe_vertex_normals(base)
    n_vertices = len(vertices)

    # 1. Inner (tooth-facing) surface: clearance offset.
    inner = vertices + normals * inner_clearance

    # 2. Dynamic thinning: lingual surfaces (normal aligned with -Y) get the
    #    full reduction; biting surfaces (normal aligned with -Z) contribute
    #    at 60% weight so the occlusal shell also stays comfortable.
    directional = np.clip(np.maximum(-normals[:, 1], 0.6 * -normals[:, 2]), 0.0, 1.0)
    thickness = shell_thickness * (1.0 - back_side_thinner_ratio * directional)
    outer = inner + normals * thickness[:, None]

    # 3. Smooth the outer shell only; rim (boundary) vertices stay pinned.
    boundary = _boundary_edges(base)
    fixed_mask = np.zeros(n_vertices, dtype=bool)
    if len(boundary):
        fixed_mask[np.unique(boundary)] = True
    if smoothing_iterations > 0:
        adjacency = _adjacency_matrix(faces, n_vertices)
        outer = _laplacian_smooth(outer, adjacency, fixed_mask, smoothing_iterations)

    # 4. Assemble the closed solid.
    #    Outer keeps the original winding (normals point away from the tooth);
    #    inner is flipped so its normals point back toward the tooth,
    #    i.e. outward from the metal solid.
    combined_vertices = np.vstack([inner, outer])
    inner_faces = faces[:, ::-1]
    outer_faces = faces + n_vertices

    wall_faces = []
    for a, b in boundary:
        wall_faces.append([a, b, b + n_vertices])
        wall_faces.append([a, b + n_vertices, a + n_vertices])
    wall_faces = np.array(wall_faces, dtype=np.int64).reshape(-1, 3)

    all_faces = np.vstack([inner_faces, outer_faces, wall_faces]) if len(wall_faces) \
        else np.vstack([inner_faces, outer_faces])

    solid = trimesh.Trimesh(vertices=combined_vertices, faces=all_faces, process=True)
    solid.update_faces(solid.nondegenerate_faces())
    solid.remove_unreferenced_vertices()
    solid.fix_normals()
    if not solid.is_watertight:
        solid.fill_holes()
        solid.fix_normals()
    return solid


# --------------------------------------------------------------------------- #
#  API
# --------------------------------------------------------------------------- #
@app.post("/api/generate-grill")
def generate_grill(request: GrillRequest) -> Response:
    """Generate a watertight grill shell and return it as a binary STL."""
    vertices = np.asarray(request.vertices, dtype=np.float64)
    faces = np.asarray(request.faces, dtype=np.int64)
    _validate_input(vertices, faces)

    try:
        solid = build_grill_shell(
            vertices, faces,
            inner_clearance=request.inner_clearance,
            shell_thickness=request.shell_thickness,
            back_side_thinner_ratio=request.back_side_thinner_ratio,
            smoothing_iterations=request.smooth_iterations,
        )
    except HTTPException:
        raise
    except Exception as exc:  # geometry failures become clean API errors
        log.exception("shell generation failed")
        raise HTTPException(422, f"Shell generation failed: {exc}") from exc

    stl_bytes = solid.export(file_type="stl")  # binary STL
    log.info(
        "generated grill: %d verts, %d faces, watertight=%s, %.1f KB",
        len(solid.vertices), len(solid.faces), solid.is_watertight, len(stl_bytes) / 1024,
    )
    return Response(
        content=stl_bytes,
        media_type="model/stl",
        headers={
            "Content-Disposition": 'attachment; filename="grillz.stl"',
            "X-Watertight": str(solid.is_watertight).lower(),
        },
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "engine": f"trimesh {trimesh.__version__}"}


# --------------------------------------------------------------------------- #
#  Automatic tooth detection (geometric segmentation)
# --------------------------------------------------------------------------- #
TOOTH_TYPES = ["Central Incisor", "Lateral Incisor", "Canine", "1st Premolar",
               "2nd Premolar", "1st Molar", "2nd Molar", "3rd Molar"]


class SegmentRequest(BaseModel):
    """Full scan mesh (mm). Assumes the app's axis convention: +Y labial,
    X across the arch, Z vertical."""

    vertices: List[List[float]]
    faces: List[List[int]]
    min_tooth_mm: float = Field(3.0, ge=0.5, le=10.0, description="Smallest bbox extent accepted as a tooth")
    max_tooth_mm: float = Field(18.0, ge=5.0, le=40.0, description="Largest bbox extent accepted as a tooth")


@app.post("/api/segment-teeth")
def segment_teeth(request: SegmentRequest) -> dict:
    """
    Detect individual teeth in a dental scan:

      1. Split the mesh into connected components.
      2. Keep tooth-sized components (bbox between min/max mm); everything
         else (gums, jaw base) becomes the non-paintable "rest" mesh.
      3. Order teeth along the arch by angle around the arch centroid and
         assign dental names. Patient's RIGHT appears at the viewer's left
         (-X), so -X teeth get R labels; FDI upper quadrants: R->1x, L->2x.

    Returns the teeth re-packed as one mesh with contiguous per-tooth
    vertex/face ranges (so the client can paint them individually) plus
    the leftover geometry.
    """
    vertices = np.asarray(request.vertices, dtype=np.float64)
    faces = np.asarray(request.faces, dtype=np.int64)
    _validate_input(vertices, faces)

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    try:
        components = mesh.split(only_watertight=False)
    except Exception as exc:
        raise HTTPException(422, f"Could not split scan into components: {exc}") from exc

    tooth_like, rest = [], []
    for comp in components:
        largest = float(comp.extents.max())
        if request.min_tooth_mm <= largest <= request.max_tooth_mm and len(comp.faces) >= 40:
            tooth_like.append(comp)
        else:
            rest.append(comp)

    if len(tooth_like) < 2:
        return {"teeth": [], "vertices": [], "faces": [], "rest_vertices": [], "rest_faces": [],
                "detail": f"only {len(tooth_like)} tooth-like connected regions found"}

    # order along the arch; angle 0 points labially (+Y) from the centroid
    centers = np.array([c.bounds.mean(axis=0) for c in tooth_like])
    centroid = centers.mean(axis=0)
    theta = np.arctan2(centers[:, 0] - centroid[0], centers[:, 1] - centroid[1])
    order = np.argsort(theta)

    # dental naming: rank within each side by distance from the midline
    naming = {}
    for side, sign in (("R", -1), ("L", 1)):
        side_idx = [i for i in range(len(tooth_like)) if (theta[i] < 0) == (sign < 0)]
        side_idx.sort(key=lambda i: abs(theta[i]))
        for rank, i in enumerate(side_idx, start=1):
            pos = min(rank, len(TOOTH_TYPES))
            naming[i] = {"name": f"{side}{rank}",
                         "fdi": (10 if side == "R" else 20) + pos,
                         "type": TOOTH_TYPES[pos - 1]}

    teeth_meta, out_vertices, out_faces = [], [], []
    v_off = f_off = 0
    for i in order:
        comp = tooth_like[i]
        nv, nf = len(comp.vertices), len(comp.faces)
        teeth_meta.append({**naming[i],
                           "vertex_start": v_off, "vertex_count": nv,
                           "face_start": f_off, "face_count": nf})
        out_vertices.append(comp.vertices)
        out_faces.append(comp.faces + v_off)
        v_off += nv
        f_off += nf

    teeth_vertices = np.round(np.vstack(out_vertices), 4)
    teeth_faces = np.vstack(out_faces)

    if rest:
        rest_combined = trimesh.util.concatenate(rest)
        rest_vertices = np.round(rest_combined.vertices, 4).tolist()
        rest_faces = rest_combined.faces.tolist()
    else:
        rest_vertices, rest_faces = [], []

    log.info("segmented scan: %d teeth, %d rest components", len(tooth_like), len(rest))
    return {"teeth": teeth_meta,
            "vertices": teeth_vertices.tolist(), "faces": teeth_faces.tolist(),
            "rest_vertices": rest_vertices, "rest_faces": rest_faces}


# --------------------------------------------------------------------------- #
#  Frontend hosting (single-service: no CORS needed)
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
