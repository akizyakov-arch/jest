# Prototype Instructions

The user approved the detailed overhead sample as the foundation. Next: slightly
cooler palette, resolve maximum-zoom softness, and extend detailed coverage over
the entire existing artistic district. Full district generation is incomplete;
see ../CONTINUE.md. Do not claim the incomplete atlas is ready.

## Cartography feedback — 2026-09-23

Correction: the user means dimensional detail in a straight-down map, not
camera pitch. Keep pitch at zero in the next preview. Add a small newly
rendered high-detail sample and real additional zoom levels; don't pass off
upscaling the old atlas as new detail. Preserve rotation and mobile preview.

The user requested map rotation, a 2.5D feel, and a mobile preview. Implement
camera pitch/bearing and clearly identify it as a flat raster in perspective,
not real terrain. Preserve existing styles and provide a browser viewport
preview without claiming native iOS/Android validation.

The user approved a cooler, less yellow version with deeper water colors,
softer banks and more dimensional canopy groups. Keep the warm version for
same-camera comparison, make the cool version default, and measure tile sizes.

The first flat vector map was rejected as too far from the supplied painterly
reference. Prioritize detailed vegetation, dimensional tree canopies, turquoise
water and softly treated shores. The user authorized a small raster-tile sample
with separate vector labels and a measured payload. Keep the original vector
mode available for comparison. Generated cartography is a visual study, not
validated navigation data; do not claim geometry preservation without evidence.

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.
