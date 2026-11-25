'use strict';

// Read large browser exports incrementally. Keep complete music links and rendered tiles,
// including ones near the end, without sending page-sized scripts or embedded images.
async function readSourceHTML(file,key) {
  if (file.size <= 6*1024*1024) return file.text();
  const decoder=new TextDecoder(), fragments=new Set();
  let tail='', kept=0;
  for(let offset=0;offset<file.size;offset+=1024*1024){
    const bytes=await file.slice(offset,offset+1024*1024).arrayBuffer();
    const chunk=tail+decoder.decode(bytes,{stream:offset+bytes.byteLength<file.size});
    const patterns=[/<ytmusic-(two-row-item-renderer|responsive-list-item-renderer|grid-media)\b[^>]*>[\s\S]{0,48000}?<\/ytmusic-\1>/gi,
                    /<a\b[^>]{0,8000}\bhref\s*=[^>]{1,6000}>[\s\S]{0,8000}?<\/a\s*>/gi,
                    /"(?:musicResponsiveListItemRenderer|musicTwoRowItemRenderer)"\s*:\s*\{[^\n]{1,12000}/g];
    for(const pattern of patterns)for(const m of chunk.matchAll(pattern)){
      if(m[0].startsWith('<a')){
        const href=m[0].match(/\bhref\s*=\s*["']([^"']+)/i)?.[1];
        if(!href)continue;
        try{
          const host=key==='youtube'?'music.youtube.com':key==='qobuz'?'qobuz.com':key;
          const url=new URL(href,'https://'+host);
          if(!['http:','https:'].includes(url.protocol) || !(url.hostname===host || url.hostname.endsWith('.'+host)))continue;
          if(key==='youtube' && !/^\/(watch|channel|browse|playlist)(\/|$)/.test(url.pathname))continue;
          if(key==='qobuz' && !/\/(album|track|interpreter|artist)\//.test(url.pathname))continue;
        }catch{continue;}
      }
      if(fragments.has(m[0]))continue;
      fragments.add(m[0]);kept+=m[0].length;
      if(kept>=2_000_000||fragments.size>=4000)return [...fragments].join('\n');
    }
    tail=chunk.slice(-50000);
  }
  return [...fragments].join('\n');
}

const sourceDescriptions={
  youtube:'YouTube Music se guarda en MP3. Podés importar tu Inicio o conectar tu sesión para recibir sugerencias.',
  qobuz:'Podés guardar tus compras en FLAC o MP3 según la edición disponible en tu cuenta. El HTML sirve para descubrir títulos.',
  'soundcloud.com':'Cuando el artista habilita la descarga del original, su formato depende del archivo que subió.',
  'bandcamp.com':'Bandcamp ofrece varias versiones de las compras. Cada enlace muestra los formatos a los que tenés acceso.',
  'archive.org':'Cada elemento de Internet Archive reúne sus propios archivos originales y derivados.',
  'vimeo.com':'La disponibilidad del original depende del video y de los permisos que eligió su creador.',
  'dailymotion.com':'Music Ingest revisa el audio disponible en el video que pegás.',
  'mixcloud.com':'La disponibilidad depende del enlace. El modo sin conexión de la app de Mixcloud guarda contenido dentro de esa app.'
};

const SourceOptions={
  key:null, saving:false,
  headers(sources){
    for(const card of $('source-grid').querySelectorAll('[data-source]')){
      const source=sources.find(s=>s.id===card.dataset.source);
      if(!source)continue;
      const badges=el('div','format-strip');badges.setAttribute('aria-label','Formatos');
      for(const f of ['mp3','flac','wav','alac','aac','opus','ogg','aiff']){
        const on=source.enabled_formats.includes(f), supported=source.formats.includes(f);
        const b=el('span','format-chip',f.toUpperCase());
        b.dataset.format=f;b.dataset.on=String(on);
        b.title=f.toUpperCase()+' · '+(on?'Habilitado':supported?'Desactivado':'Sin disponibilidad confirmada');
        b.setAttribute('aria-label',b.title);badges.append(b);
      }
      const open=el('button','source-more','•••');
      open.type='button';open.setAttribute('aria-label','Opciones de '+source.name);open.setAttribute('aria-haspopup','dialog');
      open.onclick=()=>{this.key=source.id;this.paint();$('platform-options').showModal();};
      card.querySelector('header').replaceChildren(badges,open);
    }
  },
  button(label,action,cls='quiet'){
    const b=el('button',cls,label);b.type='button';b.onclick=action;return b;
  },
  paint(){
    const src=Discovery.entries.find(s=>s.id===this.key);
    if(!src){$('platform-options').close();return;}
    const body=$('platform-options-body');
    $('platform-options-title').textContent=src.name;
    body.replaceChildren();status('platform-options-status','');
    const flag=(title,checked,field,fmt)=>{
      const label=el('label','option-line'),input=document.createElement('input');
      input.type='checkbox';input.checked=checked;input.dataset.option=fmt||field;
      input.disabled=fmt==='mp3'&&src.formats.length===1;
      input.onchange=()=>this.set(field,input.checked,fmt);
      label.append(input,el('span','',title));return label;
    };
    if(src.formats.length){
      const formats=el('fieldset','option-formats');formats.append(el('legend','','Formatos de descarga'));
      for(const f of src.formats)formats.append(flag(f.toUpperCase(),src.enabled_formats.includes(f),'format',f));
      body.append(formats);
    }
    body.append(flag('Mostrar sugerencias en Inicio',src.home,'home'));
    const favorite=this.button('',()=>this.set('favorite',!src.favorite),'favorite-line');
    favorite.dataset.option='favorite';favorite.setAttribute('aria-pressed',String(src.favorite));
    favorite.append(el('span','star',src.favorite?'★':'☆'),el('span','','Favorito'));
    const hint=el('small','favorite-hint','Verás más sugerencias de esta fuente en Inicio.');
    hint.id='source-favorite-hint';favorite.setAttribute('aria-describedby',hint.id);
    favorite.title=hint.textContent;
    const favBox=el('div','favorite-wrap');favBox.append(favorite,hint);body.append(favBox);
    const info=el('details','source-information');info.append(el('summary','','Ayuda de esta fuente'));
    for(const [title,kind] of [['Sobre la fuente','general'],['Cómo subir HTML','html'],['Cómo conectar cookies','cookies']]){
      const details=el('details');details.append(el('summary','',title));info.append(details);
      if(kind==='general'){
        details.append(el('p','',sourceDescriptions[src.id]||'Pegá un enlace para revisar la pista. Los formatos aparecen en esta tarjeta a medida que se verifican tus descargas.'));
      }else if(['qobuz','youtube'].includes(src.id)){
        const guide=kind==='cookies'?src.id:(src.id==='qobuz'?'qhtml':'html');
        details.append(this.button('Ver los tres pasos',()=>SourceGuide.open(guide),'text-action'));
      }else{
        details.append(el('p','',kind==='html'?'Abrí la página en tu navegador, cargá las pistas y guardala con Ctrl + S (⌘ + S en Mac). En la tarjeta elegí Subir HTML.':
          'En esa plataforma iniciá sesión y exportá solo las cookies del sitio como cookies.txt en formato Netscape. En tu servidor abrí localhost y elegí Cargar cookies .txt.'));
      }
    }
    body.append(info,this.button('Eliminar fuente',()=>this.confirmRemove(src,1),'remove-source'));
  },
  async set(field,enabled,format){
    if(this.saving)return;
    const key=this.key,rev=Profile.revision,body=$('platform-options-body');
    this.saving=true;body.inert=true;
    try{
      await api('/api/sources/'+encodeURIComponent(key)+'/options',{method:'PATCH',body:JSON.stringify({field,enabled,format})});
      if(rev===Profile.revision){await SourceUI.load();if(this.key===key){this.paint();body.querySelector('[data-option="'+(format||field)+'"]')?.focus();}}
    }catch(e){if(rev===Profile.revision){this.paint();status('platform-options-status',e.message,true);}}
    finally{this.saving=false;body.inert=false;}
  },
  confirmRemove(src,step){
    const body=$('platform-options-body');
    const msg=step===1?'¿Querés quitar '+src.name+' de esta biblioteca?':'¿Estás seguro de eliminar '+src.name+'? Se quitan su conexión y sus sugerencias. Conservás los archivos descargados.';
    const cancel=this.button('Cancelar',()=>this.paint());
    const next=this.button(step===1?'Continuar':'Sí, eliminar fuente',async()=>{
      if(step===1){this.confirmRemove(src,2);return;}
      const rev=Profile.revision;body.inert=true;
      try{
        await api('/api/sources/'+encodeURIComponent(src.id),{method:'DELETE',body:JSON.stringify({confirm:src.id})});
        if(rev===Profile.revision){$('platform-options').close();await SourceUI.load();$('add-source').focus();}
      }catch(e){status('platform-options-status',e.message,true);}
      finally{body.inert=false;}
    },'remove-source');
    body.replaceChildren(el('p','',msg),cancel,next);cancel.focus();
  },
};
$('platform-options').addEventListener('close',()=>{
  const card=[...$('source-grid').querySelectorAll('[data-source]')].find(c=>c.dataset.source===SourceOptions.key&&!c.hidden);
  card?.querySelector('.source-more')?.focus();
  SourceOptions.key=null;
});
