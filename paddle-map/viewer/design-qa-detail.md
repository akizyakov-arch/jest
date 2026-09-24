# Detailed top-down sample — 2026-09-23

Local preview: /?mobile=1&detail=1 (iOS and Android viewport sizes); full map: /?detail=1.

The selected z14 tile (9987,5753) now uses a separately generated 1254px artwork, packed without upscaling into a 1024px native atlas. This adds z15 and z16 detail, rather than enlarging the previous 256px tile. All zoom levels derive from the same artwork to keep features stable.

23 WebP tiles, 460422 bytes in total, for this sample only. This excludes the surrounding base map, vectors, labels and application. Source detail is artistic, not surveyed; the boundary with the old artwork remains visible. Not a seamless production atlas.

Browser checks: detailed source loaded; all 16 z16 tiles requested at close view; before/after switches the correct layer; rotating to 30° keeps pitch at zero; zoom-in is disabled at the resolution cap. Screenshot: ../output/detail-mobile.png. Build passes. Native device performance has not been measured.

The camera cap accounts for display pixel density. High-density displays request a higher raster zoom via a smaller logical tile size. Further zoom needs additional source detail, not sharpening or larger interpolated tiles.
