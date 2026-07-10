# 💎 Grillz Design Platform — POC

Web-based dental CAD for designing custom grillz. A single FastAPI service does the
3D geometric processing (trimesh) **and** hosts the interactive Three.js frontend —
no CORS, one-command deployment.

```
├── main.py            # FastAPI: /api/generate-grill + static hosting
├── requirements.txt
└── static/
    └── index.html     # Three.js CAD editor (PBR metals, painting, diamonds, sprues)
```

## Run

```bash
pip install -r requirements.txt
python main.py                      # http://localhost:8000
```

Deploy (Render / Railway / HF Spaces) with start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Workflow

1. A **realistic dental cast** loads instantly: six anatomical anterior tooth
   scans plus a full jaw-cast backdrop (converted from the MIT-licensed
   [iiitl/molars](https://github.com/iiitl/molars) models — see
   `static/models/LICENSE.txt`), merged into a single paintable mesh. If the
   model files are unavailable the app falls back to a procedural arch built
   from deformed superellipsoids (trapezoidal incisors, pointed canines,
   cusped premolars/molars). You can also upload your own STL scan.
2. **Automatic tooth detection** runs on load: teeth are identified, swept with
   a highlight animation, and listed in the TEETH tab as a table with dental
   names (R1/L1 style + FDI codes like 11/21), detected type, and measured
   W×H in mm. Clicking a row toggles that tooth in the grill selection.
   Uploaded STL scans are segmented geometrically on the backend
   (`POST /api/segment-teeth`: connected components filtered to tooth-sized
   regions, ordered along the arch, gums/jaw returned as a separate backdrop).
3. **Paint** the target teeth with the brush tool (yellow highlight) — or just
   pick them from the table.
3. Tune **Wall Thickness / Inner Clearance / Edge Margin / Back-Side Thinning /
   Smooth Strength** (0 keeps every cusp of the anatomy, 10 melts the shell
   into a soft jewelry polish).
4. **Generate Grillz** — the backend offsets the painted surface by the clearance,
   extrudes a variable-thickness outer shell (lingual and biting surfaces thinned
   up to 45% for comfort), Laplacian-polishes the outer surface per the Smooth
   Strength setting, stitches the rims into a **watertight manifold**, and streams
   back a binary STL that overlays the teeth.
5. **Pavé diamonds** (InstancedMesh placed by raycasting the actual grill/tooth
   surface, per-row control, individual gem editing, live stone report), place
   **casting sprues**, and measure with the **ruler** — point A (red marker),
   dashed preview to the cursor, then point B locks a neon-green tube with a
   floating mm label.
6. Swap **Yellow Gold / Rose Gold / Polished Silver** PBR presets live from the
   always-visible Material Preview swatches.
7. Download the watertight grill STL, or the full scene (grill + gems + sprues).
