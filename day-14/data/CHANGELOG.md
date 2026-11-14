# Day 14 data changelog

## 2026-11-14
- Copied GW's photo `0-daily/20260318_194025.jpg` (Galaxy S25 Ultra, 4000 x 3000) to `source/`, then re-saved it as `source/tub_20260318_noexif.jpg` with all EXIF removed (it carried GPS coordinates of GW's home) and deleted the copy with EXIF. Stored orientation kept (drain at the left).
- `scripts/photo_metrics.py`: footprint box (120, 608, 3932, 2152) px squared to 1280 x 520 mm; `derived/photo_rect_05mm.jpg`, `derived/photo_metrics.npz` and `.json` (pale share 0.244; lighting flattened by a 40 mm blur).
- Model runs in `../runs/` (not data, not published): tuning runs t4, s*, k*, f2_*, g2_*, h2_* (exploration, superseded); the published set from `scripts/run_set.sh`: base_2mm, grid_1mm, grid_4mm, sweep/ (16).
- `scripts/render_tiles.py runs/base_2mm`: tiles to `site/data/day14/tiles/` (light, dark, photo; 254 each), `emerge.json`, `rules.png`, `meta.json`; photo tiles resampled from 0.336 to 0.25 mm a pixel.
- `scripts/build_eda.py`: `site/data/day14/eda.json`, `thumbs/` (16).
- Preflight 11-14: film-phase slope fixed (D263); all published runs redone with `scripts/run_set.sh`; tiles, `emerge.json`, `rules.png` (now from the model's own rule mask), `eda.json` and thumbs rebuilt from the new base run (misfit 0.526).
- 11-14 (after GW's spec notes): `scripts/render_tiles.py` gained the grey look; tiles `grey` and `greydark` (254 each) added to `site/data/day14/tiles/`; `light` and `dark` re-rendered byte-identical (seed 1414). The source photo `source/tub_20260318_noexif.jpg` (no EXIF, checked with Pillow) now ships in the repository (D258 reversed by GW).
- 11-14 (thin film): `thinfilm.py` on the upper-flank patch (x 300-380, y 30-110 mm, 0.5 mm grid, 20 s) from `runs/base_2mm` mud (H0 - eroded) with 60 % lumpiness at 1 mm. Development runs in `../runs/tf/` (try1-4, va-vd, s1 aborted, s2, s3; not published). Published figure and measures: `scripts/tf_figure.py` -> `site/data/day14/thinfilm.webp`, `thinfilm.json` (runs s2/n0.6_c1_t0.03, s3/t0.6, s3/t6). Photo patch measured at 0.5 mm after a 20 mm lighting flatten.
- 11-14 (wet-mud look): `render_tiles.py` gained `tone` and `tonedark` (Beer-Lambert tone, VE 25, no synthesised texture; 254 tiles each); all other sets re-rendered byte-identical; `meta.json` rewritten with the photo fields.
