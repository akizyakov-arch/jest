import assert from 'node:assert/strict';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';
import { VectorTile } from '@mapbox/vector-tile';
import Pbf from 'pbf';
import { validateStyleMin } from '@maplibre/maplibre-gl-style-spec';
const root=fileURLToPath(new URL('../',import.meta.url));
const style=JSON.parse(await readFile(`${root}public/style.json`));
assert.deepEqual(validateStyleMin(style).map(e=>e.message),[], 'Style must be valid');
const stats=JSON.parse(await readFile(`${root}public/stats.json`));
const sizes=JSON.parse(await readFile(`${root}public/tile-sizes.json`));
let count=0,rawBytes=0,gzipBytes=0,polygons=0,holes=0;
const layersSeen=new Set(),places=new Map();
for(const zoom of await readdir(`${root}public/tiles`))for(const x of await readdir(`${root}public/tiles/${zoom}`))for(const file of await readdir(`${root}public/tiles/${zoom}/${x}`)) {
  if(!file.endsWith('.pbf'))continue;
  const path=`${root}public/tiles/${zoom}/${x}/${file}`;
  const raw=await readFile(path),gzip=await readFile(path+'.gz');
  assert.deepEqual(gunzipSync(gzip),raw,`Gzip roundtrip ${path}`);
  const tile=new VectorTile(new Pbf(raw));
  for(const [name,layer] of Object.entries(tile.layers)) {
    layersSeen.add(name);assert.equal(layer.version,2);assert.equal(layer.extent,4096);
    for(let i=0;i<layer.length;i++) {
      const f=layer.feature(i);const geom=f.loadGeometry();assert.ok(geom.length);
      if(name==='water'){polygons++;if(geom.length>1)holes++;}
      if(name==='place')places.set(f.properties.name,f.toGeoJSON(Number(x),Number(file.split('.')[0]),Number(zoom)).geometry.coordinates);
    }
  }
  assert.equal(sizes[`${zoom}/${x}/${file.slice(0,-4)}`],gzip.length);
  count++;rawBytes+=raw.length;gzipBytes+=gzip.length;
}
assert.equal(count,stats.tiles);assert.equal(rawBytes,stats.rawBytes);assert.equal(gzipBytes,stats.gzipBytes);
assert.ok(holes>0,'River polygons retain interior rings / islands');
assert.ok(places.has('Азов'));assert.ok(places.has('Елизаветинская'));
assert.ok(Math.abs(places.get('Елизаветинская')[0]-39.473179)<.01);
for(const layer of style.layers)if(layer['source-layer'])assert.ok(layersSeen.has(layer['source-layer']));
for(const ids of Object.values(style.metadata['paddle:groups']))for(const id of ids)assert.ok(style.layers.some(l=>l.id===id));
for(const n of [0,1024,8192])assert.ok((await readFile(`${root}public/fonts/Noto Sans Regular/${n}-${n+255}.pbf`)).length>100);
const report={passed:true,tiles:count,rawBytes,gzipBytes,layers:[...layersSeen],waterPolygons:polygons,waterPolygonsWithMultipleRings:holes,places:[...places.keys()],checkedAt:new Date().toISOString()};
await writeFile(`${root}verification.json`,JSON.stringify(report,null,2));
console.log(JSON.stringify({...report,places:report.places.length},null,2));
