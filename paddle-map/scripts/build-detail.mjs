import sharp from 'sharp';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
const root=fileURLToPath(new URL('../',import.meta.url));
const ref=JSON.parse(await readFile(`${root}data/detail/georeference.json`));
const input=await readFile(`${root}data/detail/generated-detail.png`);
const meta=await sharp(input).metadata();
const version=createHash('sha256').update(input).digest('hex').slice(0,10);
const sizes={},zooms=[];
for(let z=12;z<=16;z++){
 const scale=2**(z-ref.z),size=Math.round(256*scale);
 if(size>Math.min(meta.width,meta.height))throw Error('Refusing to upscale the detail source');
 const x0=Math.floor(ref.x*scale),y0=Math.floor(ref.y*scale),x1=Math.ceil((ref.x+1)*scale),y1=Math.ceil((ref.y+1)*scale);
 const art=await sharp(input).resize(size,size).png().toBuffer();
 const atlas=await sharp({create:{width:(x1-x0)*256,height:(y1-y0)*256,channels:4,background:{r:0,g:0,b:0,alpha:0}}}).composite([{input:art,left:Math.round((ref.x*scale-x0)*256),top:Math.round((ref.y*scale-y0)*256)}]).png().toBuffer();
 let bytes=0,tiles=0;
 for(let x=x0;x<x1;x++)for(let y=y0;y<y1;y++){
  await mkdir(`${root}public/raster-detail/${z}/${x}`,{recursive:true});
  const tile=await sharp(atlas).extract({left:(x-x0)*256,top:(y-y0)*256,width:256,height:256}).webp({quality:86,effort:6}).toBuffer();
  await writeFile(`${root}public/raster-detail/${z}/${x}/${y}.webp`,tile);sizes[`${z}/${x}/${y}`]=tile.length;bytes+=tile.length;tiles++;
 }
 zooms.push({z,tiles,bytes});
}
const stats={...ref,minzoom:12,maxzoom:16,tileSize:256,sourcePixels:[meta.width,meta.height],nativeAtlasPixels:1024,version,encoding:'WebP quality 86',sizes,zooms,tiles:Object.keys(sizes).length,totalBytes:Object.values(sizes).reduce((a,b)=>a+b,0)};
await mkdir(`${root}public/detail`,{recursive:true});
await writeFile(`${root}public/detail/stats.json`,JSON.stringify(stats,null,2));
await sharp(input).webp({quality:90,effort:6}).toFile(`${root}public/detail/atlas.webp`);
const style=JSON.parse(await readFile(`${root}public/style-art-cool.json`));
style.name='PADDLE — detailed overhead sample';style.center=ref.center;style.zoom=14;
style.sources.detail={type:'raster',tiles:[`./raster-detail/{z}/{x}/{y}.webp?v=${version}`],tileSize:256,minzoom:12,maxzoom:16,bounds:ref.bounds.map((v,i)=>v+(i<2?1e-8:-1e-8)),attribution:'Детальный художественный образец · ImageGen'};
const idx=style.layers.findIndex(l=>l.id==='art-basemap');
style.layers.splice(idx+1,0,{id:'detail-art',type:'raster',source:'detail',paint:{'raster-fade-duration':0}});
const [w,s,e,n]=ref.bounds;
style.sources.detailFrame={type:'geojson',data:{type:'Feature',properties:{},geometry:{type:'LineString',coordinates:[[w,s],[e,s],[e,n],[w,n],[w,s]]}}};
style.layers.push({id:'detail-frame',type:'line',source:'detailFrame',paint:{'line-color':'#b6e8df','line-width':1.5,'line-opacity':.65,'line-dasharray':[4,4]}});
style.metadata['paddle:detail']=stats;
await writeFile(`${root}public/style-detail.json`,JSON.stringify(style,null,2));
console.log({...stats,sizes:undefined});
