import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const geo = JSON.parse(await readFile(`${root}data/map.geojson`, 'utf8'));
const ranges = new Set([0, 1024, 8192]);
for (const f of geo.features) for (const c of (f.properties['name:ru'] || f.properties.name || '')) ranges.add(Math.floor(c.codePointAt(0)/256)*256);
const dir = `${root}public/fonts/Noto Sans Regular`;
await mkdir(dir, {recursive:true});
for (const n of [...ranges].sort((a,b)=>a-b)) {
  const name = `${n}-${n+255}.pbf`;
  try { await readFile(`${dir}/${name}`); continue; } catch {}
  const response = await fetch(`https://demotiles.maplibre.org/font/Noto%20Sans%20Regular/${name}`, {signal:AbortSignal.timeout(30000)});
  if (!response.ok) throw new Error(`Font ${name}: HTTP ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  await writeFile(`${dir}/${name}`,bytes); console.log(`Font ${name}: ${bytes.length} bytes`);
}
const license = await fetch('https://raw.githubusercontent.com/notofonts/noto-fonts/main/LICENSE', {signal:AbortSignal.timeout(30000)});
if (!license.ok) throw new Error(`Font license: ${license.status}`);
await writeFile(`${root}public/fonts/LICENSE.txt`,await license.text());
