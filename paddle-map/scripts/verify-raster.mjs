import assert from 'node:assert/strict';
import sharp from 'sharp';
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { validateStyleMin } from '@maplibre/maplibre-gl-style-spec';
const root=fileURLToPath(new URL('../',import.meta.url));
const cool=process.argv.includes('--cool');
const stats=JSON.parse(await readFile(`${root}public/${cool?'art-cool':'art'}/stats.json`));
const style=JSON.parse(await readFile(`${root}public/${cool?'style-art-cool.json':'style-art.json'}`));
assert.deepEqual(validateStyleMin(style).map(e=>e.message),[]);
let total=0;
for(const [key,size] of Object.entries(stats.sizes)){
  const bytes=await readFile(`${root}public/${cool?'raster-cool':'raster'}/${key}.webp`);
  assert.equal(bytes.length,size);
  const image=await sharp(bytes).metadata();assert.equal(image.width,256);assert.equal(image.height,256);assert.equal(image.format,'webp');
  total+=bytes.length;
}
assert.equal(total,stats.totalBytes);assert.equal(Object.keys(stats.sizes).length,stats.tiles);
style.sources.art.bounds.forEach((v,i)=>assert.ok(Math.abs(v-stats.bounds[i])<1e-7));
assert.equal(style.sources.art.tileSize,256);
// Verify the 16 native tiles cover the georeferenced atlas without gaps.
for(let x=stats.x;x<stats.x+stats.span;x++)for(let y=stats.y;y<stats.y+stats.span;y++)assert.ok(stats.sizes[`${stats.z}/${x}/${y}`]);
assert.ok(style.layers.findIndex(l=>l.id==='art-basemap')<style.layers.findIndex(l=>l.id==='places'));
const report={passed:true,tiles:stats.tiles,totalBytes:total,sourcePixels:stats.sourceImage,geometryValidated:false,checkedAt:new Date().toISOString()};
await writeFile(`${root}${cool?'art-cool-verification':'art-verification'}.json`,JSON.stringify(report,null,2));console.log(report);
