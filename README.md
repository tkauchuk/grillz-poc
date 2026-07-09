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

1. A procedural dental arch loads instantly (or upload your own STL scan).
2. **Paint** the target teeth with the brush tool (translucent yellow highlight).
3. Tune **Wall Thickness / Inner Clearance / Edge Margin / Back-Side Thinning**.
4. **Generate Grillz** — the backend offsets the painted surface by the clearance,
   extrudes a variable-thickness outer shell (lingual walls thinned up to 45% for
   bite comfort), Laplacian-polishes the outer surface, stitches the rims into a
   **watertight manifold**, and streams back a binary STL that overlays the teeth.
5. **Pavé diamonds** (InstancedMesh along surface normals, per-row control,
   individual gem editing, live stone report), place **casting sprues**, measure
   distances in mm, and preview **gold / rose gold / silver** PBR finishes.
6. Download the watertight grill STL, or the full scene (grill + gems + sprues).
