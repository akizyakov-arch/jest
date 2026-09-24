import sharp from 'sharp';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
await mkdir(`${root}data/detail`,{recursive:true});
// Technical geographic extraction only, no artistic edits.
const x=9987,y=5753,z=14;
const lon=x=>x/2**z*360-180;
const lat=y=>Math.atan(Math.sinh(Math.PI*(1-2*y/2**z)))*180/Math.PI;
const reference={z,x,y,span:1,bounds:[lon(x),lat(y+1),lon(x+1),lat(y)],center:[lon(x+.5),lat(y+.5)],projection:'EPSG:3857',geometryStatus:'Artistic detail study; generated features not surveyed'};
await sharp(`${root}data/art/generated-atlas-cool.png`).resize(2048,2048).extract({left:1024,top:512,width:512,height:512}).png().toFile(`${root}data/detail/input-patch.png`);
await writeFile(`${root}data/detail/georeference.json`,JSON.stringify(reference,null,2));
console.log(reference);
