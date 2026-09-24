import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
// West, south, east, north. A padded extract preserves complete river polygons.
const bounds = [39.27, 47.065, 39.57, 47.255];
const bbox = '47.045,39.24,47.275,39.60';
const query = `[out:json][timeout:60][maxsize:134217728];(
  way["natural"~"^(water|wood|scrub|wetland|grassland|sand|beach)$"](${bbox});
  relation["natural"~"^(water|wood|scrub|wetland|grassland|sand|beach)$"](${bbox});
  way["landuse"](${bbox});relation["landuse"](${bbox});
  way["waterway"](${bbox});relation["waterway"="riverbank"](${bbox});
  way["highway"](${bbox});way["railway"="rail"](${bbox});
  way["building"](${bbox});relation["building"](${bbox});
  node["place"~"^(city|town|village|hamlet|suburb|locality)$"](${bbox});
);out body;>;out skel qt;`;
await mkdir(`${root}data`, { recursive: true });
await writeFile(`${root}data/query.overpass`, query);
try { const existing = JSON.parse(await readFile(`${root}data/osm.json`)); if (existing.elements?.length && !existing.remark) { console.log(`Using cached extract: ${existing.elements.length} elements`); process.exit(0); } } catch {}
const endpoints = ['https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter'];
for (const endpoint of endpoints) {
  console.log(`Requesting ${endpoint}`);
  try {
    const response = await fetch(`${endpoint}?data=${encodeURIComponent(query)}`, {
      headers: { 'User-Agent': 'PaddleMapPrototype/0.1 (one-time cartographic extract for Azov, no live polling)' },
      signal: AbortSignal.timeout(90000)
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${(await response.text()).slice(0,140)}`);
    const data = await response.json();
    if (data.remark || !data.elements?.length) throw new Error(data.remark || 'Empty extract');
    await writeFile(`${root}data/osm.json`, JSON.stringify(data));
    await writeFile(`${root}data/source.json`, JSON.stringify({ endpoint, bounds, fetchedAt: new Date().toISOString(), osmTimestamp: data.osm3s?.timestamp_osm_base, elements: data.elements.length, attribution: '© OpenStreetMap contributors', license: 'https://www.openstreetmap.org/copyright' }, null, 2));
    console.log(`Saved ${data.elements.length} elements`); process.exit(0);
  } catch (error) { console.error(error.message); }
}
throw new Error('All extract endpoints failed; no substitute geometry was generated.');
