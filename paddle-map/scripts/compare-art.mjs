// QA visualization only: put the generated target beside the tiled renderer.
import sharp from 'sharp';
import { fileURLToPath } from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const suffix=process.argv.includes('--cool')?'-cool':'';
const left=await sharp(`${root}data/art/generated-atlas${suffix}.png`).resize(800,800).png().toBuffer();
const right=await sharp(`${root}data/art/rendered-atlas${suffix}.png`).resize(800,800).png().toBuffer();
await sharp({create:{width:1600,height:800,channels:3,background:'#ffffff'}}).composite([{input:left,left:0,top:0},{input:right,left:800,top:0}]).png().toFile(`${root}art-render-comparison${suffix}.png`);
