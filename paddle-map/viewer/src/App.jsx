import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {DetailView} from './DetailView.jsx';
import { Stack, X, ArrowUpRight, ArrowCounterClockwise, ArrowClockwise, NavigationArrow, DownloadSimple, Info, Waves, MapTrifold, Plus, Minus } from '@phosphor-icons/react';
const locations=[{name:'Дельта Дона',center:[39.44091796875,47.12995075666306],zoom:13.8},{name:'Елизаветинская',center:[39.473179,47.141026],zoom:14.3},{name:'Азов',center:[39.425,47.117],zoom:14.3}];
const groupLabels={labels:'Названия',roads:'Дороги и тропы',buildings:'Застройка',landcover:'Растительность',shore:'Оформление берегов'};
const format=n=>n>=1048576?`${(n/1048576).toFixed(2)} МиБ`:`${(n/1024).toFixed(0)} КиБ`;
export function App(){
  if(new URLSearchParams(location.search).has('mobile'))return <MobilePreview/>;
  if(new URLSearchParams(location.search).has('detail'))return <DetailView/>;
  return <MapView/>;
}
function MobilePreview(){
  const [device,setDevice]=useState('ios');
  const [dims,setDims]=useState({width:390,height:844});
  function pick(next){setDevice(next);setDims(next==='ios'?{width:390,height:844}:{width:412,height:915})}
  return <main className="mobile-stage"><header className="preview-header"><div><strong>PADDLE</strong><span>Мобильный предпросмотр</span></div><a href={new URLSearchParams(location.search).has('detail')?'/?detail=1':'/'}>На весь экран ↗</a></header><div className="device-picker"><button aria-pressed={device==='ios'} onClick={()=>pick('ios')}>iOS · 390 × 844</button><button aria-pressed={device==='android'} onClick={()=>pick('android')}>Android · 412 × 915</button></div><div className="viewport-frame" style={{width:dims.width,height:dims.height}}><iframe title="Мобильная карта PADDLE" src={new URLSearchParams(location.search).has('detail')?'/?embedded=1&detail=1':'/?embedded=1'}/></div><p className="preview-caption">Предпросмотр в браузере. Вид сверху; поворот — кнопками на карте.<br/>Это проверка размеров экрана, а не нативных SDK iOS и Android.</p></main>;
}
function MapView(){
  const container=useRef(null),mapRef=useRef(null),variants=useRef(null);
  const [tone,setTone]=useState('cool');
  const embedded=new URLSearchParams(location.search).has('embedded');
  const [camera,setCamera]=useState({pitch:0,bearing:0});
  const [ready,setReady]=useState(false),[error,setError]=useState('');
  const [panel,setPanel]=useState(false),[stats,setStats]=useState(null),[art,setArt]=useState(null);
  const [mode,setMode]=useState('art'),[geometry,setGeometry]=useState(false);
  const [groups,setGroups]=useState(Object.fromEntries(Object.keys(groupLabels).map(k=>[k,true])));
  const [selected,setSelected]=useState(0),[zoom,setZoom]=useState(13.8);
  const [traffic,setTraffic]=useState({vectorBytes:0,rasterBytes:0});
  useEffect(()=>{
    let stopped=false,map;
    const json=url=>fetch(url).then(r=>{if(!r.ok)throw new Error(`${url}: ${r.status}`);return r.json()});
    Promise.all([json('/style-art-cool.json'),json('/stats.json'),json('/tile-sizes.json'),json('/art-cool/stats.json'),json('/art/stats.json')]).then(([style,details,sizes,artDetails,warmDetails])=>{
      if(stopped)return;
      setStats(details);setArt(artDetails);variants.current={cool:artDetails,warm:warmDetails};
      style.sources.warm={...style.sources.art,tiles:[`./raster/{z}/{x}/{y}.webp?v=${warmDetails.version}`]};
      style.layers.splice(style.layers.findIndex(l=>l.id==='art-basemap'),0,{id:'warm-basemap',type:'raster',source:'warm',layout:{visibility:'none'},paint:{'raster-fade-duration':0}});
      for(const source of Object.values(style.sources))if(source.tiles)source.tiles=source.tiles.map(t=>new URL(t,location.href).href.replaceAll('%7B','{').replaceAll('%7D','}'));
      style.glyphs=new URL(style.glyphs,location.href).href.replaceAll('%7B','{').replaceAll('%7D','}');
      const requested=new Set();const [w,s,e,n]=artDetails.bounds;
      map=new maplibregl.Map({container:container.current,style,center:embedded?[39.456,47.136]:locations[0].center,zoom:embedded?14.1:locations[0].zoom,pitch:0,bearing:0,maxPitch:55,dragRotate:true,touchZoomRotate:true,touchPitch:true,minZoom:11,maxZoom:16,maxBounds:[[w,s],[e,n]],attributionControl:false,renderWorldCopies:false,fadeDuration:150,transformRequest:(url)=>{
        const match=url.match(/\/(tiles|raster|raster-cool)\/(\d+\/\d+\/\d+)\.(pbf|webp)/);
        if(match){requested.add(`${match[1]}:${match[2]}`);const metrics={vectorBytes:0,rasterBytes:0};for(const key of requested){const [kind,id]=key.split(':');if(kind==='tiles')metrics.vectorBytes+=sizes[id]||0;else metrics.rasterBytes+=(kind==='raster-cool'?artDetails:warmDetails).sizes[id]||0;}window.__paddleMetrics=metrics;setTraffic(metrics);}
        return {url};
      }});
      mapRef.current=map;window.__paddleMap=map;
      map.addControl(new maplibregl.AttributionControl({compact:false}),'bottom-right');
      map.addControl(new maplibregl.ScaleControl({maxWidth:140,unit:'metric'}),'bottom-left');
      map.on('load',()=>{setReady(true);setZoom(map.getZoom());setError('')});
      map.on('zoomend',()=>setZoom(map.getZoom()));
      map.on('moveend',()=>setCamera({pitch:map.getPitch(),bearing:map.getBearing()}));
      map.on('error',e=>{console.error(e.error);setError('Часть карты не загрузилась. Обновите страницу или проверьте локальный сервер.')});
      map.on('click',e=>{
        const features=map.queryRenderedFeatures(e.point,{layers:['places','water-labels']});if(!features.length)return;
        const content=document.createElement('div'),title=document.createElement('strong');title.textContent=features[0].properties.name;content.append(title);
        const text=document.createElement('p');text.textContent='Подпись из OpenStreetMap';content.append(text);
        new maplibregl.Popup({closeButton:true,offset:12}).setLngLat(e.lngLat).setDOMContent(content).addTo(map);
      });
    }).catch(e=>{console.error(e);setError('Не удалось открыть карту. Проверьте сборку тайлов и стиля.')});
    return()=>{stopped=true;map?.remove();delete window.__paddleMap;delete window.__paddleMetrics;};
  },[]);
  function toggle(key){const value=!groups[key];setGroups({...groups,[key]:value});const map=mapRef.current;for(const id of map.getStyle().metadata['paddle:groups'][key])map.setLayoutProperty(id,'visibility',value?'visible':'none');}
  function changeMode(next){setMode(next);const map=mapRef.current;if(!map)return;map.setLayoutProperty('art-basemap','visibility',next==='art'&&tone==='cool'?'visible':'none');map.setLayoutProperty('warm-basemap','visibility',next==='art'&&tone==='warm'?'visible':'none');map.setLayoutProperty('geometry-check','visibility',next==='art'&&geometry?'visible':'none');}
  function changeTone(next){setTone(next);setMode('art');setArt(variants.current[next]);const map=mapRef.current;map.setLayoutProperty('art-basemap','visibility',next==='cool'?'visible':'none');map.setLayoutProperty('warm-basemap','visibility',next==='warm'?'visible':'none');map.setLayoutProperty('geometry-check','visibility',geometry?'visible':'none');}
  function toggleGeometry(){const value=!geometry;setGeometry(value);mapRef.current?.setLayoutProperty('geometry-check','visibility',value?'visible':'none');}
  function fly(i){setSelected(i);mapRef.current?.flyTo({...locations[i],duration:1000,essential:true})}
  function setView(pitch,bearing){mapRef.current?.easeTo({pitch,bearing,duration:450});}
  function resetView(){setSelected(0);mapRef.current?.flyTo({...locations[0],pitch:0,bearing:0,duration:800});}
  return <main className={`map-viewer ${embedded?'embedded-map':''}`}>
    <div ref={container} className="map-canvas" aria-label="Интерактивная карта дельты Дона"/>
    <header className="topbar"><a className="brand" href="#" onClick={e=>{e.preventDefault();fly(0)}} aria-label="Paddle — общий вид"><span>PADDLE</span><Waves size={30} weight="bold"/><small>БЛИЖЕ К ВОДЕ</small></a><div className="top-actions">{!embedded&&<><a className="mobile-preview-link" href="/?mobile=1&detail=1">Новые детали</a><a className="mobile-preview-link" href="/?mobile=1">Мобильное превью</a></>}<span className="vector-tag"><span/>{mode==='art'?'Художественный образец':'Векторная карта'}</span><button className={`round ${panel?'active':''}`} onClick={()=>setPanel(!panel)} aria-expanded={panel} aria-label={panel?'Закрыть слои':'Слои и информация'}>{panel?<X size={23}/>:<Stack size={25}/>}</button></div></header>
    <section className="location-card art-card"><div className="eyebrow">АЗОВ · ЕЛИЗАВЕТИНСКАЯ</div><h1>Дельта Дона</h1><p>Новый взгляд на знакомые берега.</p><div className="style-switch" aria-label="Оформление карты"><button disabled={!ready} aria-pressed={mode==='art'&&tone==='cool'} onClick={()=>changeTone('cool')}>Прохладная</button><button disabled={!ready} aria-pressed={mode==='art'&&tone==='warm'} onClick={()=>changeTone('warm')}>Тёплая</button><button disabled={!ready} aria-pressed={mode==='vector'} onClick={()=>changeMode('vector')}>Векторная</button></div></section>
    {panel&&<aside className="layers-panel" aria-label="Настройки карты"><div className="panel-heading"><h2>Ваша карта</h2><span>{mode==='art'?'WEBP + MVT':'MVT'}</span></div><p className="panel-caption">{mode==='art'?'Живописная подложка. Названия остаются векторными.':'Исходная векторная карта того же участка.'}</p><div className="camera-settings"><label>Наклон <output>{Math.round(camera.pitch)}°</output><input aria-label="Наклон карты" type="range" min="0" max="55" value={Math.round(camera.pitch)} disabled={!ready} onChange={e=>{const pitch=Number(e.target.value);setCamera({...camera,pitch});mapRef.current?.setPitch(pitch)}}/></label><p>Это настройка перспективы плоской подложки. Рельеф и здания не подняты.</p></div><div className="layer-options">{Object.entries(groupLabels).filter(([key])=>mode==='vector'||key==='labels').map(([key,label])=><label key={key}><span>{label}</span><input type="checkbox" checked={groups[key]} onChange={()=>toggle(key)} disabled={!ready}/></label>)}{mode==='art'&&<label><span>Сверить берега с OSM</span><input type="checkbox" checked={geometry} onChange={toggleGeometry}/></label>}</div><div className="stats-box"><div><span>{mode==='art'?'Растровый фрагмент · z11–14':'Векторный район · z9–15'}</span><strong>{mode==='art'?(art?format(art.totalBytes):'…'):(stats?format(stats.gzipBytes):'…')}</strong></div><div><span>Тайлов в наборе</span><strong>{mode==='art'?art?.tiles:stats?.tiles}</strong></div><div><span>Запрошено: растр*</span><strong>{format(traffic.rasterBytes)}</strong></div><div><span>Запрошено: вектор*</span><strong>{format(traffic.vectorBytes)}</strong></div><small>*Сумма размеров уникальных запрошенных файлов. Без учёта кеша, шрифтов и интерфейса. Растровый фрагмент меньше полного векторного района.</small></div><a className="download-link" href={mode==='art'?(tone==='cool'?'/style-art-cool.json':'/style-art.json'):'/style.json'} download={mode==='art'?'paddle-art-style.json':'paddle-style.json'}><DownloadSimple size={18}/>Скачать стиль<ArrowUpRight size={16}/></a><p className="source-note">{mode==='art'?'Подложка создана ImageGen по геометрии OSM. Мелкие берега и детали могли измениться. Это образец оформления, а не проверенная навигационная карта.':'Данные OSM: '+stats?.source.osmTimestamp?.slice(0,10)+'. Кроны и береговая кромка — декоративное оформление.'}</p></aside>}
    <div className="map-controls"><button className="round" aria-label="Приблизить" onClick={()=>mapRef.current?.zoomIn()} disabled={!ready}><Plus size={22}/></button><button className="round" aria-label="Отдалить" onClick={()=>mapRef.current?.zoomOut()} disabled={!ready}><Minus size={22}/></button><button className="round reset" aria-label="Вернуть общий вид" onClick={resetView} disabled={!ready}><ArrowCounterClockwise size={21}/></button></div>
    <div className="camera-dock" aria-label="Управление камерой"><button disabled={!ready} aria-label="Повернуть влево" onClick={()=>setView(mapRef.current.getPitch(),mapRef.current.getBearing()-30)}><ArrowCounterClockwise size={19}/></button><button disabled={!ready} aria-label="Север сверху" onClick={()=>setView(mapRef.current.getPitch(),0)}>N <span style={{display:'inline-block',transform:`rotate(${-camera.bearing}deg)`}}><NavigationArrow size={16}/></span></button><button disabled={!ready} aria-label="Повернуть вправо" onClick={()=>setView(mapRef.current.getPitch(),mapRef.current.getBearing()+30)}><ArrowClockwise size={19}/></button><button className={camera.pitch>5?'tilted':''} disabled={!ready} aria-pressed={camera.pitch>5} onClick={()=>setView(camera.pitch>5?0:40,mapRef.current.getBearing())}>Наклон</button></div>
    <footer className="bottom-bar"><div className="place-tabs" aria-label="Участки карты">{locations.map((l,i)=><button key={l.name} className={selected===i?'selected':''} onClick={()=>fly(i)} disabled={!ready}>{i===0&&<MapTrifold size={18}/>}<span>{l.name}</span></button>)}</div><span className="sample-note"><Info size={15}/>{mode==='art'?'Образец визуала':'Исходная геометрия'} · масштаб {zoom.toFixed(1)}</span></footer>
    {!ready&&!error&&<div className="loading" role="status">Открываем дельту Дона…</div>}{error&&<div className="map-error" role="alert">{error}</div>}
  </main>;
}
