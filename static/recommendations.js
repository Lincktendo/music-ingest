'use strict';
const HomeRecommendations={
  epoch:0,historyRead:0,settingsLoaded:false,
  reset(){this.epoch++;this.historyRead++;this.settingsLoaded=false;$('home-genres')?.remove();if($('recommendation-algorithm'))$('recommendation-algorithm').value='';if($('recommendation-settings-status'))$('recommendation-settings-status').textContent='';if($('advanced-settings'))$('advanced-settings').open=false;},
  update(data){
    const info=data.genres;if(!info)return;
    let box=$('home-genres');
    if(!info.connected){box?.remove();return;}
    if(!box){box=el('section','recommendation-genres');box.id='home-genres';$('home-sections').before(box);}
    const head=el('header');head.append(el('h3','','Explorá tus géneros'),el('small','','De Navidrome · cambian cada 6 horas'));
    const row=el('div','genre-row');row.setAttribute('aria-label','Géneros de tu biblioteca');
    for(const name of info.items||[]){
      const button=el('button','',name);button.type='button';button.onclick=()=>this.genre(name,button);row.append(button);
    }
    if(!row.childElementCount&&info.checking){row.setAttribute('aria-busy','true');for(let i=0;i<6;i++)row.append(el('span','genre-placeholder'));}
    box.replaceChildren(head,row);
    if(info.warning)box.append(el('small','',info.warning));
    else if(!row.childElementCount)box.append(el('small','','Los géneros aparecen cuando Navidrome termina de revisar música con etiquetas.'));
  },
  async genre(name,button){
    const revision=Profile.revision;button.disabled=true;
    try{await post('/api/recommendations/genre',{genre:name});if(revision!==Profile.revision)return;}
    catch(e){if(revision!==Profile.revision)return;toast(e.message);}
    finally{button.disabled=false;}
    $('query').value=name;const songs=document.querySelector('[name=kind][value=songs]');if(songs)songs.checked=true;$('search-form').requestSubmit();
  },
  async showHistory(){
    if(!Profile.user||suggest.composing||$('preview-dialog').open)return;
    const query=$('query').value.trim();if(/^(?:https?:|www\.|\/watch\?)/i.test(query))return;
    invalidateSuggestions();const revision=Profile.revision,request=++this.historyRead,suggestionRevision=suggest.revision;
    try{
      const data=await api('/api/recommendations/history');
      if(request!==this.historyRead||revision!==Profile.revision||suggestionRevision!==suggest.revision||document.activeElement!==$('query')||$('query').value.trim()!==query)return;
      const items=data.items||[];if(!items.length)return;
      suggest.items=items.map(t=>t.query);suggest.active=-1;$('suggestions').replaceChildren();
      items.forEach((item,index)=>{
        const option=el('div','suggestion-option history-option');option.id='history-'+request+'-'+index;option.setAttribute('role','option');option.setAttribute('aria-selected','false');option.tabIndex=-1;
        const label=el('span','suggestion-label',item.query),icon=el('span','suggestion-icon','↶');icon.setAttribute('aria-hidden','true');
        const remove=el('button','history-remove','×');remove.type='button';remove.setAttribute('aria-label','Eliminar búsqueda: '+item.query);remove.title='Eliminar del historial';
        remove.onpointerdown=e=>e.preventDefault();remove.onclick=async e=>{
          e.stopPropagation();e.preventDefault();remove.disabled=true;this.historyRead++;const deletingRevision=Profile.revision,deleteSuggestions=suggest.revision;
          try{await api('/api/recommendations/history/'+encodeURIComponent(item.id),{method:'DELETE'});if(deletingRevision===Profile.revision&&deleteSuggestions===suggest.revision&&$('query').value.trim()===query&&(document.activeElement===$('query')||option.contains(document.activeElement))){closeSuggestions();$('query').focus();this.showHistory();}}
          catch(err){if(deletingRevision===Profile.revision)toast(err.message);remove.disabled=false;}
        };
        option.addEventListener('mousedown',e=>e.preventDefault());option.onpointermove=e=>{if(e.pointerType==='mouse')activateSuggestion(index);};option.onclick=()=>chooseSuggestion(index);
        option.append(icon,label,remove);$('suggestions').append(option);
      });
      $('suggestion-panel').hidden=false;$('query').setAttribute('aria-expanded','true');$('suggestions-status').textContent='Búsquedas recientes. Usá las flechas para elegir o la equis para eliminar.';
    }catch{/* History is optional and must not prevent typing a new search. */}
  },
  async loadSettings(){
    if(this.settingsLoaded||!Profile.user)return;const revision=Profile.revision,epoch=this.epoch;
    try{const data=await api('/api/recommendations/settings');if(revision!==Profile.revision||epoch!==this.epoch)return;$('recommendation-algorithm').value=data.algorithm;this.settingsLoaded=true;}
    catch(e){if(revision===Profile.revision)$('recommendation-settings-status').textContent=e.message;}
  },
  mountSettings(){
    const parent=$('advanced-settings');if(!parent)return;
    const section=el('section','recommendation-settings'),title=el('h3','','Tus recomendaciones');
    const copy=el('p','','Dejá el campo vacío para usar el equilibrio recomendado. Ajustá cuánto pesan tus búsquedas, reproducciones, favoritas, descargas y géneros. Es JSON de configuración; no ejecuta código.');
    const label=el('label','','Pesos personalizados (opcional)'),input=el('textarea');input.id='recommendation-algorithm';input.maxLength=2000;input.spellcheck=false;input.placeholder='Vacío = configuración recomendada';label.htmlFor=input.id;
    const example=el('details'),summary=el('summary','','Ver ejemplo y significado de los pesos');example.append(summary,el('pre','',JSON.stringify({search:3,plays:4,likes:8,downloads:2,genres:3},null,2)),el('p','','search: búsquedas · plays: escuchas · likes: favoritas · downloads: descargas · genres: géneros que abrís. Cada peso acepta de 0 a 20. Un peso más alto da más importancia a esa señal. Los que omitás conservan su valor recomendado.'));
    const actions=el('div','actions'),save=el('button','primary','Guardar preferencias'),reset=el('button','quiet','Usar valores recomendados'),status=el('p');status.id='recommendation-settings-status';status.setAttribute('role','status');save.type=reset.type='button';
    const persist=async value=>{const revision=Profile.revision;save.disabled=reset.disabled=true;status.textContent='Guardando…';try{const data=await api('/api/recommendations/settings',{method:'PATCH',body:JSON.stringify({algorithm:value})});if(revision!==Profile.revision)return;input.value=data.algorithm;status.textContent='Listo. Inicio se actualizará con estos pesos.';this.settingsLoaded=true;}
      catch(e){if(revision===Profile.revision)status.textContent=e.message;}finally{save.disabled=reset.disabled=false;}};
    save.onclick=()=>persist(input.value);reset.onclick=()=>persist('');actions.append(save,reset);section.append(title,copy,label,input,example,actions,status);parent.append(section);
    parent.addEventListener('toggle',()=>{if(parent.open)this.loadSettings();});
  }
};
window.HomeRecommendations=HomeRecommendations;
$('query').addEventListener('focus',()=>HomeRecommendations.showHistory());
HomeRecommendations.mountSettings();
