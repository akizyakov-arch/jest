import {useEffect,useRef,useState} from 'react';
import maplibregl from 'maplibre-gl';
import {Stack,X,Waves,Plus,Minus,ArrowCounterClockwise,ArrowClockwise} from '@phosphor-icons/react';
import './detail.css';

export function DetailView(){
 const host=useRef(null),mapRef=useRef(null),ref=useRef(null);
 const [ready,setReady]=useState(false),[detail,setDetail]=useState(true),[panel,setPanel]=useState(false),[error,setError]=useState('');
 const [zoom,setZoom]=useState(14),[stats,setStats]=useState(null),[labels,setLabels]=useState(true),[boundary,setBoundary]=useState(true);
 const [limit,setLimit]=useState(15),[requested,setRequested]=useState(0);
 const embedded=new URLSearchParams(location.search).has('embedded');
 useEffect(()=>{
  let stopped=false,map;
  const json=url=>fetch(url).then(r=>{if(!r.ok)throw Error(`${url}: ${r.status}`);return r.json()});
  Promise.all([json('/style-detail.json'),json('/detail/stats.json')]).then(([style,info])=>{
   if(stopped)return;ref.current=info;setStats(info);
   // MapLibre camera uses 512px world tiles. Raster z16 at 256px reaches
   // 1 source pixel per physical display pixel at camera zoom 15-log2(DPR).
   const max=15-Math.log2(Math.max(1,window.devicePixelRatio));setLimit(max);
   const initial=Math.max(12.5,max-1);
   // Request enough raster samples for high-density screens too.
   style.sources.detail.tileSize=256/Math.pow(2,Math.ceil(Math.log2(Math.max(1,window.devicePixelRatio-0.001))));
   for(const source of Object.values(style.sources))if(source.tiles)source.tiles=source.tiles.map(t=>new URL(t,location.href).href.replaceAll('%7B','{').replaceAll('%7D','}'));
   style.glyphs=new URL(style.glyphs,location.href).href.replaceAll('%7B','{').replaceAll('%7D','}');
   const seen=new Set();
   const bounds=style.sources.don.bounds;
   map=new maplibregl.Map({container:host.current,style,center:info.center,zoom:initial,pitch:0,maxPitch:0,bearing:0,minZoom:12.5,maxZoom:max,dragRotate:true,touchZoomRotate:true,touchPitch:false,renderWorldCopies:false,maxBounds:[[bounds[0],bounds[1]],[bounds[2],bounds[3]]],attributionControl:false,transformRequest:url=>{
    const key=url.match(/\/raster-detail\/(\d+\/\d+\/\d+)\.webp/)?.[1];
    if(key){seen.add(key);setRequested([...seen].reduce((sum,k)=>sum+(info.sizes[k]||0),0));}
    return {url};
   }});
   mapRef.current=map;window.__paddleDetail=map;
   map.addControl(new maplibregl.AttributionControl({compact:true}),'bottom-right');
   map.addControl(new maplibregl.ScaleControl({maxWidth:110,unit:'metric'}),'bottom-left');
   map.on('load',()=>{setReady(true);setZoom(map.getZoom())});map.on('zoomend',()=>setZoom(map.getZoom()));
   map.on('error',e=>{console.error(e.error);setError('Не удалось загрузить часть карты.')});
  }).catch(e=>{console.error(e);setError('Не удалось открыть детальный образец.')});
  return()=>{stopped=true;map?.remove();delete window.__paddleDetail;};
 },[]);
 const fly=z=>mapRef.current?.easeTo({center:ref.current.center,zoom:Math.min(z,limit),pitch:0,duration:650});
 const choose=value=>{setDetail(value);mapRef.current?.setLayoutProperty('detail-art','visibility',value?'visible':'none')};
 const rotate=delta=>mapRef.current?.easeTo({bearing:mapRef.current.getBearing()+delta,duration:350});
 return <main className="detail-view">
  <div ref={host} className="detail-map" aria-label="Детальный участок карты, вид сверху"/>
  <header className="detail-header"><div className="detail-brand"><span>PADDLE</span><Waves size={23}/><small>ОБЪЁМ В ДЕТАЛЯХ</small></div><button className="round" aria-label={panel?'Закрыть настройки':'Настройки детализации'} onClick={()=>setPanel(!panel)}>{panel?<X size={22}/>:<Stack size={23}/>}</button></header>
  <div className="detail-badge">{detail?'Детальный участок':'Прежняя подложка'}<span>Вид сверху · {zoom.toFixed(1)}</span></div>
  {panel&&<aside className="detail-panel"><h2>Детализация</h2><p>Новые кроны, тени и фактура берега. Камера остаётся строго сверху.</p><label>Названия<input type="checkbox" checked={labels} onChange={e=>{setLabels(e.target.checked);for(const id of ['places','water-labels'])mapRef.current.setLayoutProperty(id,'visibility',e.target.checked?'visible':'none')}}/></label><label>Граница образца<input type="checkbox" checked={boundary} onChange={e=>{setBoundary(e.target.checked);mapRef.current.setLayoutProperty('detail-frame','visibility',e.target.checked?'visible':'none')}}/></label><dl><dt>Новый набор</dt><dd>{stats?(stats.totalBytes/1024).toFixed(0):'…'} КиБ</dd><dt>Тайлы</dt><dd>{stats?.tiles??'…'} · z12–16</dd><dt>Запрошено*</dt><dd>{(requested/1024).toFixed(0)} КиБ</dd><dt>Предел приближения</dt><dd>{limit.toFixed(2)}</dd></dl><small>*Сумма размеров тайлов участка. Без прежней подложки, подписей, кеша и интерфейса.</small><p>Сгенерированные детали — художественная интерпретация, не съёмка отдельных деревьев. За рамкой остаётся прежняя карта.</p><a href="/">Открыть весь район</a>{!embedded&&<a href="/?mobile=1&detail=1">Мобильное превью</a>}</aside>}
  <div className="detail-navigation"><button className="round" aria-label="Приблизить" disabled={!ready||zoom>=limit-.01} onClick={()=>mapRef.current.zoomIn()}><Plus size={22}/></button><button className="round" aria-label="Отдалить" disabled={!ready} onClick={()=>mapRef.current.zoomOut()}><Minus size={22}/></button><button className="round" aria-label="Повернуть влево" disabled={!ready} onClick={()=>rotate(-30)}><ArrowCounterClockwise size={20}/></button><button className="round" aria-label="Повернуть вправо" disabled={!ready} onClick={()=>rotate(30)}><ArrowClockwise size={20}/></button></div>
  <footer className="detail-footer"><div className="detail-scale"><button disabled={!ready} onClick={()=>fly(Math.max(12.5,limit-1))}>Общий вид</button><button disabled={!ready} onClick={()=>fly(limit)}>Ближе к берегу</button></div><div className="detail-compare"><button disabled={!ready} aria-pressed={!detail} onClick={()=>choose(false)}>Раньше</button><button disabled={!ready} aria-pressed={detail} onClick={()=>choose(true)}>Новые детали</button></div><small>{zoom>=limit-.01?'Максимум детализации для этого экрана':'Пунктиром отмечен участок с новыми деталями'}</small></footer>
  {!ready&&!error&&<div className="loading" role="status">Загружаем детальный участок…</div>}{error&&<div className="map-error" role="alert">{error}</div>}
 </main>;
}
