'use strict';
const AutomationUI={
  folder:'',
  async load(){
    if(!Profile.owner())return;
    const revision=Profile.revision;
    const data=await api('/api/following');if(revision!==Profile.revision)return;
    $('check-interval').value=String(data.interval_seconds);
    $('following-backlog').textContent=data.pending_tracks?data.pending_tracks+' rolas esperando espacio en la cola. Se irán agregando solitas.':'';
    this.renderSources(data.items.filter(x=>x.kind==='playlist'),'following-list','Todavía no agregaste playlists. Pegá el enlace arriba para empezar.');
    this.renderSources(data.items.filter(x=>x.kind==='artist'),'favorite-list','Todavía no seguís artistas. Tocá «Buscar un artista» para elegir el primero.');
    if(!$('folder-current').textContent)await this.browse('');
  },
  renderSources(items,target,emptyText){
    const root=$(target);root.replaceChildren();if(!items.length){root.append(el('p','empty-state',emptyText));return;}
    const revision=Profile.revision,labels={pending:'Preparando',paused:'En pausa',error:'No se pudo revisar',following:'Automática',importing:'Descargando',needs_retry:'Hay descargas pendientes',imported:'Descarga terminada'};
    for(const source of items){
      const row=el('article','profile-card source-card'),head=el('div','job-head'),info=el('div','row-info');
      info.append(el('h3','',source.title),el('p','section-copy',source.kind==='artist'?(source.include_existing?'Catálogo actual + nuevos lanzamientos':'Nuevos lanzamientos automáticos'):source.follow_updates?'Se actualiza automáticamente':'Descarga de una sola vez'));
      head.append(info,el('span','status-tag',labels[source.state]||'Preparando'));row.append(head);
      if(source.initialized)row.append(el('p','section-copy',source.track_count+' canciones encontradas'+(source.pending_tracks?' · '+source.pending_tracks+' esperando su turno':'')+(source.active_tracks?' · '+source.active_tracks+' en descarga':'')));
      const stamp=value=>new Date(value*1000).toLocaleString('es',{dateStyle:'short',timeStyle:'short'});
      if(source.last_check)row.append(el('p','section-copy','Última revisión: '+stamp(source.last_check)));
      if(source.enabled&&source.next_check)row.append(el('p','section-copy','Próxima revisión: '+stamp(source.next_check)));
      if(source.error)row.append(el('p','job-error',source.error));
      const actions=el('div','row-actions');
      const operations=[];
      if(source.follow_updates||!source.initialized||source.pending_tracks)operations.push([source.enabled?'Pausar':'Reanudar','PATCH','',{enabled:!source.enabled}]);
      if(source.follow_updates||!source.initialized)operations.push(['Revisar ahora','POST','/check',{}]);
      operations.push(['Quitar de esta lista','DELETE','',{}]);
      for(const [label,method,suffix,body] of operations){
        const button=el('button','quiet',label);button.type='button';button.disabled=label==='Revisar ahora'&&!source.enabled;
        button.addEventListener('click',async()=>{button.disabled=true;try{await api('/api/following/'+encodeURIComponent(source.id)+suffix,{method,body:JSON.stringify(body)});if(revision!==Profile.revision)return;await this.load();toast(method==='DELETE'?'Quitado de la lista. Tus archivos y descargas en cola se conservan.':'Listo. Cambio guardado.');}catch(error){toast(error.message);}finally{button.disabled=false;}});actions.append(button);
      }
      const downloads=el('button','text-action','Ver descargas →');downloads.type='button';downloads.addEventListener('click',()=>navigate('descargas'));actions.append(downloads);row.append(actions);root.append(row);
    }
  },
  async browse(path){
    if(!Profile.owner())return;const revision=Profile.revision;
    const data=await api('/api/folders?path='+encodeURIComponent(path));if(revision!==Profile.revision)return;
    this.folder=data.path;
    $('folder-current').textContent='Viendo: Música'+(data.path?' / '+data.path:'');
    $('folder-selected').textContent='Guardando en: Música'+(data.selected?' / '+data.selected:'');
    $('folder-up').disabled=!data.path;
    const list=$('folder-list');list.replaceChildren();
    for(const item of data.items){const button=el('button','quiet folder-entry','📁 '+item.name);button.type='button';button.addEventListener('click',()=>this.browse(item.path).catch(e=>toast(e.message)));list.append(button);}
    if(!data.items.length)list.append(el('p','section-copy','Esta carpeta no tiene subcarpetas. Podés crear una abajo.'));
  },
  reset(){this.folder='';for(const id of ['following-list','favorite-list','folder-list'])$(id).replaceChildren();for(const id of ['folder-current','folder-selected','following-backlog'])$(id).textContent='';$('playlist-url').value='';$('new-folder-name').value='';$('playlist-form').reset();status('playlist-feedback','');}
};
window.AutomationUI=AutomationUI;
$('playlist-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter||$('playlist-submit'),revision=Profile.revision;
  const mode=document.querySelector('[name="playlist-mode"]:checked');if(!mode)return;
  button.disabled=true;status('playlist-feedback','Agregando tu playlist…');
  try{const result=await post('/api/following',{kind:'playlist',source:$('playlist-url').value.trim(),follow_updates:mode.value==='follow'});
    if(revision!==Profile.revision)return;$('playlist-form').reset();button.textContent='Agregar playlist';await AutomationUI.load();
    status('playlist-feedback',result.already_following?'Esta playlist ya está en tu lista. Conservamos la opción que habías elegido.':result.follow_updates?'Listo: descargamos las canciones de ahora y buscamos las nuevas automáticamente.':'Listo: descargamos las canciones que tiene ahora, una sola vez.');
  }catch(e){status('playlist-feedback',e.message,true);}finally{button.disabled=false;}
});
document.querySelectorAll('[name="playlist-mode"]').forEach(input=>input.addEventListener('change',()=>{$('playlist-submit').textContent=input.value==='follow'?'Descargar y mantener al día':'Descargar una vez';}));
$('refresh-artists').addEventListener('click',()=>AutomationUI.load().catch(e=>toast(e.message)));
$('check-interval').addEventListener('change',async()=>{const input=$('check-interval'),revision=Profile.revision;input.disabled=true;try{await api('/api/following/settings',{method:'PATCH',body:JSON.stringify({seconds:Number(input.value)})});if(revision!==Profile.revision)return;await AutomationUI.load();toast('Frecuencia guardada para tus playlists y artistas.');}catch(e){toast(e.message);}finally{input.disabled=false;}});
$('refresh-following').addEventListener('click',()=>AutomationUI.load().catch(e=>toast(e.message)));
$('folder-up').addEventListener('click',()=>AutomationUI.browse(AutomationUI.folder.split('/').slice(0,-1).join('/')).catch(e=>toast(e.message)));
$('folder-select').addEventListener('click',async()=>{const button=$('folder-select'),revision=Profile.revision;button.disabled=true;try{await api('/api/folders',{method:'PATCH',body:JSON.stringify({path:AutomationUI.folder})});if(revision!==Profile.revision)return;await AutomationUI.browse(AutomationUI.folder);toast('Las próximas descargas se guardarán acá. Tus archivos anteriores no se mueven.');}catch(e){toast(e.message);}finally{button.disabled=false;}});
$('folder-create').addEventListener('submit',async event=>{event.preventDefault();const button=event.submitter,revision=Profile.revision;button.disabled=true;try{const result=await post('/api/folders',{path:AutomationUI.folder,name:$('new-folder-name').value});if(revision!==Profile.revision)return;$('new-folder-name').value='';await AutomationUI.browse(result.path);toast('Carpeta creada. Tocá «Guardar acá» para usarla.');}catch(e){toast(e.message);}finally{button.disabled=false;}});
setInterval(()=>{if(!document.hidden&&['perfil','playlists','favoritos'].includes(state.page)&&Profile.owner())AutomationUI.load().catch(()=>{});},15000);
