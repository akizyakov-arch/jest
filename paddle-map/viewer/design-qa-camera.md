# Camera / mobile preview QA

Target: existing approved cool map, mobile reference as context, new requested
rotation/pitch and mobile-size preview. No new raster artwork was generated.
Existing map textures, labels, colors and typography are preserved.

Evidence: `../preview-mobile-25d.png`, 1200 × 1120 CSS px outer viewport;
embedded map is 390 × 844 CSS px. Android viewport measured 412 × 915.
This is a plain browser viewport frame, not simulated physical device chrome.

Checked: initial pitch 40 / bearing -18; right rotation to bearing 12;
north reset to 0; 2.5D toggle to pitch 0 and back; slider set to 50;
device viewport resizing. No horizontal overflow; camera buttons remain
inside the viewport and above location tabs. Existing layer/settings panel
remains usable. No browser errors in final run. Production build passes.

Corrections: CSS order fixed so mobile camera overrides apply; outer frame
uses content-box to preserve exact embedded dimensions; start center adjusted
to show the river; controls use existing Phosphor icons.

Scope limitation: camera pitch only, not terrain or 3D trees. Native iOS/Android
and physical multi-touch not tested. No claim of pixel-match to phone reference.

final result: passed
