'use strict';
const Artists={
  request:0,saved:[],savedRevision:-1,savedRead:0,savedPromise:null,bookmarking:new Set(),
  reset(){this.close();this.saved=[];this.savedRevision=-1;this.savedRead++;this.savedPromise=null;this.bookmarking.clear();$('saved-artists')?.replaceChildren();},
  identity(artist){return {name:artist.title||artist.artist||'',source:artist.source||'youtube',id:(artist.source||'youtube')==='youtube'&&artist.id?.startsWith('UC')?artist.id:'',cover:artist.cover||''};},
  findSaved(artist){const meta=this.identity(artist),norm=s=>String(s||'').trim().toLocaleLowerCase();return this.saved.find(s=>s.source===meta.source&&(s.id&&meta.id?s.id===meta.id:norm(s.title)===norm(meta.name)));},
  async loadSaved(force=false){
    if(!Profile.user||!Profile.library)return [];
    if(!force&&this.savedRevision===Profile.revision)return this.saved;
    if(!force&&this.savedPromise)return this.savedPromise;
    const rev=Profile.revision,read=++this.savedRead;
    const promise=(async()=>{const data=await api('/api/listening/artists');if(rev!==Profile.revision||read!==this.savedRead)return [];this.saved=data.items||[];this.savedRevision=rev;this.paintHearts();return this.saved;})();
    this.savedPromise=promise;
    try{return await promise;}finally{if(this.savedPromise===promise)this.savedPromise=null;}
  },
  paintHearts(){for(const button of document.querySelectorAll('.artist-bookmark')){
    const saved=!!this.findSaved(button.artistRef);button.classList.toggle('is-active',saved);button.setAttribute('aria-pressed',String(saved));
    const label=saved?'Quitar de tus artistas':'Guardar en Artistas';button.title=label;button.setAttribute('aria-label',label);
    button.replaceChildren(ListeningCollection.icon('heart'),el('span','',saved?'Guardado en Artistas':'Guardar en Artistas'));
  }},
  heart(artist){const button=el('button','quiet artist-bookmark');button.type='button';button.artistRef=artist;button.title='Guardar en Artistas';button.onclick=()=>this.bookmark(artist).catch(e=>toast(e.message));
    const saved=!!this.findSaved(artist);button.classList.toggle('is-active',saved);button.setAttribute('aria-pressed',String(saved));button.append(ListeningCollection.icon('heart'),el('span','',saved?'Guardado en Artistas':'Guardar en Artistas'));
    this.loadSaved().then(()=>this.paintHearts()).catch(()=>{});return button;
  },
  async bookmark(artist,enabled=null,notify=true){
    const rev=Profile.revision,meta=this.identity(artist),key=meta.source+'|'+(meta.id||meta.name.toLocaleLowerCase());
    if(this.bookmarking.has(key))return;this.bookmarking.add(key);
    try{
      await this.loadSaved();if(rev!==Profile.revision)return;
      const saved=this.findSaved(artist);
      if(enabled===true&&saved||enabled===false&&!saved)return;
      if(saved){await api('/api/listening/artists/'+encodeURIComponent(saved.key),{method:'DELETE'});if(rev!==Profile.revision)return;this.saved=this.saved.filter(s=>s.key!==saved.key);}
      else{const added=await api('/api/listening/artists',{method:'PUT',body:JSON.stringify(meta)});if(rev!==Profile.revision)return;this.saved=[added,...this.saved.filter(s=>s.key!==added.key)];}
      this.savedRead++;this.savedPromise=null;this.savedRevision=rev;this.paintHearts();if(state.page==='favoritos')this.paintSaved();
      if(notify)toast(saved?'Quitado de tus artistas.':'Guardado en Artistas.');
    }finally{if(rev===Profile.revision)this.bookmarking.delete(key);}
  },
  async saveSelected(items,current){
    const artists=new Map();
    for(const item of items){
      const names=item.type==='artist'?[{name:item.title,id:item.id}]:item.artists?.length?item.artists:RecordCards.artistNames(item).map(name=>({name,id:''}));
      for(const person of names){if(!person.name)continue;const artist={type:'artist',id:person.id||'',title:person.name,source:item.source||'youtube',cover:item.type==='artist'?item.cover:''},meta=this.identity(artist);
        artists.set(meta.source+'|'+(meta.id||meta.name.toLocaleLowerCase()),artist);}
    }
    if(!artists.size)throw Error('No encontramos artistas en esta selección.');
    for(const artist of artists.values()){if(!current())return;await this.bookmark(artist,true,false);}
    if(current())toast(artists.size===1?'Artista guardado.':'Artistas guardados.');
  },
  paintSaved(){
    const root=$('saved-artists');if(!root)return;root.replaceChildren();
    if(!this.saved.length){root.append(el('p','empty-state','Guardá artistas con el corazón de su perfil o desde el menú de tres puntos. No activa descargas.'));return;}
    const grid=el('div','record-grid');for(const artist of this.saved)grid.append(RecordCards.card({...artist,id:artist.id||'artist:'+artist.key,type:'artist'}));root.append(grid);
  },
  async showSaved(force=false){
    const rev=Profile.revision;status('saved-artists-status','Cargando tus artistas…');
    try{await this.loadSaved(force);if(rev!==Profile.revision||state.page!=='favoritos')return;this.paintSaved();status('saved-artists-status','');}
    catch(e){if(rev===Profile.revision)status('saved-artists-status',e.message,true);}
    if(Profile.owner())AutomationUI.load().catch(()=>{});
  },
  async openNamed(name,item){
    if(state.page!=='buscar')navigate('buscar');closeSuggestions();
    const request=++this.request,revision=Profile.revision,panel=$('artist-panel');
    panel.hidden=false;$('results').hidden=true;$('results-heading').hidden=true;$('welcome').hidden=true;
    const feedback=el('p','inline-status','Cargando artista…');feedback.setAttribute('role','status');panel.replaceChildren(feedback);panel.scrollIntoView({block:'start'});
    try{
      const data=await RecordCards.collection('artist',name,item);if(request!==this.request||revision!==Profile.revision)return;
      if(data.open?.id)return this.open(data.open.id);
      const artist={id:'',type:'artist',source:item.source||'youtube',title:data.title||name,cover:data.cover||''};
      const back=RecordCards.button('quiet artist-back','← Volver a resultados',()=>this.close()),hero=el('div','artist-hero'),info=el('div');
      info.append(el('span','eyebrow','ARTISTA'),el('h2','',artist.title),this.heart(artist));hero.append(cover(artist.cover),info);panel.replaceChildren(back,hero);
      const songs=data.songs||[],albums=data.albums||[];
      for(const [title,items] of [['Canciones',songs],['Álbumes',albums]])if(items.length){panel.append(el('h3','artist-section-title',title));const grid=el('div','record-grid');items.forEach(t=>grid.append(RecordCards.card(t)));panel.append(grid);}
      if(!songs.length&&!albums.length)panel.append(el('p','section-copy','Todavía no hay música disponible de este artista en esta fuente. Podés guardarlo en Artistas para volver después.'));
    }catch(e){if(request===this.request&&revision===Profile.revision){feedback.textContent=e.message;feedback.classList.add('error');}}
  },
  close(){this.request++;$('artist-panel').hidden=true;$('artist-panel').replaceChildren();$('results').hidden=false;$('results-heading').hidden=false;},
  async open(id){
    if(state.page!=='buscar')navigate('buscar');
    closeSuggestions();const request=++this.request,revision=Profile.revision,panel=$('artist-panel');
    panel.hidden=false;$('results').hidden=true;$('results-heading').hidden=true;$('welcome').hidden=true;panel.replaceChildren();
    const back=el('button','quiet artist-back','← Volver a resultados');back.type='button';back.addEventListener('click',()=>this.close());panel.append(back);panel.scrollIntoView({block:'start'});
    const feedback=el('p','inline-status','Cargando artista…');feedback.setAttribute('role','status');panel.append(feedback);
    try{
      const artist=await api('/api/artists/'+encodeURIComponent(id));if(request!==this.request||revision!==Profile.revision)return;feedback.remove();
      const hero=el('div','artist-hero'),info=el('div');info.append(el('span','eyebrow','ARTISTA'),el('h2','',artist.title||'Artista'),this.heart({...artist,source:'youtube'}));
      hero.append(cover(artist.cover),info);panel.append(hero);
      if(Profile.owner()){
        const box=el('section','profile-card artist-follow'),heading=el('h3','','¿Querés que sus próximas rolas lleguen solas?');
        const explanation=el('p','section-copy','Guardamos sus próximos álbumes y sencillos automáticamente. Marcá el check si también querés lo que ya tiene publicado.');
        const follow=el('button','primary','Mantener su música al día');follow.type='button';follow.disabled=true;
        const feedback=el('p','section-copy','Revisando si ya lo seguís…');feedback.setAttribute('role','status');
        const includeLabel=el('label','include-catalogue'),include=document.createElement('input');include.type='checkbox';include.dataset.includeExisting='true';includeLabel.append(include,el('span','','Incluir también toda su música actual'));
        box.append(heading,explanation,includeLabel,follow,feedback);panel.append(box);
        let source=null;
        const current=()=>request===this.request&&revision===Profile.revision&&Profile.owner();
        const render=()=>{
          if(!current())return;
          include.disabled=!!source?.include_existing;if(source?.include_existing)include.checked=true;
          follow.disabled=!!source?.enabled&&(!include.checked||!!source?.include_existing);
          follow.textContent=source?.enabled&&include.checked&&!source?.include_existing?'Descargar su música actual y mantener al día':source?.enabled?'✓ Su música se mantiene al día':source?'Reanudar actualización automática':'Mantener su música al día';
          feedback.textContent=include.checked?'También incluiremos los álbumes y sencillos disponibles de su catálogo actual. Si son muchos, se descargarán por turnos.':source?.enabled?'Listo. Revisamos sus lanzamientos con la frecuencia de Playlists → Revisiones automáticas.':source?'Lo tenés en pausa. Reanudalo para volver a recibir novedades.':'La primera revisión toma su catálogo actual como punto de partida; no descarga la discografía completa.';
        };
        include.addEventListener('change',render);
        api('/api/following').then(data=>{
          if(!current())return;
          source=data.items.find(item=>item.kind==='artist'&&item.source_id===artist.id)||null;render();
        }).catch(()=>{if(current()){follow.disabled=false;feedback.textContent='Podés activar la actualización. Si ya lo seguís, no lo agregamos dos veces.';}});
        follow.addEventListener('click',async()=>{
          follow.disabled=true;
          try{
            const added=await post('/api/following',{kind:'artist',source:artist.id,include_existing:include.checked});
            if(!current())return;
            if(source&&!source.enabled)await api('/api/following/'+encodeURIComponent(added.id),{method:'PATCH',body:JSON.stringify({enabled:true})});
            source={id:added.id,enabled:true,include_existing:!!added.include_existing,existing_imported:!!added.existing_imported};
            if(!current())return;
            source.enabled=true;render();toast(include.checked?'Listo. Importamos su música actual y mantenemos las novedades.':'Listo. Sus próximas rolas se guardarán automáticamente.');
          }catch(error){if(current()){feedback.textContent=error.message;follow.disabled=false;}}
        });
      }else{
        panel.append(el('p','section-copy','Elegí canciones o álbumes de abajo para enviárselos al dueño de esta biblioteca. Solo él puede activar la actualización automática del artista.'));
      }
      if(artist.description){const about=el('details','artist-about');about.append(el('summary','','Sobre el artista'),el('p','',artist.description));panel.append(about);}
      const songs=Array.isArray(artist.songs)?artist.songs:[],albums=Array.isArray(artist.albums)?artist.albums:[];
      if(songs.length){panel.append(el('h3','artist-section-title','Canciones destacadas'));const list=el('div','record-grid');
        for(const song of songs)list.append(RecordCards.card({...song,artists:song.artists?.length?song.artists:[{id:artist.id,name:artist.title}]}));
        panel.append(list);}
      if(albums.length){panel.append(el('h3','artist-section-title','Álbumes'));const grid=el('div','record-grid');
        for(const album of albums)grid.append(RecordCards.card({...album,artists:[{id:artist.id,name:artist.title}]}));
        panel.append(grid);}
      if(!songs.length&&!albums.length)panel.append(el('p','section-copy','No hay pistas o álbumes disponibles para este artista. Probá buscar una canción por su nombre.'));
    }catch(err){if(request===this.request&&revision===Profile.revision){feedback.textContent=err.message;feedback.classList.add('error');}}
  }
};
window.Artists=Artists;
$('refresh-artists').addEventListener('click',()=>Artists.showSaved(true));

