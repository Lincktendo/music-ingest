'use strict';
const Artists={
  request:0,
  close(){this.request++;$('artist-panel').hidden=true;$('artist-panel').replaceChildren();$('results').hidden=false;$('results-heading').hidden=false;},
  async open(id){
    closeSuggestions();const request=++this.request,revision=Profile.revision,panel=$('artist-panel');
    panel.hidden=false;$('results').hidden=true;$('results-heading').hidden=true;$('welcome').hidden=true;panel.replaceChildren();
    const back=el('button','quiet artist-back','← Volver a resultados');back.type='button';back.addEventListener('click',()=>this.close());panel.append(back);panel.scrollIntoView({block:'start'});
    const feedback=el('p','inline-status','Cargando artista…');feedback.setAttribute('role','status');panel.append(feedback);
    try{
      const artist=await api('/api/artists/'+encodeURIComponent(id));if(request!==this.request||revision!==Profile.revision)return;feedback.remove();
      const hero=el('div','artist-hero'),info=el('div');info.append(el('span','eyebrow','ARTISTA'),el('h2','',artist.title||'Artista'));
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
      if(songs.length){panel.append(el('h3','artist-section-title','Canciones destacadas'));const list=el('div','artist-songs');
        for(const song of songs){const button=el('button','artist-song');button.type='button';const text=el('div','row-info');text.append(el('strong','',song.title||'Sin título'),el('small','',song.artist||artist.title));button.append(cover(song.cover||artist.cover),text,el('span','song-length',duration(song.duration)),el('span','song-action','Revisar'));button.addEventListener('click',()=>openPreview({id:song.id,type:'song'}));list.append(window.Selection?Selection.wrap(button,song):button);}panel.append(list);}
      if(albums.length){panel.append(el('h3','artist-section-title','Álbumes'));const grid=el('div','results-grid');for(const album of albums){const card=el('button','music-card');card.type='button';card.append(cover(album.cover),el('h3','',album.title||'Álbum'),el('p','',album.artist||artist.title||''));card.addEventListener('click',()=>openPreview({id:album.id,type:'album'}));grid.append(card);}panel.append(grid);}
      if(!songs.length&&!albums.length)panel.append(el('p','section-copy','No hay pistas o álbumes disponibles para este artista. Probá buscar una canción por su nombre.'));
    }catch(err){if(request===this.request&&revision===Profile.revision){feedback.textContent=err.message;feedback.classList.add('error');}}
  }
};
window.Artists=Artists;

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
