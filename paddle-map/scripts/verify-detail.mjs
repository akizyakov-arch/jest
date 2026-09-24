import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import sharp from 'sharp';
import {validateStyleMin} from '@maplibre/maplibre-gl-style-spec';
const read=async p=>JSON.parse(await readFile(new URL('../'+p,import.meta.url)));
const stats=await read('public/detail/stats.json'),style=await read('public/style-detail.json');
assert.deepEqual(validateStyleMin(style).map(e=>e.message),[]);
let total=0;
for(const [key,size] of Object.entries(stats.sizes)){
 const b=await readFile(new URL('../public/raster-detail/'+key+'.webp',import.meta.url));
 assert.equal(b.length,size);total+=size;
 const m=await sharp(b).metadata();assert.equal(m.width,256);assert.equal(m.height,256);
}
assert.equal(total,stats.totalBytes);assert.equal(Object.keys(stats.sizes).length,23);
assert.equal(Object.keys(stats.sizes).filter(k=>k.startsWith('16/')).length,16);
const source=await sharp(new URL('../data/detail/generated-detail.png',import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1')).metadata();
assert.ok(source.width>=1024&&source.height>=1024);
assert.equal(style.sources.detail.maxzoom,16);
console.log({passed:true,tiles:23,totalBytes:total,sourcePixels:[source.width,source.height]});
