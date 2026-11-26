'use strict';
const platformSymbols = new Map([
  ['youtube', 'yt-music'], ['qobuz', 'qobuz'], ['soundcloud.com', 'soundcloud'],
  ['vimeo.com', 'vimeo'], ['bandcamp.com', 'bandcamp'], ['dailymotion.com', 'dailymotion'],
  ['mixcloud.com', 'mixcloud'], ['archive.org', 'internet-archive'],
]);

function sourceMark(key, name, showName = false) {
  const mark = el('span', 'source-mark');
  const graphic = document.createElementNS(NS, 'svg');
  graphic.setAttribute('viewBox', '0 0 32 32');
  graphic.setAttribute('aria-hidden', 'true');
  graphic.setAttribute('focusable', 'false');
  const use = document.createElementNS(NS, 'use');
  use.setAttribute('href', '/static/brand/platforms.svg?v=0120#' + (platformSymbols.get(key) || 'website'));
  graphic.append(use);
  mark.append(graphic, el('span', showName ? '' : 'sr-only', name));
  if (!showName) mark.title = name;
  return mark;
}

function platformHeading(key, name) {
  const mark=sourceMark(key,name,!platformSymbols.has(key));
  if (platformSymbols.has(key)) {
    const asset=key.split('.')[0];
    const word=el('span','brand-word word-'+asset);
    word.setAttribute('aria-hidden','true');
    mark.append(word);
  }
  return mark;
}

for (const heading of document.querySelectorAll('h3[data-platform]')) {
  heading.replaceChildren(platformHeading(heading.dataset.platform, heading.textContent));
}