function libraryMetadata(item){
  const genres=Array.isArray(item.genres)?item.genres.filter(x=>typeof x==='string').slice(0,3):[];
  const sources=Array.isArray(item.metadata_sources)?item.metadata_sources.filter(x=>typeof x==='string'):[];
  const credits=Array.isArray(item.metadata_attributions)?item.metadata_attributions:[];
  if(!genres.length&&!sources.length&&!item.metadata_status)return null;
  const details=el('details','library-metadata');details.append(el('summary','','Detalles de la música'));
  if(genres.length)details.append(el('p','',(item.metadata_status?.genres==='artist'?'Géneros del artista: ':'Géneros: ')+genres.join(' · ')));
  const lyrics=item.metadata_status?.lyrics;
  if(lyrics){const labels={synced:'Letra sincronizada incluida',plain:'Letra incluida',missing:'Letra no encontrada',unavailable:'Servicio de letras no disponible',unverified:'Letra sin coincidencia suficiente',disabled:'Letras desactivadas',instrumental:'Pista instrumental'};details.append(el('p','',labels[lyrics]||'Información de letras procesada'));}
  if(sources.length)details.append(el('p','','Datos de '+sources.join(', ')));
  for(const credit of credits){try{const url=new URL(credit.url);if(url.protocol!=='https:'||url.username||url.password)continue;const a=el('a','',credit.label||credit.provider||'Fuente');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';details.append(a);}catch{}}
  return details;
}
