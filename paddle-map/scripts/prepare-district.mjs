import sharp from 'sharp';
import {mkdir,writeFile} from 'node:fs/promises';
const root=new URL('../',import.meta.url);
const path=p=>new URL(p,root).pathname.replace(/^\/([A-Za-z]:)/,'$1');
await mkdir(path('data/district'),{recursive:true});
// Enlarged only as spatial guides. Final artwork must be newly generated.
const guide=await sharp(path('data/art/generated-atlas-cool.png')).resize(4096,4096).extend({top:64,bottom:64,left:64,right:64,extendWith:'copy'}).png().toBuffer();
for(let y=0;y<4;y++)for(let x=0;x<4;x++)await sharp(guide).extract({left:x*1024,top:y*1024,width:1152,height:1152}).png().toFile(path(`data/district/guide-${x}-${y}.png`));
await writeFile(path('data/district/manifest.json'),JSON.stringify({columns:4,rows:4,core:1024,overlap:64,guideOnly:true},null,2));
