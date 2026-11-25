'use strict';
const DownloadUI={
  saved:new Map(), watched:new Set(), foreground:null, poll:null, editing:null, latest:[],
  storeKey(){return 'mi-download-notices:'+Profile.user?.id+':'+Profile.library?.id;},
  reset(){
    clearInterval(this.poll);this.poll=null;this.foreground=null;this.editing=null;
    this.saved.clear();this.latest=[];this.watched.clear();
    $('download-notices').replaceChildren();$('failed-attempts').replaceChildren();$('failed-section').hidden=true;
    $('metadata-dialog').close();
    if(Profile.library){try{this.watched=new Set(JSON.parse(localStorage.getItem(this.storeKey())||'[]'));}catch{}}
  },
  persist(){try{localStorage.setItem(this.storeKey(),JSON.stringify([...this.watched].slice(-100)));}catch{}},
  trackJob(id){if(id){this.watched.add(id);this.persist();}},
  isSaved(t){
    if(!t)return false;
    for(const id of [t.id,t.source_id,t.youtube_id,t.flac_id])if(this.saved.has(id))return this.saved.get(id);
    return !!(t.job_id||t.downloaded);
  },
  remember(file,on=true){
    for(const id of [file.source_id,file.id,file.youtube_id].filter(Boolean)){
      if(this.saved.get(id)===on)continue;
      this.saved.set(id,on);
      for(const card of document.querySelectorAll('.record-card[data-record-id="'+CSS.escape(id)+'"]')){
        const marker=card.querySelector('.record-saved');if(marker)marker.hidden=!on;
      }
    }
  },
  playerState(t){
    const saved=this.isSaved(t),b=$('player-download');
    b.hidden=false;b.disabled=saved;b.classList.toggle('downloaded',saved);
    b.setAttribute('aria-label',saved?'Ya está en la biblioteca':'Descargar');
    b.title=b.getAttribute('aria-label');b.parentElement.title=b.title;
    b.replaceChildren(actionIcon(saved?'check':'download'));
  },
  review(item){
    if(!item)return;
    $('player-detail').close();
    return openPreview(item.reference?{url:item.url}:{id:item.id||item.source_id,type:item.type==='album'?'album':'song'});
  },
  async fileFor(t){
    const id=t.source_id||t.id;
    let data=await api('/api/library/record/'+encodeURIComponent(id));
    if(!data.file&&t.flac_id&&t.flac_id!==id)data=await api('/api/library/record/'+encodeURIComponent(t.flac_id));
    return data.file;
  },
  async details(t){
    if(!t)return;
    if(!this.isSaved(t))return this.review(t);
    const rev=Profile.revision;
    try{
      const file=t.job_id&&t.format?t:await this.fileFor(t);
      if(rev!==Profile.revision)return;
      if(!file){this.remember(t,false);return this.review(t);}
      this.editing=file;$('player-detail').close();
      for(const key of ['title','artist','album','track']){
        const input=$('tag-'+key);input.value=file[key]||'';input.readOnly=!Profile.owner();
      }
      $('tag-image').replaceChildren(cover(file.cover));
      if(Profile.owner())$('tag-image').append(CoverEditor.button(file));
      $('tag-save').hidden=!Profile.owner();$('tag-save').disabled=false;
      $('tag-caption').textContent=SourceUI.label(file.format);
      status('tag-status','');if(!$('metadata-dialog').open)$('metadata-dialog').showModal();
    }catch(e){if(rev===Profile.revision)toast(e.message);}
  },
  async updateTags(event){
    event.preventDefault();const file=this.editing,rev=Profile.revision;
    if(!file||!Profile.owner())return;
    const fields={revision:file.tag_revision||0};
    for(const key of ['title','artist','album'])fields[key]=$('tag-'+key).value.trim();
    fields.track=$('tag-track').value?Number($('tag-track').value):null;
    $('tag-save').disabled=true;status('tag-status','Guardando etiquetas…');
    try{
      const data=await api('/api/library/'+encodeURIComponent(file.source_id)+'/'+encodeURIComponent(file.format)+'/metadata',
        {method:'PATCH',body:JSON.stringify(fields)});
      if(rev!==Profile.revision)return;
      this.editing=data.file;
      const current=MediaUI.playing;
      if(current&&[current.id,current.source_id,current.flac_id].some(id=>id&&[file.source_id,file.youtube_id].includes(id))){
        for(const key of ['title','artist','album','track','tag_revision'])current[key]=data.file[key];
        Player.paint();
      }
      state.libraryKey='';state.jobsKey='';
      if(state.page==='biblioteca')await loadLibrary();if(state.page==='descargas')await loadJobs();
      if(rev===Profile.revision){$('metadata-dialog').close();toast('Etiquetas guardadas en el archivo.');}
    }catch(e){if(rev===Profile.revision)status('tag-status',e.message,true);}
    finally{if(rev===Profile.revision)$('tag-save').disabled=false;}
  },
  prepareReview(){
    this.release();
    $('download-progress').hidden=true;$('review-buttons').hidden=false;
    $('queue-review').hidden=!Profile.owner();$('queue-review').disabled=true;
  },
  release(){
    if(this.foreground)this.trackJob(this.foreground);
    this.foreground=null;clearInterval(this.poll);this.poll=null;
  },
  async submit(background){
    if(!state.preview||!state.selected.size||state.saving||this.foreground)return;
    const rev=Profile.revision,request=state.previewRequest;
    const format=$('format').value;
    const tracks=state.preview.tracks.filter(t=>state.selected.has(t.id)).map(t=>({id:t.id,expected_format:SourceUI.output(t,format)}));
    state.saving=true;updateSelected();$('close-preview').disabled=true;status('preview-status','Agregando…');
    try{
      const result=await post('/api/jobs',{format,tracks});
      if(rev!==Profile.revision)return;
      if(result.kind==='proposal'){
        $('preview-dialog').close();toast(result.status==='approved'?'Selección aprobada y en cola.':'Selección enviada al dueño de la biblioteca.');return;
      }
      if(background||request!==state.previewRequest||!$('preview-dialog').open){
        this.trackJob(result.id);if(request===state.previewRequest)$('preview-dialog').close();
        toast('En cola. Te avisamos cuando termine.');
      }else{
        this.foreground=result.id;$('review-buttons').hidden=true;$('download-progress').hidden=false;
        for(const control of $('preview-dialog').querySelectorAll('[data-track-id],#select-all,#format,.artwork-action,.review-art-edit'))control.disabled=true;
        this.drawProgress({status:'queued',progress:0});this.poll=setInterval(()=>{if(!document.hidden)loadJobs();},1000);
      }
      state.jobsKey='';await loadJobs();
    }catch(e){if(rev===Profile.revision&&request===state.previewRequest)status('preview-status',e.message,true);}
    finally{
      if(rev===Profile.revision){state.saving=false;$('close-preview').disabled=false;
        if(!this.foreground)updateSelected();if(!this.foreground&&$('download-progress').hidden)$('format').disabled=false;}
    }
  },
  drawProgress(job){
    const pct=job.status==='completed'?100:Math.max(0,Math.min(100,Math.floor(job.progress||0)));
    $('review-meter').value=pct;
    const failed=['failed','interrupted'].includes(job.status);
    $('review-percent').textContent=(failed?'Interrumpida':job.status==='completed'?'Descarga completada':job.status==='queued'?'En cola':'Descargando')+' · '+pct+' %';
    status('preview-status',failed?job.error||'No pudimos terminar la descarga.':'',failed);
    const actions=$('review-progress-actions');actions.replaceChildren();
    if(job.status==='completed'){
      for(const file of job.files||[]){
        const label=(job.files.length===1?'Reproducir':'Reproducir '+file.title);
        actions.append(MediaUI.button(label,'play',()=>{this.foreground=null;$('preview-dialog').close();MediaUI.play(file);},'primary'));
      }
    }else if(failed){
      actions.append(RecordCards.button('quiet','Ver intentos fallidos',()=>{this.foreground=null;$('preview-dialog').close();navigate('descargas');}));
    }
    if(failed||job.status==='completed'){
      clearInterval(this.poll);this.poll=null;
    }else actions.append(RecordCards.button('quiet','Continuar en segundo plano',()=>{$('preview-dialog').close();}));
  },
  observe(items){
    this.latest=items;
    for(const job of items){
      if(job.id===this.foreground&&$('preview-dialog').open)this.drawProgress(job);
      const terminal=['completed','failed','interrupted'].includes(job.status);
      if(this.watched.has(job.id)&&terminal){
        this.watched.delete(job.id);this.persist();
        if(this.foreground!==job.id)this.notify(job);
      }
    }
  },
  notify(job){
    const succeeded=job.status==='completed',note=el('div','download-notice');
    const file=job.files?.[0],info=el('div','notice-text');
    info.append(el('strong','',succeeded?'Descarga completada':'Error de descarga'),el('span','',job.title),
      el('small','',succeeded?job.artist:job.error));
    const open=RecordCards.button('notice-open','',()=>{
      note.remove();if(succeeded&&file)MediaUI.play(file);else navigate('descargas');
    });
    open.append(cover(file?.cover||job.cover),info);
    const close=RecordCards.button('icon-button','×',()=>note.remove());close.setAttribute('aria-label','Cerrar notificación');
    note.append(open,close);const tray=$('download-notices');tray.prepend(note);
    while(tray.children.length>3)tray.lastElementChild.remove();
    setTimeout(()=>note.remove(),succeeded?15000:30000);
  },
  async removeAttempt(job,button){
    if(!Profile.owner())return;button.disabled=true;const rev=Profile.revision;
    try{
      await api('/api/jobs/'+encodeURIComponent(job.id),{method:'DELETE',body:'{}'});
      if(rev!==Profile.revision)return;
      this.watched.delete(job.id);this.persist();state.jobsKey='';await loadJobs();toast('Intento quitado del historial.');
    }catch(e){if(rev===Profile.revision){button.disabled=false;toast(e.message);}}
  }
};
window.DownloadUI=DownloadUI;
$('enqueue').onclick=()=>DownloadUI.submit(false);
$('queue-review').onclick=()=>DownloadUI.submit(true);
$('tag-form').onsubmit=e=>DownloadUI.updateTags(e);
$('player-info-action').onclick=()=>DownloadUI.details(MediaUI.playing);
$('preview-dialog').addEventListener('close',()=>{
  if($('preview-dialog').open)return;
  if(DownloadUI.latest.some(job=>job.id===DownloadUI.foreground&&['completed','failed','interrupted'].includes(job.status)))DownloadUI.foreground=null;
  DownloadUI.release();
});
