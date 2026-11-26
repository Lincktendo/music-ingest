'use strict';
const DownloadUI={
  saved:new Map(), watched:new Set(), foreground:null, poll:null, editing:null, latest:[],
  quick:new Map(),quickView:null,view:'list',
  storeKey(){return 'mi-download-notices:'+Profile.user?.id+':'+Profile.library?.id;},
  reset(){
    clearInterval(this.poll);this.poll=null;this.foreground=null;this.editing=null;
    this.saved.clear();this.latest=[];this.watched.clear();this.quick.clear();this.quickView=null;
    $('quick-download-dialog')?.close();
    try{this.view=localStorage.getItem('mi-download-view')==='grid'?'grid':'list';}catch{this.view='list';}
    $('download-notices').replaceChildren();$('failed-attempts').replaceChildren();$('failed-section').hidden=true;
    $('metadata-dialog').close();
    if(Profile.library){try{this.watched=new Set(JSON.parse(localStorage.getItem(this.storeKey())||'[]'));}catch{}}
  },
  persist(){try{localStorage.setItem(this.storeKey(),JSON.stringify([...this.watched].slice(-100)));}catch{}},
  trackJob(id){if(id){this.watched.add(id);this.persist();}},
  itemKeys(t){return [...new Set([t?.id,t?.source_id,t?.youtube_id,t?.flac_id,t?.url].filter(Boolean))];},
  pendingFor(t){for(const id of this.itemKeys(t)){const q=this.quick.get(id);if(q)return q;}return null;},
  async quickQueue(item){
    if(!item)return;
    if(this.isSaved(item))return this.details(item);
    const pending=this.pendingFor(item);
    if(pending){this.openQuick(pending);return pending.promise;}
    const rev=Profile.revision,task={item,jobs:[],status:'preparing',error:''};
    for(const key of this.itemKeys(item))this.quick.set(key,task);
    if(MediaUI.playing)this.playerState(MediaUI.playing);
    task.promise=(async()=>{
      try{
        const data=await RecordCards.resolve(item);if(rev!==Profile.revision)return;
        const tracks=data.tracks||[];if(!tracks.length)throw Error('No encontramos pistas disponibles para descargar.');
        // Use the server's canonical ids and current format decision, even for pasted links.
        for(let start=0;start<tracks.length;start+=50){
          const batch=tracks.slice(start,start+50);
          const result=await RecordCards.enqueue(batch);if(rev!==Profile.revision)return;
          if(result.kind==='proposal'){
            task.status='proposal';toast(result.status==='approved'?'Selección aprobada y en cola.':'Selección enviada al dueño de la biblioteca.');continue;
          }
          task.jobs.push(result.id);this.trackJob(result.id);task.status='queued';
          for(const t of batch)for(const key of this.itemKeys(t))this.quick.set(key,task);
        }
        if(task.jobs.length)toast('En cola. Podés seguir escuchando.');
        state.jobsKey='';await loadJobs();
      }catch(e){
        if(rev!==Profile.revision)return;
        task.status='failed';task.error=e.message;toast(e.message);
      }finally{
        if(rev===Profile.revision){if(MediaUI.playing)this.playerState(MediaUI.playing);if(this.quickView===task)this.drawQuick();}
      }
    })();
    return task.promise;
  },
  mountQuick(){
    if($('quick-download-dialog'))return;
    const dialog=el('dialog','quick-download-dialog');dialog.id='quick-download-dialog';
    dialog.setAttribute('aria-labelledby','quick-download-title');dialog.setAttribute('closedby','any');
    const top=el('div','dialog-top'),title=el('h2');title.id='quick-download-title';
    const close=RecordCards.button('icon-button','×',()=>dialog.close());close.setAttribute('aria-label','Cerrar');top.append(title,close);
    const body=el('div');body.id='quick-download-body';dialog.append(top,body);document.body.append(dialog);
    let outside=false;const isOutside=event=>{const r=dialog.getBoundingClientRect();return event.target===dialog&&(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom);};
    dialog.addEventListener('pointerdown',event=>{outside=isOutside(event);});
    dialog.addEventListener('click',event=>{if(outside&&isOutside(event))dialog.close();outside=false;});
    dialog.addEventListener('close',()=>{if(!dialog.open)this.quickView=null;});
  },
  openQuick(task){
    this.mountQuick();this.quickView=task;this.drawQuick();
    if(!$('quick-download-dialog').open)$('quick-download-dialog').showModal();
  },
  drawQuick(){
    const task=this.quickView;if(!task)return;
    $('quick-download-title').textContent=task.item.title||'Tu descarga';
    const root=$('quick-download-body');root.replaceChildren();
    const jobs=task.jobs.map(id=>this.latest.find(job=>job.id===id)).filter(Boolean);
    if(!jobs.length){
      const p=el('p','section-copy',task.error|| (task.status==='proposal'?'Selección enviada.':'Preparando la descarga…'));
      if(task.status==='preparing')p.prepend(el('i','ux-spinner'));root.append(p);
    }
    for(const job of jobs)root.append(this.jobCard(job));
    if(task.error){
      const retry=RecordCards.button('quiet','Reintentar descarga',()=>{
        for(const [key,value] of this.quick)if(value===task)this.quick.delete(key);
        $('quick-download-dialog').close();this.quickQueue(task.item);
      });root.append(retry);
    }
    root.append(RecordCards.button('quiet','Seguir escuchando',()=>$('quick-download-dialog').close()));
  },
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
    const saved=this.isSaved(t),pending=this.pendingFor(t),b=$('player-download');
    b.hidden=false;b.disabled=false;b.classList.toggle('downloaded',saved);b.classList.toggle('download-pending',!!pending&&!saved);
    b.setAttribute('aria-label',saved?'Ya está en la biblioteca · Ver datos':pending?'Ver descarga':'Descargar en segundo plano');
    b.title=b.getAttribute('aria-label');b.parentElement.title=b.title;
    b.replaceChildren(pending?.status==='preparing'&&!saved?el('i','ux-spinner'):actionIcon(saved?'check':'download'));
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
    if(this.quickView&&$('quick-download-dialog')?.open)this.drawQuick();
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
    setTimeout(()=>note.remove(),4000);
  },
  mountView(){
    if($('download-view'))return;
    try{this.view=localStorage.getItem('mi-download-view')==='grid'?'grid':'list';}catch{}
    const tools=el('div','download-view');tools.id='download-view';tools.setAttribute('role','group');tools.setAttribute('aria-label','Vista de descargas');
    tools.append(el('span','section-copy','Ver como'));
    for(const [value,label] of [['list','Lista'],['grid','Cuadrícula']]){
      const b=RecordCards.button('quiet',label,()=>{
        this.view=value;try{localStorage.setItem('mi-download-view',value);}catch{}
        this.renderJobs(this.latest);
      });b.dataset.downloadView=value;tools.append(b);
    }
    $('jobs-status').before(tools);
    const hint=el('small','tag-artist-hint','Varios artistas: separalos con punto y coma (;).');
    hint.id='tag-artist-hint';$('tag-artist').after(hint);$('tag-artist').setAttribute('aria-describedby',hint.id);
  },
  renderJobs(items){
    this.mountView();
    for(const button of $('download-view').querySelectorAll('[data-download-view]')){
      const active=button.dataset.downloadView===this.view;button.setAttribute('aria-pressed',String(active));button.classList.toggle('active',active);
    }
    const root=$('jobs'),failed=$('failed-attempts');root.replaceChildren();failed.replaceChildren();
    for(const container of [root,failed])container.className=this.view==='grid'?'record-grid download-cards':'download-list';
    const failures=items.filter(job=>['failed','interrupted'].includes(job.status));$('failed-section').hidden=!failures.length;
    for(const job of items){
      const target=['failed','interrupted'].includes(job.status)?failed:root;
      if(job.files?.length)for(const file of job.files)target.append(this.compactCard(job,file));
      if(!job.files?.length||job.status!=='completed')target.append(this.compactCard(job));
    }
    if(!root.children.length)empty(root,failures.length?'No hay descargas activas':'Tu cola está tranquila',
      failures.length?'Podés reintentar las descargas pendientes más abajo.':'Cuando descargués música, vas a ver su progreso acá.');
  },
  compactCard(job,file=null){
    const title=file?.title||job.title||'Selección de música',artist=file?.artist||job.artist||'Artista sin identificar';
    const item={...file,id:file?.source_id||job.id,title,artist,downloadFile:file,downloadJob:job};
    const card=el('article','record-card download-card');card.dataset.jobId=job.id;
    const frame=el('div','record-picture'),open=()=>file?MediaUI.play(file):this.openQuick({item,jobs:[job.id]});
    const photo=RecordCards.button('record-open',undefined,open);photo.setAttribute('aria-label',(file?'Escuchar ':'Ver descarga de ')+title);
    photo.append(cover(file?.cover||job.cover));frame.append(photo);card.append(frame);
    const info=el('div','download-card-info');
    const name=RecordCards.button('record-title',title,open);name.title=title;
    const by=el('div','record-by',artist);by.title=artist;
    const album=el('div','record-release',file?.album||'Single');album.title=album.textContent;
    const footer=el('div','download-card-footer');
    const fmt=file?.format||job.formats?.[0];if(fmt){const badge=el('small','format-chip',fmt.toUpperCase());badge.dataset.format=fmt;badge.dataset.on='true';footer.append(badge);}
    const text=file?'Guardada':({queued:'En cola',running:Math.round(job.progress||0)+' %',failed:'Error · Reintentar',interrupted:'Interrumpida'})[job.status]||'Procesando';
    const status=el('small','download-card-status',text);status.title=job.error||text;footer.append(status);
    if(file&&job.warnings?.length){const warning=el('span','download-card-warning','!');warning.title='Algunos datos no se completaron. Revisalos en los tres puntos.';footer.append(warning);}
    info.append(name,by,album,footer);card.append(info);
    if(!file){const progress=el('progress','download-card-progress');progress.max=100;progress.value=job.progress||0;progress.setAttribute('aria-label','Progreso');frame.append(progress);}
    RecordMenus.attach(card,item);return card;
  },
  async showLyrics(file){
    const url=safeUrl(file.lyrics_url,'/api/files/');if(!url)return;
    const revision=Profile.revision,dialog=el('dialog','download-lyrics'),top=el('div','dialog-top');
    const close=RecordCards.button('icon-button','×',()=>dialog.close());close.setAttribute('aria-label','Cerrar letra');
    top.append(el('h2','',file.title||'Letra'),close);const body=el('pre','','Cargando letra…');dialog.append(top,body);
    dialog.setAttribute('aria-label','Letra de '+(file.title||'la canción'));dialog.setAttribute('closedby','any');document.body.append(dialog);
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
    try{const response=await fetch(url);if(!response.ok)throw Error('No se pudo abrir la letra.');const text=await response.text();
      if(revision!==Profile.revision){dialog.close();return;}body.textContent=text;
    }catch(e){body.textContent=e.message;}
  },
  jobCard(job){
    const box=el('article','job download-job');box.dataset.jobId=job.id;
    const head=el('div','job-head'),info=el('div','download-job-info'),art=cover(job.files?.[0]?.cover||job.cover);
    art.classList.add('download-job-art');head.append(art);
    info.append(el('h3','job-title',job.title||'Selección de música'));
    const by=el('p','job-info',job.artist||'');if(job.artist)info.append(by);
    let stamp='';if(job.created_at){const date=new Date(typeof job.created_at==='number'?job.created_at*1000:job.created_at);
      if(!Number.isNaN(date.valueOf()))stamp=date.toLocaleString('es',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});}
    const badges=el('div','download-job-formats');
    for(const fmt of job.formats||[]){const chip=el('small','format-chip',String(fmt).toUpperCase());chip.dataset.format=String(fmt).toLowerCase();chip.dataset.on='true';badges.append(chip);}
    if(stamp)badges.append(el('small','job-info',stamp));info.append(badges);
    const failed=['failed','interrupted'].includes(job.status),running=['queued','running'].includes(job.status);
    const statusText={queued:'En cola',running:'Descargando',completed:'Completada',failed:'No se pudo completar',interrupted:'Interrumpida'}[job.status]||'Procesando';
    head.append(info,el('span','status-tag'+(failed?' bad':''),statusText));box.append(head);
    if(running){
      const meter=el('progress','progress');meter.max=100;meter.value=Math.max(0,Math.min(100,Number(job.progress)||0));
      meter.setAttribute('aria-label','Progreso de '+(job.title||'descarga'));
      box.append(meter,el('p','job-info',job.status==='queued'?'Esperando su turno…':Math.round(meter.value)+' % completado'));
    }
    if(job.error)box.append(el('p','job-error',job.error));
    if(job.warnings?.length){const warn=el('p','job-info download-warning','Audio guardado. Algunos datos, la portada o la letra no se pudieron completar.');box.append(warn);}
    if(failed&&Profile.owner()){
      const actions=el('div','download-job-actions');
      const retry=RecordCards.button('quiet','Reintentar pendientes',async()=>{
        retry.disabled=true;const rev=Profile.revision;
        try{await post('/api/jobs/'+encodeURIComponent(job.id)+'/retry');if(rev!==Profile.revision)return;
          this.trackJob(job.id);state.jobsKey='';await loadJobs();toast('El trabajo vuelve a la cola.');
        }catch(e){if(rev===Profile.revision){retry.disabled=false;toast(e.message);}}
      });
      const remove=RecordCards.button('quiet danger-action','Quitar intento',()=>this.removeAttempt(job,remove));
      actions.append(retry,remove);box.append(actions);
    }
    if(job.files?.length){
      const files=el('div','file-links');
      for(const file of job.files){
        const row=el('div','download-track'),info=el('div','download-track-info');
        const title=el('strong','',file.title||file.name),by=el('small','',[file.artist,file.album].filter(Boolean).join(' · '));
        title.title=title.textContent;by.title=by.textContent;info.append(title,by);
        const controls=MediaUI.controls(file);
        controls.append(MediaUI.button(Profile.owner()?'Editar datos':'Ver datos','music',()=>this.details(file)));
        row.append(cover(file.cover),info,controls);files.append(row);
      }
      box.append(files);
    }
    return box;
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
