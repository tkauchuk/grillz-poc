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

1. A **realistic procedural dental arch** loads instantly — trapezoidal incisors,
   pointed diamond-profile canines, and cusped premolars/molars built from
   deformed superellipsoids and merged into a single paintable mesh (or upload
   your own STL scan).
2. **Paint** the target teeth with the brush tool (yellow highlight).
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
