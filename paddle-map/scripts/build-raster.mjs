import sharp from 'sharp';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
const root=fileURLToPath(new URL('../',import.meta.url));
const ref=JSON.parse(await readFile(`${root}data/art/georeference.json`));
const cool=process.argv.includes('--cool');
const rasterDir=cool?'raster-cool':'raster';
const artDir=cool?'art-cool':'art';
await mkdir(`${root}public/${artDir}`,{recursive:true});
const input=`${root}data/art/${cool?'generated-atlas-cool.png':'generated-atlas.png'}`;
const info=await sharp(input).metadata();
const version=createHash('sha256').update(await readFile(input)).digest('hex').slice(0,10);
const sizes={},zooms=[];
// Packaging only: resize, encode and slice one atlas. No generative edits here.
// z14 uses 4x4 256px tiles; lower zooms are padded to the global XYZ grid.
for(let z=11;z<=14;z++) {
  const scale=2**(z-ref.z),n=2**z;
  const x0=Math.floor(ref.x*scale),y0=Math.floor(ref.y*scale);
  const x1=Math.ceil((ref.x+ref.span)*scale),y1=Math.ceil((ref.y+ref.span)*scale);
  const width=(x1-x0)*256,height=(y1-y0)*256;
  const artwork=await sharp(input).resize(Math.round(ref.span*256*scale),Math.round(ref.span*256*scale)).png().toBuffer();
  const atlas=await sharp({create:{width,height,channels:4,background:{r:0,g:0,b:0,alpha:0}}}).composite([{input:artwork,left:Math.round((ref.x*scale-x0)*256),top:Math.round((ref.y*scale-y0)*256)}]).png().toBuffer();
  let bytes=0,tiles=0;
  for(let x=x0;x<x1;x++)for(let y=y0;y<y1;y++) {
    await mkdir(`${root}public/${rasterDir}/${z}/${x}`,{recursive:true});
    const buffer=await sharp(atlas).extract({left:(x-x0)*256,top:(y-y0)*256,width:256,height:256}).webp({quality:83,effort:6}).toBuffer();
    await writeFile(`${root}public/${rasterDir}/${z}/${x}/${y}.webp`,buffer);
    sizes[`${z}/${x}/${y}`]=buffer.length;bytes+=buffer.length;tiles++;
  }
  zooms.push({z,tiles,bytes});
}
await sharp(input).webp({quality:86,effort:6}).toFile(`${root}public/${artDir}/atlas.webp`);
const stats={...ref,sourceImage:{width:info.width,height:info.height},tileSize:256,minzoom:11,maxzoom:14,version,encoding:'WebP quality 83',zooms,tiles:Object.keys(sizes).length,totalBytes:Object.values(sizes).reduce((a,b)=>a+b,0),sizes};
await writeFile(`${root}public/${artDir}/stats.json`,JSON.stringify(stats,null,2));
const style=JSON.parse(await readFile(`${root}public/style.json`));
style.name='PADDLE — Don / Illustrated study';
style.center=ref.center;style.zoom=14;
style.sources.art={type:'raster',tiles:[`./${rasterDir}/{z}/{x}/{y}.webp?v=${version}`],tileSize:256,minzoom:11,maxzoom:14,bounds:ref.bounds,attribution:'Художественная интерпретация · ImageGen'};
const firstLabel=style.layers.findIndex(l=>l.type==='symbol');
// Bounds use an inclusive tile test in MapLibre. Nudge inward to avoid
// requesting the nonexistent row/column exactly beyond the atlas edge.
style.sources.art.bounds=ref.bounds.map((v,i)=>v+(i<2?1e-8:-1e-8));
style.layers.splice(firstLabel,0,{id:'art-basemap',type:'raster',source:'art',paint:{'raster-fade-duration':0}});
style.layers.push({id:'geometry-check',type:'line',source:'don','source-layer':'water',layout:{visibility:'none'},paint:{'line-color':'#ff40be','line-width':1.3,'line-opacity':.9}});
style.metadata['paddle:art']=stats;
await writeFile(`${root}public/${cool?'style-art-cool.json':'style-art.json'}`,JSON.stringify(style,null,2));
console.log(JSON.stringify({...stats,sizes:undefined},null,2));
