'use strict';

const djDefaults={enabled:false,continuous:true,criterion:'similar',group:'songs',limit:10,refill:9,duplicates:false,strict:false};
const ListeningCollection = {
  likes:new Set(), lists:[], aliases:new Map(), locks:new Set(), pool:new Map(),
  cardData:new WeakMap(),cardFor:new WeakMap(),contextTracks:[],contextHeard:new Set(),
  queue:[], recent:[], series:null, expected:'', last:'', shuffle:false, serial:0,
  queueEpoch:0, filling:null, read:0, listRead:0, view:null, selectedList:'favorites', offset:null,
  currentItems:[], adding:null, error:'',
  dj:{...djDefaults},history:[],rewinding:false,warm:null,warmed:'',warmTimer:null,dragging:false,playSession:0,

  id(t){return t?.id||t?.source_id||'';},
  key(t){const id=this.id(t);return this.aliases.get(id)||id;},
  icon(name){
    const paths={heart:'M20.8 4.9a5.5 5.5 0 0 0-7.8 0l-1 1-1-1a5.5 5.5 0 1 0-7.8 7.8L12 22l8.8-9.3a5.5 5.5 0 0 0 0-7.8Z',
      plus:'M12 4v16M4 12h16',shuffle:'M3 6h3c4 0 7 12 12 12h3m-4-4 4 4-4 4M3 18h3c2 0 3-2 5-5m3-5c1-2 2-2 4-2h3m-4-4 4 4-4 4',
      queue:'M3 5h18M3 10h18M3 15h9m4-1 6 4-6 4Z',continuous:'m3 6 8 6-8 6Zm10 0 8 6-8 6Z',
      more:'M4 12h1m6 0h1m6 0h1',grip:'M6 7h12M6 12h12M6 17h12',
      play:'m7 4 13 8-13 8Z',remove:'M5 12h14',close:'m6 6 12 12m-12 0L18 6'};
    const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
    const path=document.createElementNS(NS,'path');path.setAttribute('d',paths[name]);svg.append(path);return svg;
  },
  action(label,fn,cls='quiet'){
    const button=el('button',cls,label);button.type='button';button.onclick=fn;return button;
  },
  iconButton(name,label,fn){
    const b=this.action(null,fn,'listening-icon');b.replaceChildren(this.icon(name));b.title=label;b.setAttribute('aria-label',label);return b;
  },
  mount(){
    const bar=el('div','collection-player-actions');
    const heart=this.iconButton('heart','Guardar en Favoritas',()=>this.like(MediaUI.playing));heart.id='listen-player-heart';
    const add=this.iconButton('plus','Agregar a playlist',()=>this.chooseList(MediaUI.playing));add.id='listen-player-add';
    const random=this.action('Auto DJ',()=>this.openDJ(),'dj-open');random.id='listen-shuffle';random.title='Configurar Auto DJ';
    const keep=this.action('',()=>this.changeDJ('continuous',!this.dj.continuous),'continuous-switch');keep.id='listen-continuous';keep.setAttribute('role','switch');keep.append(el('i'),el('span','','Seguir'));
    const next=this.iconButton('queue','Ver próximas rolas',()=>this.openQueue());next.id='listen-queue-button';
    bar.append(heart,add,keep,random,next);$('close-player').before(bar);

    const shelf=el('section','listening-shelf'),heading=el('h2','','Para escuchar');
    const open=this.action('Favoritas y playlists',()=>this.open());open.id='listen-open-shelf';
    shelf.append(heading,open);$('following-card').before(shelf);
    const library=this.action('Favoritas y playlists',()=>this.open());library.id='listen-open-library';
    document.querySelector('#page-biblioteca .page-heading').append(library);
    const dialog=el('dialog','listening-dialog');dialog.id='listening-dialog';dialog.setAttribute('aria-labelledby','listening-title');
    const head=el('div','dialog-top'),title=el('h2');title.id='listening-title';
    const close=this.iconButton('close','Cerrar',()=>dialog.close());head.append(title,close);
    const content=el('div','listening-dialog-body');content.id='listening-body';
    const status=el('p','inline-status');status.id='listening-status';status.setAttribute('role','status');
    dialog.append(head,content,status);document.body.append(dialog);
    dialog.setAttribute('closedby','any');
    const outside=e=>{if(e.target!==dialog)return false;const r=dialog.getBoundingClientRect();return e.clientX<r.left||e.clientX>=r.right||e.clientY<r.top||e.clientY>=r.bottom;};
    let pressed=false;
    dialog.addEventListener('pointerdown',e=>{pressed=outside(e);});
    dialog.addEventListener('click',e=>{if(pressed&&outside(e))dialog.close();pressed=false;});
    dialog.onclose=()=>{if(dialog.open)return;this.listRead++;this.view=null;this.adding=null;};
    $('music-audio').addEventListener('ended',()=>{if(this.dj.continuous)this.next();});
    this.paint();
  },
  reset(){
    this.serial++;this.read++;this.listRead++;this.queueEpoch++;this.dragging=false;this.playSession++;
    this.queue=[];this.filling=null;this.expected=this.last='';this.series=null;this.likes.clear();
    this.lists=[];this.pool.clear();this.aliases.clear();this.locks.clear();this.recent=[];this.currentItems=[];
    this.contextTracks=[];this.contextHeard.clear();this.cardData=new WeakMap();this.cardFor=new WeakMap();
    this.view=null;this.adding=null;this.error='';$('listening-dialog')?.close();
    this.history=[];this.rewinding=false;this.cancelWarm();this.dj=this.settings();this.shuffle=this.dj.enabled;
    this.paint();
  },
  async load(){
    if(!Profile.library||!Profile.user)return;
    const epoch=this.serial,seq=++this.read;
    try{
      const result=await api('/api/listening/lists');
      if(epoch!==this.serial||seq!==this.read)return;
      this.likes=new Set(result.favorites);this.lists=result.playlists;this.paint();
      if(this.view==='add')this.renderAdd();
      if(this.view==='lists')this.renderLists();
    }catch(e){if(epoch===this.serial&&this.view)this.message(e.message,true);}
  },
  decorate(card,item){
    if((item.type||'song')!=='song')return;
    this.cardData.set(card,item);this.cardFor.set(item,card);
    if(!item.reference){
      this.pool.set(item.id,item);
      if(this.pool.size>200)this.pool.delete(this.pool.keys().next().value);
    }
    const heart=this.iconButton('heart','Guardar en Favoritas',()=>this.like(item));
    heart.classList.add('record-heart');heart.dataset.likeId=this.id(item);
    card.querySelector('.record-picture').append(heart);this.paintHeart(heart,item);
  },
  paintHeart(button,item){
    if(!button)return;
    const id=typeof item==='string'?(this.aliases.get(item)||item):this.key(item);
    const active=this.likes.has(id),label=active?'Quitar de Favoritas':'Guardar en Favoritas';
    button.classList.toggle('liked',active);button.setAttribute('aria-pressed',String(active));
    button.setAttribute('aria-label',label);button.title=label;button.disabled=!id||this.locks.has(id);
  },
  paint(){
    for(const b of document.querySelectorAll('[data-like-id]'))this.paintHeart(b,b.dataset.likeId);
    this.paintHeart($('listen-player-heart'),window.MediaUI?.playing);
    const random=$('listen-shuffle');
    if(random){random.setAttribute('aria-pressed',String(this.shuffle));random.classList.toggle('active',this.shuffle);}
    const keep=$('listen-continuous');
    if(keep){
      keep.setAttribute('aria-checked',String(this.dj.continuous));keep.setAttribute('aria-pressed',String(this.dj.continuous));keep.classList.toggle('active',this.dj.continuous);
      keep.title=this.dj.continuous?'Reproducción continua · Detener al terminar esta rola':'Detener al terminar · Activar reproducción continua';
      keep.setAttribute('aria-label',keep.title);
    }
    if(this.view==='queue'&&!this.dragging)this.drawQueue();
  },
  async identify(item){
    if(!item)throw Error('Primero elegí una rola.');
    if(!item.reference)return this.key(item);
    if(this.aliases.has(item.id))return this.key(item);
    const token=this.serial,data=await RecordCards.resolve(item);
    if(token!==this.serial)throw Error('Cambiaste de biblioteca.');
    if(data.tracks?.length!==1)throw Error('Abrí una pista individual para guardarla.');
    this.aliases.set(item.id,data.tracks[0].id);return data.tracks[0].id;
  },
  async like(item){
    const token=this.serial;
    let id;
    try{
      id=await this.identify(item);if(token!==this.serial||this.locks.has(id))return;
      this.locks.add(id);this.paint();
      const active=this.likes.has(id);
      await api('/api/listening/lists/favorites/'+encodeURIComponent(id),{method:active?'DELETE':'PUT',body:'{}'});
      if(token!==this.serial)return;
      if(active)this.likes.delete(id);else this.likes.add(id);
      this.read++; // an older list response must not undo this change
      if(this.view==='tracks'&&this.selectedList==='favorites')await this.openTracks('favorites');
      if(this.view==='lists')this.renderLists();
      toast(active?'Quitada de Favoritas.':'Guardada en Favoritas.');
    }catch(e){if(token===this.serial)toast(e.message);}
    finally{if(token===this.serial&&id){this.locks.delete(id);this.paint();}}
  },
  present(view,title){
    this.view=view;this.listRead++;$('listening-title').textContent=title;$('listening-body').replaceChildren();this.message('');
    if(!$('listening-dialog').open)$('listening-dialog').showModal();
  },
  message(text,error=false){status('listening-status',text,error);},
  async open(){
    this.adding=null;this.present('lists','Favoritas y playlists');this.renderLists();await this.load();
  },
  renderLists(){
    const body=$('listening-body');body.replaceChildren();
    const favorite=this.action('♥ Favoritas · '+this.likes.size,()=>this.openTracks('favorites'),'listening-list');
    body.append(favorite,...this.lists.map(list=>this.action(list.name+' · '+list.count,()=>this.openTracks(list.id),'listening-list')));
    body.append(this.createForm());
  },
  createForm(){
    const form=el('form','listening-create'),label=el('label','','Nueva playlist'),input=el('input','wide-input');
    input.required=true;input.maxLength=100;input.placeholder='Nombre de la playlist';label.append(input);
    const submit=el('button','quiet','Crear');submit.type='submit';form.append(label,submit);
    form.onsubmit=async event=>{
      event.preventDefault();const name=input.value.trim();if(!name)return;
      const token=this.serial,target=this.view,track=this.adding;submit.disabled=true;
      try{
        const list=await post('/api/listening/lists',{name});
        if(token!==this.serial)return;
        if(target==='add'&&track){await this.addTo(list.id,track);return;}
        await this.load();
        if(token===this.serial&&this.view===target)await this.openTracks(list.id);
      }catch(e){if(token===this.serial)this.message(e.message,true);}
      finally{submit.disabled=false;}
    };
    return form;
  },
  chooseList(item){
    if(!item)return;
    this.adding=item;this.present('add','Agregar a playlist');this.renderAdd();this.load();
  },
  renderAdd(){
    const body=$('listening-body');body.replaceChildren(el('p','section-copy',this.adding?.title||''));
    for(const l of this.lists)body.append(this.action(l.name,()=>this.addTo(l.id,this.adding),'listening-list'));
    body.append(this.createForm());
  },
  async addTo(key,item){
    const token=this.serial;
    try{
      const id=await this.identify(item);if(token!==this.serial)return;
      await api('/api/listening/lists/'+key+'/'+encodeURIComponent(id),{method:'PUT',body:'{}'});
      if(token!==this.serial)return;
      $('listening-dialog').close();toast('Rola guardada en la playlist.');this.load();
    }catch(e){if(token===this.serial)this.message(e.message,true);}
  },
  async openTracks(key,append=false){
    if(!append){
      this.selectedList=key;this.currentItems=[];this.offset=0;
      this.present('tracks',key==='favorites'?'Favoritas':this.lists.find(l=>l.id===key)?.name||'Playlist');
    }
    if(this.offset==null)return;
    const seq=++this.listRead,offset=this.offset;
    this.message('Cargando rolas…');
    try{
      const data=await api('/api/listening/lists/'+key+'?offset='+offset);
      if(seq!==this.listRead)return;
      this.currentItems.push(...data.items);this.offset=data.next_offset;this.drawTracks();this.message('');
    }catch(e){if(seq===this.listRead)this.message(e.message,true);}
  },
  row(item,play){
    const row=el('div','listening-row'),btn=this.action(null,play,'listening-pick');
    const copy=el('span','listening-row-copy');
    copy.append(el('strong','',item.title),el('small','',item.artist||''));
    btn.replaceChildren(cover(item.cover),copy);btn.title='Escuchar '+item.title;
    row.append(btn);this.trackMenu(row,{...item,type:'song'});return row;
  },
  drawTracks(){
    const body=$('listening-body'),key=this.selectedList;
    body.replaceChildren(this.action('← Tus playlists',()=>this.open(),'text-action'));
    if(this.currentItems.length){
      body.append(this.action('Reproducir',()=>this.startList(0),'primary'));
      this.currentItems.forEach((item,i)=>{
        const row=this.row(item,()=>this.startList(i));
        row.append(this.iconButton('plus','Agregar a otra playlist',()=>this.chooseList(item)),
          this.iconButton('remove','Quitar de esta lista',()=>this.removeEntry(key,item)));
        body.append(row);
      });
      if(this.offset!=null)body.append(this.action('Ver más rolas',()=>this.openTracks(key,true)));
    }else body.append(el('p','section-copy',key==='favorites'?'Tocá el corazón de una rola para guardarla acá.':'Agregá rolas con el botón + del reproductor.'));
    if(key!=='favorites')body.append(this.action('Eliminar playlist',()=>this.confirmRemove(key),'text-action'));
  },
  async removeEntry(key,item){
    const token=this.serial;
    try{
      await api('/api/listening/lists/'+key+'/'+encodeURIComponent(this.id(item)),{method:'DELETE',body:'{}'});
      if(token!==this.serial)return;
      if(key==='favorites')this.likes.delete(this.id(item));
      if(this.series?.key===key){this.series=null;this.queue=[];this.queueEpoch++;this.filling=null;}
      this.paint();this.load();if(this.view==='tracks'&&key===this.selectedList)await this.openTracks(key);
    }catch(e){if(token===this.serial)this.message(e.message,true);}
  },
  confirmRemove(key){
    const name=this.lists.find(l=>l.id===key)?.name||'esta playlist';
    this.present('remove','¿Eliminar «'+name+'»?');
    const body=$('listening-body');
    body.append(el('p','section-copy','Tus archivos de música se conservan.'),
      this.action('Cancelar',()=>this.openTracks(key)),this.action('Eliminar playlist',async()=>{
        const token=this.serial;
        try{
          await api('/api/listening/lists/'+key,{method:'DELETE',body:'{}'});
          if(token!==this.serial)return;
          if(this.series?.key===key){this.series=null;this.queue=[];this.queueEpoch++;this.filling=null;}
          this.open();
        }catch(e){if(token===this.serial)this.message(e.message,true);}
      }));
  },
  settingsKey(){return 'mi-auto-dj:'+Profile.user?.id+':'+Profile.library?.id;},
  settings(){
    let value={};
    try{
      const key=this.settingsKey(),saved=localStorage.getItem(key);
      value=saved?JSON.parse(saved):{enabled:localStorage.getItem('mi-shuffle:'+Profile.user?.id+':'+Profile.library?.id)==='true'};
    }catch{}
    const d={...djDefaults};
    for(const field of ['enabled','continuous','duplicates','strict'])if(typeof value?.[field]==='boolean')d[field]=value[field];
    if(['random','similar','favorites','library'].includes(value?.criterion))d.criterion=value.criterion;
    if(['songs','albums'].includes(value?.group))d.group=value.group;
    if(Number.isInteger(value?.limit))d.limit=Math.max(1,Math.min(10,value.limit));
    if(Number.isInteger(value?.refill))d.refill=Math.max(0,Math.min(d.limit-1,value.refill));
    return d;
  },
  invalidate(){this.queueEpoch++;this.filling=null;this.error='';},
  changeDJ(field,value){
    this.dj[field]=value;
    this.dj.refill=Math.min(this.dj.refill,this.dj.limit-1);
    this.shuffle=this.dj.enabled;
    try{localStorage.setItem(this.settingsKey(),JSON.stringify(this.dj));}catch{}
    if(field!=='continuous'){
      this.invalidate();
      this.queue=this.queue.filter(row=>row.queuedBy==='manual');
      if(this.series){this.series.after=this.key(MediaUI.playing);this.series.offset=0;this.series.end=false;}
      this.fill(MediaUI.playing,true);
    }else if(value){this.fill(MediaUI.playing,true);}
    this.paint();this.warmNext();
    if(this.view==='dj')this.drawDJ();
  },
  openDJ(){this.present('dj','Auto DJ');this.drawDJ();},
  drawDJ(){
    const body=$('listening-body'),d=this.dj;
    const field=(key,label,choices)=>{
      const row=el('label','dj-field'),control=el('select');control.id='dj-'+key;
      row.append(el('span','',label),control);
      for(const [value,text] of choices){
        const opt=el('option','',text);opt.value=value;control.append(opt);
      }
      control.value=String(d[key]);control.onchange=()=>this.changeDJ(key,['limit','refill'].includes(key)?Number(control.value):control.value);
      return row;
    };
    const toggle=(key,label,help)=>{
      const row=el('label','dj-field dj-toggle'),text=el('span');text.append(el('strong','',label));
      if(help)text.append(el('small','',help));
      const input=el('input');input.id='dj-'+key;input.type='checkbox';input.setAttribute('role','switch');input.checked=d[key];
      input.onchange=()=>this.changeDJ(key,input.checked);row.append(text,input);return row;
    };
    body.replaceChildren(toggle('enabled','Activar Auto DJ','Agrega música a tu cola mientras escuchás.'));
    if(!d.enabled)return;
    body.append(field('group','Agregar',[['songs','Canciones'],['albums','Canciones en orden de álbum']]),
      field('criterion','Elegir de',[['similar','Música parecida'],['random','Al azar'],['favorites','Mis favoritas'],['library','Mi biblioteca']]),
      field('limit','Próximas en la cola',Array.from({length:10},(_,i)=>[i+1,String(i+1)])),
      field('refill','Rellenar cuando queden',Array.from({length:d.limit},(_,i)=>[i,String(i)])),
      toggle('duplicates','Permitir repetir rolas','Permite volver a elegir una pista que ya escuchaste.'),
      toggle('strict','Solo similares','Según la radio de la fuente o el artista de la rola actual.'));
  },
  trackMenu(card,item){
    if(item.type!=='song')return;
    const menu=()=>{
      this.present('track',item.title||'Opciones de la rola');
      $('listening-body').append(this.action('Reproducir a continuación',()=>{this.playNext(item);$('listening-dialog').close();},'primary'),
        this.action('Agregar a playlist',()=>this.chooseList(item)));
    };
    card.addEventListener('contextmenu',event=>{event.preventDefault();menu();});
    card.addEventListener('keydown',event=>{if(event.key==='ContextMenu'||(event.shiftKey&&event.key==='F10')){event.preventDefault();menu();}});
    const picture=card.querySelector('.record-picture');
    if(picture){const more=this.iconButton('more','Opciones de la rola',menu);more.classList.add('record-menu');picture.append(more);}
  },
  async playNext(item){
    const token=this.serial,session=this.playSession;
    try{
      if(item.reference){
        const data=await RecordCards.resolve(item);
        if(token!==this.serial||session!==this.playSession)return;
        if(data.tracks?.length!==1)throw Error('Elegí una rola individual.');
        item=data.tracks[0];
      }
      const id=this.key(item);if(!id)return;
      if(!MediaUI.playing){await this.playItem(item);return;}
      this.invalidate();
      if(!this.dj.duplicates)this.queue=this.queue.filter(row=>this.key(row)!==id);
      this.queue.unshift({...item,queuedBy:'manual'});
      this.trimQueue();this.queueChanged();toast('Va a sonar a continuación.');
    }catch(e){if(token===this.serial)toast(e.message);}
  },
  trimQueue(){
    let left=Math.max(0,this.dj.limit-this.queue.filter(row=>row.queuedBy==='manual').length);
    const before=this.queue.length;
    this.queue=this.queue.filter(row=>{
      if(row.queuedBy==='manual')return true;
      if(left<=0)return false;
      left--;return true;
    });
    if(before!==this.queue.length&&this.series&&!this.shuffle){
      const tail=this.queue.filter(t=>t.queuedBy==='list').at(-1);
      this.series.after=this.key(tail)||this.series.last;
      this.series.offset=0;this.series.end=false;
    }
  },
  playItem(item){
    if(item.job_id&&item.url)return MediaUI.play(item);
    if(this.ready?.id===this.key(item)&&this.ready.url)return Player.start(item,this.ready.url);
    return Player.stream(item);
  },
  startList(index){
    const track=this.currentItems[index];if(!track)return;
    this.invalidate();this.queue=[];this.recent=[];this.history=[];this.rewinding=false;
    this.series={key:this.selectedList,offset:index+1,end:false,last:this.key(track)};
    if(!this.shuffle){
      this.queue=this.currentItems.slice(index+1,index+1+this.dj.limit).map(t=>({...t,queuedBy:'list'}));
      this.series.offset+=this.queue.length;
      this.series.end=this.offset==null&&this.series.offset>=this.currentItems.length;
    }
    this.expected=this.key(track);
    $('listening-dialog').close();this.playItem(track);this.fill(track,true);
  },
  cancelWarm(){
    clearTimeout(this.warmTimer);this.warmTimer=null;this.warmed='';this.ready=null;
    this.warm?.controller.abort();
  },
  warmNext(){
    clearTimeout(this.warmTimer);
    const item=this.queue[0],id=this.key(item),token=this.serial;
    if(!this.dj.continuous||!MediaUI.playing||!id||item.job_id||item.reference)return;
    if(this.warm||this.warmed===id)return;
    this.warmTimer=setTimeout(async()=>{
      if(this.warm||token!==this.serial||id!==this.key(this.queue[0])||!MediaUI.playing||!this.dj.continuous)return;
      const controller=new AbortController(),task={id,controller};
      this.warm=task;this.warmed=id;
      const timer=setTimeout(()=>controller.abort(),60000);
      try{
        const response=await fetch(Profile.scope('/api/listen/'+encodeURIComponent(id)+'/prepare'),{
          method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}',signal:controller.signal
        });
        if(response.ok){
          const data=await response.json();
          if(this.serial===token&&this.key(this.queue[0])===id&&!controller.signal.aborted){
            const url=safeUrl(data.url,'/api/listen/')||safeUrl(data.url,'/api/files/');
            if(url)this.ready={id,url};
          }
        }
      }catch{}finally{
        clearTimeout(timer);
        if(this.warm===task)this.warm=null;
        if(this.key(this.queue[0])!==id)this.warmNext();
      }
    },300);
  },
  queueChanged(){
    if(this.view==='queue'&&!this.dragging)this.drawQueue();
    this.warmNext();
  },
  stop(){
    this.invalidate();this.playSession++;this.series=null;this.queue=[];this.cancelWarm();
    this.expected=this.last='';this.recent=[];this.history=[];this.rewinding=false;this.contextTracks=[];this.contextHeard.clear();this.paint();
  },
  starting(item){
    const id=this.key(item);
    if(id!==this.expected&&id!==this.last){
      this.invalidate();this.series=null;this.queue=this.queue.filter(row=>row.queuedBy==='manual');this.rewinding=false;
      this.contextHeard.clear();
      const card=this.cardFor.get(item);
      if(card?.isConnected){
        this.contextTracks=Array.from(card.parentElement.children,n=>this.cardData.get(n)).filter(t=>t&&!t.reference);
      }else if(item.job_id){
        this.contextTracks=(window.MediaUI?.items||[]).map(file=>({...file,id:this.id(file)}));
      }else{
        this.contextTracks=[];
      }
    }
    if(this.series&&item.queuedBy==='list')this.series.last=id;
    this.paint();
  },
  async played(item){
    if(!item||!Profile.user)return;
    const key=this.key(item),token=this.serial;
    if(!key)return;
    if(!this.series&&!this.shuffle)this.contextHeard.add(key);
    if(this.last===key){this.expected='';this.fill(item);this.queueChanged();this.paint();return;}
    this.last=key;this.recent=[...this.recent.filter(k=>k!==key),key].slice(-60);
    if(!this.rewinding)this.history.push(item);
    this.history=this.history.slice(-60);this.rewinding=false;this.expected='';
    this.paint();this.fill(item);this.queueChanged();
    try{await post('/api/listening/played',{id:key});}
    catch(e){if(token===this.serial&&Profile.user)this.error=e.message;}
  },
  toggleShuffle(){this.changeDJ('enabled',!this.dj.enabled);},
  fill(item,force=false){
    if(!item||this.queue.length>=this.dj.limit||(!force&&this.queue.length>this.dj.refill))return Promise.resolve();
    if(this.filling)return this.filling;
    const epoch=this.queueEpoch,token=this.serial;
    this.filling=this.fetchNext(item,epoch,token).catch(e=>{if(epoch===this.queueEpoch&&token===this.serial)this.error=e.message;})
      .finally(()=>{if(epoch===this.queueEpoch&&token===this.serial){this.filling=null;this.queueChanged();}});
    return this.filling;
  },
  async fetchNext(item,epoch,token){
    const seed=this.key(item);if(!seed)return;
    const live=()=>epoch===this.queueEpoch&&token===this.serial;
    const d=this.dj,left=d.limit-this.queue.length;
    const occupied=new Set([seed,...this.queue.map(t=>this.key(t))]);this.error='';
    const add=(track,kind)=>{
      const id=this.key(track);
      if(id&&!occupied.has(id)&&this.queue.length<d.limit){this.queue.push({...track,queuedBy:kind});occupied.add(id);}
    };
    if(!this.shuffle){
      if(this.series){
        if(this.series.end)return;
        const args=new URLSearchParams({limit:left,offset:this.series.offset});
        if(this.series.after)args.set('after',this.series.after);
        const data=await api('/api/listening/lists/'+this.series.key+'?'+args);
        if(!live())return;
        this.series.after=null;this.series.offset=data.next_offset;this.series.end=data.next_offset==null;
        data.items.forEach(t=>add(t,'list'));
      }else{
        const context=this.contextTracks;
        const tail=this.queue.filter(t=>t.queuedBy==='context').at(-1)||item;
        const start=context.findIndex(t=>this.key(t)===this.key(tail));
        if(start>=0)context.slice(start+1).forEach(t=>{if(!this.contextHeard.has(this.key(t)))add(t,'context');});
      }
      return;
    }
    const skip=new Set([...occupied,...(d.duplicates?[]:this.recent)]);
    if(d.criterion==='random'&&d.group==='songs'&&!d.strict&&!this.series){
      const pool=[...this.pool.values()].filter(t=>!skip.has(this.key(t)));
      while(pool.length&&this.queue.length<d.limit)add(pool.splice(Math.floor(Math.random()*pool.length),1)[0],'auto');
    }
    if(this.queue.length>=d.limit)return;
    const exclude=[...new Set([...occupied,...skip])].slice(0,100);
    const last=this.queue.filter(t=>t.queuedBy==='auto').at(-1);
    const result=await post('/api/listening/next',{id:seed,exclude,limit:d.limit-this.queue.length,
      criterion:d.criterion,group:d.group,strict:d.strict,list_id:this.series&&d.criterion==='random'?this.series.key:null,
      tail:d.group==='albums'?this.key(last||item):null});
    if(live())result.items.forEach(t=>add(t,'auto'));
  },
  async next(index=0){
    const epoch=this.queueEpoch,token=this.serial;
    if(!this.queue.length)await this.fill(MediaUI.playing,true);
    if(epoch!==this.queueEpoch||token!==this.serial)return;
    const chosen=this.queue[index];if(!chosen)return;
    this.queue.splice(0,index+1);this.expected=this.key(chosen);
    if(this.view==='queue')this.drawQueue();
    await this.playItem(chosen);
  },
  previous(){
    if(this.history.length<2){$('music-audio').currentTime=0;return;}
    const current=this.history.pop(),prior=this.history.at(-1);
    this.invalidate();
    this.queue.unshift({...current,queuedBy:'manual'});this.trimQueue();this.rewinding=true;
    this.expected=this.key(prior);this.playItem(prior);
  },
  openQueue(){
    this.present('queue','Cola de reproducción');this.drawQueue();this.fill(MediaUI.playing,true);
  },
  move(from,to){
    if(from===to||from<0||to<0||from>=this.queue.length||to>=this.queue.length)return;
    const [track]=this.queue.splice(from,1);
    this.queue.splice(to,0,track);this.queueChanged();
  },
  drag(handle,row){
    handle.onkeydown=e=>{
      const step=e.key==='ArrowUp'?-1:e.key==='ArrowDown'?1:0;if(!step)return;
      e.preventDefault();const i=Number(row.dataset.queueIndex),j=Math.max(0,Math.min(this.queue.length-1,i+step));
      this.move(i,j);$('listening-body').querySelector('[data-queue-index="'+j+'"] .queue-grip')?.focus();
    };
    handle.onpointerdown=e=>{
      if(e.button!==0||!e.isPrimary)return;
      e.preventDefault();this.dragging=true;handle.setPointerCapture(e.pointerId);
      const initial=Number(row.dataset.queueIndex);
      row.classList.add('moving');let dest=initial;
      const marker=to=>{
        $('listening-body').querySelectorAll('.drop-target').forEach(n=>n.classList.remove('drop-target'));
        const target=$('listening-body').querySelector('[data-queue-index="'+to+'"]');
        target?.classList.add('drop-target');
      };
      handle.onpointermove=event=>{
        const target=document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-queue-index]');
        if(target){dest=Number(target.dataset.queueIndex);marker(dest);}
        const dialog=$('listening-dialog'),bounds=dialog.getBoundingClientRect();
        if(event.clientY<bounds.top+55)dialog.scrollTop-=16;
        else if(event.clientY>bounds.bottom-50)dialog.scrollTop+=16;
      };
      const done=apply=>{
        this.dragging=false;handle.onpointermove=handle.onpointercancel=handle.onpointerup=handle.onlostpointercapture=null;
        if(apply&&dest!==initial)this.move(initial,dest);else this.drawQueue();
      };
      handle.onpointerup=()=>done(true);handle.onpointercancel=handle.onlostpointercapture=()=>done(false);
    };
  },
  drawQueue(){
    const body=$('listening-body');if(!body||this.view!=='queue'||this.dragging)return;
    const controls=el('div','queue-controls');
    controls.append(el('span','section-copy',this.queue.length+' próximas'),this.action('Auto DJ',()=>this.openDJ()));
    body.replaceChildren(controls);
    this.queue.forEach((item,i)=>{
      const row=this.row(item,()=>this.next(i));row.dataset.queueIndex=i;row.classList.add('queue-row');
      const grip=this.iconButton('grip','Mover rola · flechas arriba o abajo',()=>{});grip.classList.add('queue-grip');
      this.drag(grip,row);row.prepend(grip,el('small','queue-number',String(i+1)));
      const seconds=Number(item.duration_seconds||item.duration);
      const duration=Number.isFinite(seconds)&&seconds>0?Math.floor(seconds/60)+':'+String(Math.floor(seconds%60)).padStart(2,'0'):item.duration||'—';
      const heart=this.iconButton('heart','Guardar en Favoritas',()=>this.like(item));heart.dataset.likeId=this.id(item);
      this.paintHeart(heart,item);row.append(el('small','queue-duration',duration),heart);
      body.append(row);
    });
    if(!this.queue.length)body.append(el('p','section-copy',this.error||(this.filling?'Buscando rolas…':this.shuffle?'Con estos ajustes ya no hay más rolas disponibles.':'Elegí «Reproducir a continuación» en una rola o activá Auto DJ.')));
  }
};
window.ListeningCollection=ListeningCollection;
ListeningCollection.mount();
if(window.Profile?.user)ListeningCollection.load();
