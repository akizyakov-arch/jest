import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const zoom = (...stops) => ['interpolate', ['linear'], ['zoom'], ...stops];
const eq = (key,val) => ['==', ['get',key],val];
const oneOf = (values) => ['in',['get','kind'],['literal',values]];
const layer = (id,type,sourceLayer,paint,extra={}) => ({id,type,source:'don','source-layer':sourceLayer,paint,...extra});
const font = ['Noto Sans Regular'];
const layers = [
  {id:'land',type:'background',paint:{'background-color':'#a6b985'}},
  layer('landcover','fill','landcover',{'fill-color':['match',['get','kind'],
    ['wood','forest'],'#53785a',['scrub'],'#78965e',['wetland'],'#7fa780',
    ['grassland','meadow','grass','recreation_ground','village_green'],'#9fb77c',
    ['farmland','farmyard'],'#b6be87',['orchard','vineyard'],'#8ba569',
    ['sand','beach'],'#d6d0a1',['residential'],'#bdc5aa',
    ['industrial','commercial','retail','railway'],'#a9b6a1',['cemetery'],'#8ca88a','#a3b485']}),
  layer('forest-rim','line','landcover',{'line-color':'#3e654f','line-opacity':0.26,'line-width':zoom(10,0.5,15,2.5),'line-blur':1.5},{filter:oneOf(['wood','forest'])}),
  layer('fields-outline','line','landcover',{'line-color':'#e3dfaa','line-opacity':0.2,'line-width':0.6},{minzoom:12,filter:oneOf(['farmland','orchard','meadow'])}),
  layer('canopy-shadows','circle','canopy',{'circle-radius':zoom(13,1.9,14,2.8,15,3.9,17,12),'circle-color':'#264f41','circle-opacity':0.32,'circle-blur':0.6,'circle-translate':[1.2,1.5]},{minzoom:13}),
  layer('canopy','circle','canopy',{'circle-radius':zoom(13,1.5,14,2.3,15,3.4,17,11),'circle-color':['match',['get','tone'],0,'#69885b',1,'#78955f',2,'#496e51','#8aa366'],'circle-opacity':0.8,'circle-blur':0.22},{minzoom:13}),
  layer('canopy-light','circle','canopy',{'circle-radius':zoom(13,.5,15,1.6,17,5),'circle-color':'#b5bd75','circle-opacity':0.25,'circle-blur':0.65,'circle-translate':[-.6,-.8]},{minzoom:13}),
  // Decorative shoreline strokes are screen-space styling, never bathymetry.
  layer('shore-shadow','line','water',{'line-color':'#244e47','line-opacity':0.22,'line-width':zoom(9,2,13,7,17,13),'line-blur':zoom(9,1,13,5,17,8)}),
  layer('water','fill','water',{'fill-color':'#147e92','fill-antialias':true}),
  layer('water-bank-soft','line','water',{'line-color':'#69c4af','line-opacity':0.65,'line-width':zoom(9,1,12,7,16,20),'line-blur':zoom(9,1,12,6,16,16)}),
  layer('water-bank','line','water',{'line-color':'#bbcc9b','line-opacity':0.85,'line-width':zoom(9,0.4,12,1.1,16,2.4)}),
  layer('waterways','line','waterway',{'line-color':'#278b98','line-width':zoom(10,0.3,13,1.4,16,3.2)},{filter:['!',oneOf(['riverbank','river'])],layout:{'line-cap':'round','line-join':'round'}}),
  layer('roads-casing','line','transportation',{'line-color':'#84967e','line-opacity':0.6,'line-width':zoom(10,0.7,13,2.7,16,6)},{filter:oneOf(['motorway','trunk','primary','secondary','tertiary','residential','unclassified']),layout:{'line-cap':'round','line-join':'round'}}),
  layer('roads','line','transportation',{'line-color':'#e1debb','line-opacity':0.9,'line-width':zoom(10,0.4,13,1.4,16,3.8)},{filter:oneOf(['motorway','trunk','primary','secondary','tertiary','residential','unclassified']),layout:{'line-cap':'round','line-join':'round'}}),
  layer('paths','line','transportation',{'line-color':'#e2dfb4','line-opacity':0.62,'line-width':zoom(12,0.4,16,1.5),'line-dasharray':[3,2]},{minzoom:12,filter:oneOf(['track','path','footway','cycleway','service','living_street'])}),
  layer('railways','line','transportation',{'line-color':'#7e8e7c','line-width':1,'line-dasharray':[2,2]},{minzoom:12,filter:eq('kind','rail')}),
  layer('buildings','fill','building',{'fill-color':'#e6ddbd','fill-opacity':zoom(13,0.4,15,0.85),'fill-outline-color':'#a6aa90'},{minzoom:13}),
  layer('water-labels','symbol','waterway',{'text-color':'#d4f1e9','text-halo-color':'#16788a','text-halo-width':1.3,'text-halo-blur':0.6},{minzoom:10,filter:['all',['!=',['get','name'],''],oneOf(['river','canal','stream'])],layout:{'symbol-placement':'line','symbol-spacing':500,'text-field':['get','name'],'text-font':font,'text-size':zoom(10,12,14,17),'text-letter-spacing':0.15,'text-max-angle':35}}),
  layer('places','symbol','place',{'text-color':'#fcf9e8','text-halo-color':'#365950','text-halo-width':1.5,'text-halo-blur':0.5},{filter:['!=',['get','name'],''],layout:{'text-field':['get','name'],'text-font':font,'text-size':['match',['get','kind'],['city','town'],20,['village'],15,12],'text-max-width':10,'text-padding':14,'text-letter-spacing':0.04,'symbol-sort-key':['match',['get','kind'],['city','town'],0,'village',1,2]}}),
];
const style = {version:8,name:'PADDLE — Don / Estuary',metadata:{'paddle:description':'Vector cartography inspired by the supplied Don reference. Decorative shore treatment; no depth data.','paddle:groups':{labels:['water-labels','places'],roads:['roads-casing','roads','paths','railways'],buildings:['buildings'],landcover:['landcover','forest-rim','fields-outline'],shore:['shore-shadow','water-bank-soft','water-bank']}},center:[39.455,47.142],zoom:13.4,bearing:0,pitch:0,glyphs:'./fonts/{fontstack}/{range}.pbf',sources:{don:{type:'vector',tiles:['./tiles/{z}/{x}/{y}.pbf'],minzoom:9,maxzoom:15,bounds:[39.27,47.065,39.57,47.255],attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}},layers};
await mkdir(`${root}public`,{recursive:true});
style.metadata['paddle:groups'].landcover.push('canopy-shadows','canopy','canopy-light');
const revision=createHash('sha256').update(await readFile(`${root}public/stats.json`)).digest('hex').slice(0,10);
style.sources.don.tiles=style.sources.don.tiles.map(url=>`${url}?v=${revision}`);
style.metadata['paddle:revision']=revision;
await writeFile(`${root}public/style.json`,JSON.stringify(style,null,2));
console.log(`Wrote style with ${layers.length} layers`);
