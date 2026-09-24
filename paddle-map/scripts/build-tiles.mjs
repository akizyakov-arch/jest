import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
import osmtogeojson from 'osmtogeojson';
import GeoJSONVT from 'geojson-vt';
import vtpbf from 'vt-pbf';

const root = fileURLToPath(new URL('../', import.meta.url));
const output = `${root}public`;
const source = JSON.parse(await readFile(`${root}data/source.json`, 'utf8'));
const osm = JSON.parse(await readFile(`${root}data/osm.json`, 'utf8'));
const geojson = osmtogeojson(osm, { flatProperties: true });
const collections = Object.fromEntries(['water', 'landcover', 'waterway', 'transportation', 'building', 'place', 'canopy'].map(k => [k, { type: 'FeatureCollection', features: [] }]));
let skipped = 0;
for (const feature of geojson.features) {
  const p = feature.properties;
  if (!feature.geometry || p.tainted) { skipped++; continue; }
  const polygon = /Polygon/.test(feature.geometry.type);
  const line = /LineString/.test(feature.geometry.type);
  let layer, kind;
  if (polygon && (p.natural === 'water' || p.waterway === 'riverbank' || p.landuse === 'reservoir')) { layer = 'water'; kind = p.water || 'water'; }
  else if (polygon && p.building) { layer = 'building'; kind = p.building; }
  else if (polygon && (p.natural || p.landuse)) { layer = 'landcover'; kind = p.natural || p.landuse; }
  else if (line && p.waterway) { layer = 'waterway'; kind = p.waterway; }
  else if (line && (p.highway || p.railway)) { layer = 'transportation'; kind = p.highway || 'rail'; }
  else if (feature.geometry.type === 'Point' && p.place) { layer = 'place'; kind = p.place; }
  if (!layer) continue;
  collections[layer].features.push({ type: 'Feature', geometry: feature.geometry, properties: {
    kind, name: p['name:ru'] || p.name || '', osm_id: feature.id,
    ...(layer === 'transportation' ? { bridge: p.bridge && p.bridge !== 'no' ? 1 : 0 } : {})
  }});
}
await mkdir(output, { recursive: true });
await writeFile(`${root}data/map.geojson`, JSON.stringify(geojson));
// Decorative canopy points stay inside mapped woodland. They are not observed trees.
function insideRing(x,y,ring) {
  let inside=false;
  for(let i=0,j=ring.length-1;i<ring.length;j=i++) {
    const [xi,yi]=ring[i], [xj,yj]=ring[j];
    if((yi>y)!==(yj>y) && x<(xj-xi)*(y-yi)/(yj-yi)+xi)inside=!inside;
  }
  return inside;
}
function noise(x,y,salt=0){ let v=Math.imul(x+salt,374761393)^Math.imul(y-salt,668265263);v=Math.imul(v^(v>>>13),1274126177);return ((v^(v>>>16))>>>0)/4294967296; }
const dx=0.00038,dy=0.00026;
const occupied=new Set();
for(const f of collections.landcover.features.filter(f=>['wood','forest'].includes(f.properties.kind))) {
  const polygons=f.geometry.type==='Polygon'?[f.geometry.coordinates]:f.geometry.coordinates;
  for(const rings of polygons) {
    const xs=rings[0].map(p=>p[0]),ys=rings[0].map(p=>p[1]);
    const x0=Math.ceil(Math.max(source.bounds[0],Math.min(...xs))/dx), x1=Math.floor(Math.min(source.bounds[2],Math.max(...xs))/dx);
    const y0=Math.ceil(Math.max(source.bounds[1],Math.min(...ys))/dy), y1=Math.floor(Math.min(source.bounds[3],Math.max(...ys))/dy);
    for(let x=x0;x<=x1;x++)for(let y=y0;y<=y1;y++) {
      const key=`${x}/${y}`; if(occupied.has(key))continue;
      const lon=(x+(noise(x,y,31)-.5)*.85)*dx,lat=(y+(noise(x,y,61)-.5)*.85)*dy;
      if(!insideRing(lon,lat,rings[0]) || rings.slice(1).some(r=>insideRing(lon,lat,r)))continue;
      occupied.add(key);
      collections.canopy.features.push({type:'Feature',geometry:{type:'Point',coordinates:[lon,lat]},properties:{tone:Math.floor(noise(x,y,93)*4),density:Math.floor(noise(x,y,151)*4)}});
    }
  }
}
const counts = Object.fromEntries(Object.entries(collections).map(([name,c])=>[name,c.features.length]));
console.log('Features:', counts, 'Skipped incomplete:', skipped);
if (!counts.water || !counts.place) throw new Error('Extract lacks essential water or place data');
const indexes = Object.fromEntries(Object.entries(collections).map(([name, collection]) => [name, new GeoJSONVT(collection, { maxZoom: 15, tolerance: 3, extent: 4096, buffer: 128, indexMaxZoom: 5, generateId: true })]));
const tileX = (lon, z) => Math.floor((lon + 180) / 360 * 2 ** z);
const tileY = (lat, z) => Math.floor((1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2 * 2 ** z);
const [west,south,east,north] = source.bounds;
const stats = { bounds: source.bounds, minzoom: 9, maxzoom: 15, counts, skippedIncomplete: skipped, tiles: 0, rawBytes: 0, gzipBytes: 0, maxGzipTileBytes: 0, zooms: [], generatedAt: new Date().toISOString(), source };
const tileSizes = {};
for (let z = stats.minzoom; z <= stats.maxzoom; z++) {
  const row = { z, tiles: 0, rawBytes: 0, gzipBytes: 0 };
  for (let x = tileX(west,z); x <= tileX(east,z); x++) {
    await mkdir(`${output}/tiles/${z}/${x}`, { recursive: true });
    for (let y = tileY(north,z); y <= tileY(south,z); y++) {
      const layers = {};
      for (const [name,index] of Object.entries(indexes)) {
        if ((name === 'building' || name === 'canopy') && z < 13) continue;
        const tile = index.getTile(z,x,y);
        if (!tile?.features.length) continue;
        if (name === 'transportation' && z < 12) tile.features = tile.features.filter(f => ['motorway','trunk','primary','secondary','tertiary','rail'].includes(f.tags.kind));
        if (name === 'canopy' && z === 13) tile.features = tile.features.filter(f => f.tags.density === 0);
        if (name === 'canopy' && z === 14) tile.features = tile.features.filter(f => f.tags.density < 2);
        if (tile.features.length) layers[name] = tile;
      }
      const pbf = Buffer.from(vtpbf.fromGeojsonVt(layers, { version: 2, extent: 4096 }));
      const gzip = gzipSync(pbf, { level: 9 });
      tileSizes[`${z}/${x}/${y}`]=gzip.length;
      await writeFile(`${output}/tiles/${z}/${x}/${y}.pbf`, pbf);
      await writeFile(`${output}/tiles/${z}/${x}/${y}.pbf.gz`, gzip);
      row.tiles++; row.rawBytes += pbf.length; row.gzipBytes += gzip.length;
      stats.maxGzipTileBytes = Math.max(stats.maxGzipTileBytes, gzip.length);
    }
  }
  stats.tiles += row.tiles; stats.rawBytes += row.rawBytes; stats.gzipBytes += row.gzipBytes; stats.zooms.push(row);
  console.log(`z${z}: ${row.tiles} tiles, ${(row.gzipBytes / 1024).toFixed(0)} KiB gzip`);
}
await writeFile(`${output}/stats.json`, JSON.stringify(stats, null, 2));
await writeFile(`${output}/tile-sizes.json`, JSON.stringify(tileSizes));
await writeFile(`${output}/tilejson.json`, JSON.stringify({ tilejson: '3.0.0', name: 'PADDLE · Don Delta', description: 'Azov / Yelizavetinskaya — OSM vector sample', scheme: 'xyz', tiles: ['./tiles/{z}/{x}/{y}.pbf'], minzoom: stats.minzoom, maxzoom: stats.maxzoom, bounds: source.bounds, center: [39.455,47.142,13.4], attribution: '© OpenStreetMap contributors', vector_layers: Object.keys(collections).map(id=>({id, fields:id==='canopy'?{tone:'Number',density:'Number'}:{kind:'String',name:'String',osm_id:'String'}})) },null,2));
console.log(`Total: ${stats.tiles} tiles; ${(stats.gzipBytes/1048576).toFixed(2)} MiB gzip`);
