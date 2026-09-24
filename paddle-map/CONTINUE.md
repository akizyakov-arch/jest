# PADDLE — checkpoint 2026-09-23

## User direction

The detailed top-down sample is approved as the visual foundation. User requests slightly cooler colors, less blur at maximum zoom, and this detail across the entire current artistic map district (4×4 z14 tiles). They clarified that “cover the whole map” means extend coverage, not close the preview. Latest request is to relocate into a dedicated working folder; destination has been requested, not yet provided.

## Working preview

Vite was running at http://127.0.0.1:4173 from viewer. Detailed sample: /?mobile=1&detail=1; full viewport /?detail=1. Original full district: /. Mobile preview supports 390×844 and 412×915 CSS viewports. This is a browser prototype, not a tested native application.

Approved sample: data/detail/generated-detail.png, 1254×1254. scripts/build-detail.mjs packs 23 WebP tiles (460422 bytes), z12–16, using a 1024px atlas without upscaling. public/style-detail.json and viewer/src/DetailView.jsx. Pitch is fixed at zero; rotation retained. Camera cap is 15-log2(DPR); high-DPR logical tile size selects finer source tiles. Tests confirmed z16 loads at DPR 1 and 2. User still sees softness at maximum scale: investigate source softness and sampling; this complaint is NOT resolved by the existing cap.

## Full-district work in progress

scripts/prepare-district.mjs creates 16 spatial guides in data/district/guide-X-Y.png. Each is 1152px with a 1024px core and 64px overlap on each side, derived from the old cool atlas enlarged ONLY as a guide, not new detail. Original bounds in data/art/georeference.json: z14 x9985 y5752 span4, roughly 6.7km square.

A single request for a 4096px whole district returned only 1254px; not adequate for full detailed zoom coverage. Instead, generated four new detailed northern patches (row y=0, x=0..3). Saved as data/district/generated-X-0.png. They require visual review, edge alignment, and blending before integration. Remaining 12 patches were NOT generated: image tool returned usage_limit_reached (429), reset approximately 2026-09-23 11:18 Europe/Moscow. Do not present the district as finished. No automatic paid API fallback was authorized.

Current approved sample and live map remain unchanged by the incomplete district work. No cooler replacement has been published. Continue using ImageGen for artistic edits, Sharp only for technical crop/resize/tile assembly. Keep source assets in this project, not solely under the user's generated_images folder.

## Sand

data/map.geojson contains 2 natural=sand features and 8 natural=beach features across the source extract. scripts/build-tiles.mjs places these polygons in landcover; scripts/build-style.mjs styles sand/beach. The illustrated raster also has painted sandy shores. No separate reusable sand material texture or dedicated sand raster tileset exists. Beach does not necessarily mean sand.

## Checks and relocation

Run node scripts/verify-detail.mjs and npm --prefix viewer run build for the detail sample. Previous checks passed. Runtime assets live in public; Vite config references ../public. Preserve the WHOLE paddle-map folder structure, including data, scripts, public, viewer, docs and package lockfiles. node_modules and viewer/dist are reproducible. Do not move or delete the surrounding Jest project. Read viewer/AGENTS.md for durable design preferences. If relocating outside the current writable root, use the necessary sandbox permission for the user-approved destination.