const Discovery={
  entries:[],sections:[], reference:null,
  reset(){
    this.entries=[];this.sections=[];this.reference=null;$('platform-options').close();
    $('feed-filter').value='all';$('search-switches').replaceChildren();$('add-dialog').close();$('ref-dialog').close();
    document.querySelectorAll('.extra-source').forEach(n=>n.remove());
  },
  name(key){return this.entries.find(s=>s.id===key)?.name||({youtube:'YouTube Music',qobuz:'Qobuz'})[key]||key;},
  async settings(){
    const rev=Profile.revision, data=await api('/api/sources');
    if(rev===Profile.revision&&Profile.owner())this.switches(data.sources);
  },
  switches(entries){
    const box=$('search-switches');box.replaceChildren();
    for(const src of entries){
      const label=el('label','toggle-line');const check=document.createElement('input');check.type='checkbox';check.checked=src.search;
      label.append(sourceMark(src.id, src.name, true), check);box.append(label);
      check.onchange=async()=>{const desired=check.checked,rev=Profile.revision;check.disabled=true;
        try{await api('/api/sources/'+encodeURIComponent(src.id)+'/search',{method:'PATCH',body:JSON.stringify({enabled:desired})});}
        catch(e){if(rev===Profile.revision){check.checked=!desired;toast(e.message);}}finally{check.disabled=false;}};
    }
  },
  sources(data){
    this.entries=data.sources;this.available=data.available;
    document.querySelectorAll('.extra-source').forEach(n=>n.remove());
    const grid=$('source-grid');
    for(const card of grid.querySelectorAll('[data-source]'))card.hidden=!data.sources.some(s=>s.id===card.dataset.source);
    for(const s of data.sources){
      if(s.id==='youtube')continue;
      if(s.id==='qobuz'){
        $('q-page-count').textContent=s.html?s.html+' referencias de tu página':'';
        document.querySelector('[data-remove-page="qobuz"]').hidden=!s.html;continue;
      }
      const card=el('article','source-box extra-source'),heading=el('h3');
      card.dataset.source=s.id;
      heading.append(platformHeading(s.id,s.name));
      card.append(el('header'),heading,
        el('p','','Pegá un enlace para comprobar el audio disponible o importá referencias de una página.'));
      for(const html of [true,false]){
        const label=el('label','file-control',html?'Subir HTML':'Cargar cookies .txt'),input=document.createElement('input');
        input.type='file';input.accept=html?'.html,.htm':'.txt';input.setAttribute('aria-label',label.textContent+' de '+s.name);
        if(!html)input.dataset.sessionFile='true';
        input.disabled=!html&&!data.can_import_sessions;label.append(input);card.append(label);input.onchange=()=>this.upload(s.id,input,html);
      }
      if(!data.can_import_sessions)card.append(el('small','','Conectá las cookies desde localhost en la computadora del servidor.'));
      if(s.session||s.html){const small=el('small','',[s.session?'Sesión conectada':'',s.html?s.html+' referencias':''].filter(Boolean).join(' · '));card.append(small);}
      for(const [enabled,ending,label] of [[s.session,'cookies','Desconectar cuenta'],[s.html,'html','Borrar referencias HTML']]){
        if(enabled){const b=el('button','text-action',label);b.type='button';b.onclick=()=>this.remove(s.id,ending);card.append(b);}
      }
      grid.append(card);
    }
    this.switches(this.entries);
    SourceOptions.headers(data.sources);
  },
  async upload(key,input,html){
    const file=input.files[0];input.value='';if(!file)return;
    if(!html&&file.size>60000){toast('El archivo supera el tamaño admitido.');return;}
    if(!html&&!SourceUI.settings?.can_import_sessions)return;
    const epoch=SourceUI.epoch;
    await SourceUI.action(html?'Importando referencias…':'Conectando tu sesión…',async()=>{
      const content=html?await readSourceHTML(file,key):await file.text();if(epoch!==SourceUI.epoch)return;
      const response=await api('/api/sources/'+encodeURIComponent(key)+(html?'/html':'/cookies'),{method:'PUT',body:JSON.stringify({content})});
      return html?response.imported+' referencias revisadas. Se suman a las anteriores, sin duplicados.':'Sesión conectada.';
    });
  },
  remove(key,ending){
    return SourceUI.action('Guardando cambios…',async()=>{
      await api('/api/sources/'+encodeURIComponent(key)+'/'+ending,{method:'DELETE',body:'{}'});return 'Listo.';
    });
  },
  feed(sections){
    this.sections=sections||[];
    const select=$('feed-filter'),prev=select.value;
    const keys=new Set([...this.entries.map(s=>s.id),...this.sections.flatMap(s=>s.items.map(t=>t.source||'youtube'))]);
    select.replaceChildren(new Option('Todo','all'),new Option('Separar por fuentes','group'),...Array.from(keys,k=>new Option(this.name(k),k)));
    select.value=keys.has(prev)||prev==='group'?prev:'all';this.paint();
  },
  paint(){
    const root=$('home-sections'),filter=$('feed-filter').value;
    root.replaceChildren();const seen=new Set(),items=[];
    // Interleave shelves so the first screen can contain more than one source.
    const max=Math.max(0,...this.sections.map(s=>s.items.length));
    for(let i=0;i<max;i++)for(const section of this.sections){
      const t=section.items[i];if(!t)continue;const key=t.source||(t.id?.startsWith('qb:')?'qobuz':'youtube'),id=key+'|'+t.id;
      if(seen.has(id)||(filter!=='all'&&filter!=='group'&&key!==filter))continue;
      seen.add(id);items.push({...t,source:key,reason:section.title==='Por lo que escuchás y descargás'?section.title:''});
    }
    if(!items.length){
      const empty=el('div','home-empty'),text=el('p','',filter==='all'||filter==='group'?'Escuchá una rola, descargala o agregá una fuente para recibir recomendaciones.':'Todavía no hay recomendaciones de '+this.name(filter)+'. Importá su página o descargá una pista.');
      const b=el('button','text-action','Ir a Fuentes →');b.type='button';b.onclick=()=>navigate('fuentes');empty.append(text,b);root.append(empty);return;
    }
    if(filter==='all'||filter==='group'){
      const pools=new Map();
      for(const t of items){
        if(!pools.has(t.source))pools.set(t.source,[]);
        pools.get(t.source).push(t);
      }
      items.length=0;
      const ordered=[...pools.keys()].sort((a,b)=>Number(!!this.entries.find(s=>s.id===b)?.favorite)-Number(!!this.entries.find(s=>s.id===a)?.favorite));
      while(ordered.some(k=>pools.get(k).length) && items.length<72){
        for(const key of ordered){
          const weight=this.entries.find(s=>s.id===key)?.favorite?3:1;
          items.push(...pools.get(key).splice(0,Math.min(weight,72-items.length)));
        }
      }
    }
    const favored=new Set((this.favorites||[]).map(n=>n.toLocaleLowerCase()));
    const favoredTrack=t=>(t.artists?.map(a=>a.name)||t.artist?.split(';')||[]).some(n=>favored.has(n.trim().toLocaleLowerCase()));
    const regular=items.filter(t=>!favoredTrack(t)), picks=items.filter(favoredTrack);
    items.length=0;
    while(regular.length||picks.length){items.push(...picks.splice(0,1),...regular.splice(0,3));}
    const groups=new Map();
    for(const item of items){
      const kind=item.type==='album'?'album':item.type==='song'?'song':null;if(!kind)continue;
      const key=(filter==='group'?item.source:'all')+'|'+kind;if(!groups.has(key)){
        const section=el('section','home-shelf recommendation-shelf'),header=el('header','recommendation-heading');
        const heading=el('h3','',kind==='album'?'Álbumes para descubrir':'Para escuchar ahora');
        header.append(heading);
        if(filter==='group')header.append(sourceMark(item.source,this.name(item.source),true));
        const grid=el('div','record-grid recommendation-grid');
        grid.setAttribute('role','list');grid.setAttribute('aria-label',heading.textContent);
        section.append(header,grid);root.append(section);groups.set(key,grid);
      }
      const card=RecordCards.card(item);card.setAttribute('role','listitem');groups.get(key).append(card);
    }
    // Stable shelf order regardless of whether the first recommendation was an album.
    [...root.children].sort((a,b)=>Number(a.querySelector('.record-grid')?.getAttribute('aria-label').startsWith('Álbumes'))-Number(b.querySelector('.record-grid')?.getAttribute('aria-label').startsWith('Álbumes'))).forEach(n=>root.append(n));
  },
  async openReference(item,stream=false){
    if(item.source!=='qobuz')return openPreview({url:item.url});
    const q=item.url.match(/\/track\/(?:[^/?]+\/)?(\d+)(?:[/?#]|$)/);
    const album=item.url.match(/\/album\/(?:[^/?]+\/)?([A-Za-z0-9]+)(?:[/?#]|$)/);
    if(album){
      const result=await api('/api/sources/qobuz/reference?album='+encodeURIComponent(album[1])).catch(()=>null);
      if(result?.album)return openPreview({type:'album',id:result.album});
    }
    if(q){const data=await api('/api/sources/qobuz/reference?id='+encodeURIComponent(q[1])).catch(()=>null);
      if(data?.track)return stream?Player.stream({...item,id:data.track,reference:false}):openPreview({type:'song',id:data.track});}
    this.reference=item;$('ref-title').textContent=item.title;
    $('ref-copy').textContent='Tu HTML guardó una referencia de Qobuz. Podés buscar las pistas disponibles en tu biblioteca o abrir la ficha original.';
    $('ref-site').href=item.url;$('ref-dialog').showModal();
  }
};
window.Discovery=Discovery;
for (const dialog of document.querySelectorAll('dialog[data-light-dismiss]')) {
  if ('closedBy' in dialog) {
    dialog.closedBy = 'any';
    continue;
  }
  // Older browsers deliver backdrop events to the dialog itself, including taps.
  const onBackdrop = event => {
    if (event.target !== dialog) return false;
    const rect = dialog.getBoundingClientRect();
    return event.clientX < rect.left || event.clientX >= rect.right ||
           event.clientY < rect.top || event.clientY >= rect.bottom;
  };
  let startedOutside = false;
  dialog.addEventListener('pointerdown', event => {
    startedOutside = event.isPrimary && event.button === 0 && onBackdrop(event);
  });
  dialog.addEventListener('pointercancel', () => { startedOutside = false; });
  dialog.addEventListener('click', event => {
    if (startedOutside && onBackdrop(event)) dialog.close();
    startedOutside = false;
  });
}
$('feed-filter').onchange=()=>Discovery.paint();
$('ref-search').onclick=()=>{const item=Discovery.reference;$('ref-dialog').close();$('query').value=item.title;$('search-form').requestSubmit();};
document.querySelector('[data-page-file="qobuz"]').onchange=e=>Discovery.upload('qobuz',e.target,true);
document.querySelector('[data-remove-page="qobuz"]').onclick=()=>Discovery.remove('qobuz','html');
function showCustomSourceField(custom) {
  $('custom-source-wrap').hidden = !custom;
  $('source-site').disabled = !custom;
  $('source-site').required = custom;
}
$('add-source').onclick=()=>{
  const choices = $('source-choices');
  choices.replaceChildren();
  const options = [...(Discovery.available || []), {id:'custom', name:'Otro sitio compatible…'}];
  for (const [index, source] of options.entries()) {
    const label = el('label', 'source-choice');
    const radio = document.createElement('input');
    radio.type = 'radio'; radio.name = 'platform'; radio.value = source.id;
    radio.checked = index === 0;
    label.append(radio, sourceMark(source.id, source.name, true));
    choices.append(label);
  }
  showCustomSourceField(options[0].id==='custom');$('source-site').value='';$('add-error').textContent='';$('add-dialog').showModal();
};
$('source-choices').onchange=event=>showCustomSourceField(event.target.value==='custom');
$('source-add-form').onsubmit=async e=>{
  e.preventDefault();const choice=e.currentTarget.elements.platform.value;
  const site=choice==='custom'?$('source-site').value:choice,rev=Profile.revision;
  e.submitter.disabled=true;
  try{await post('/api/sources/add',{site});if(rev===Profile.revision){$('add-dialog').close();await SourceUI.load();}}
  catch(err){if(rev===Profile.revision)$('add-error').textContent=err.message;}finally{e.submitter.disabled=false;}
};
