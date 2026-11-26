'use strict';
const RecordCards={
  streamMode:true, request:0,
  reset(){
    this.request++;this.streamMode=localStorage.getItem(this.modeKey())!=='download';this.paintMode();window.RecordMenus?.close(false);
    for(const id of ['player-detail','large-art'])$(id).close();
  },
  modeKey(){return 'music-ingest:open:'+ (Profile.user?.id||'guest')+':'+(Profile.library?.id||'');},
  paintMode(){const b=$('listen-mode');b.setAttribute('aria-checked',String(!this.streamMode));b.dataset.stream=String(this.streamMode);},
  artistNames(t){return t.type==='artist'?[t.title]:(t.artists?.length?t.artists.map(a=>a.name):(t.artist||'').split(';')).map(n=>n.trim()).filter(Boolean);},
  button(cls,label,action){
    const b=el('button',cls,label);b.type='button';b.onclick=action;return b;
  },
  card(t){
    const item={...t,type:t.type||'song',source:t.source||(t.id?.startsWith('qb:')?'qobuz':'youtube')};
    const card=el('article','record-card');card.dataset.recordId=item.id;
    const frame=el('div','record-picture');
    const open=()=>Selection.items.size?Selection.toggle(item):this.open(item);
    const photo=this.button('record-open',undefined,open);
    photo.setAttribute('aria-label','Abrir '+item.title);photo.append(cover(item.cover));frame.append(photo);
    const type=item.type==='album'?'Álbum':item.type==='artist'?'Artista':item.album?'Rola de álbum':'Single';
    const badge=(node,caption)=>{
      node.dataset.coverTip=caption;node.setAttribute('aria-label',caption);
      node.setAttribute('role','img');node.tabIndex=0;node.removeAttribute('title');
      node.addEventListener('click',open);
      return node;
    };
    const identity=el('span','record-identity');
    // Different periods and phase offsets keep neighboring covers from blinking together.
    let seed=2166136261;for(const ch of String(item.id))seed=Math.imul(seed^ch.charCodeAt(0),16777619)>>>0;
    identity.style.setProperty('--identity-period',(12+(seed%6000)/1000)+'s');
    identity.style.setProperty('--identity-phase',(-((seed>>>3)%12000)/1000)+'s');
    const kind=el('span','record-kind'+(type==='Rola de álbum'?' layered':''));
    kind.append(actionIcon(item.type==='album'?'album':item.type==='artist'?'artist':'music'));identity.append(badge(kind,type));
    const name=Discovery.name(item.source),source=sourceMark(item.source,name);
    source.classList.add('record-source');identity.append(badge(source,name));frame.append(identity);
    const saved=el('span','record-saved');saved.append(actionIcon('check'));frame.append(badge(saved,'Ya está en la biblioteca'));
    saved.hidden=!(window.DownloadUI?.isSaved(item)??item.downloaded);
    card.append(frame);
    const title=this.button('record-title',item.title||'Sin título',open);title.title=title.textContent;card.append(title);
    if(item.type!=='artist'){
      const by=el('div','record-by'),names=this.artistNames(item);by.title=names.join(', ');
      names.forEach((name,index)=>{
        if(index)by.append(document.createTextNode(', '));
        const artist=this.button('record-link',name,()=>this.artist(item,name));by.append(artist);
      });
      card.append(by);
    }
    if(item.type==='song'){
      const release=this.button('record-link record-release',item.album||'Single',()=>this.release(item));
      release.title=release.textContent;card.append(release);
    }
    const format=item.output_format||item.format;
    if(format){
      const chip=el('small','format-chip record-format',format.toUpperCase());
      chip.dataset.format=format.toLowerCase();chip.dataset.on='true';card.append(chip);
    }
    Selection.register(card,item);window.RecordUX?.selectOnHold(photo,item);
    window.ListeningCollection?.decorate(card,item);
    window.RecordMenus?.attach(card,item);
    return card;
  },
  async resolve(item){
    return post('/api/preview',item.reference?{url:item.url}:{id:item.id||item.source_id,type:item.type==='album'?'album':'song'});
  },
  enqueue(tracks){
    return post('/api/jobs',{format:'auto',tracks:tracks.map(t=>({id:t.id,expected_format:t.output_format}))});
  },
  save(item){return DownloadUI.review(item);},
  open(item){
    if(item.type==='artist')return this.artist(item,item.title);
    if(item.type==='album'||item.type==='playlist')return SourceUI.open(item);
    if(item.reference&&item.source==='qobuz')return Discovery.openReference(item,this.streamMode);
    if(this.streamMode)return item.fromFavorites?ListeningCollection.playFavorites(item):Player.stream(item);
    return this.save(item);
  },
  collection(kind,name,item){
    const q=new URLSearchParams({kind,name,source:item.source||'youtube',artist:kind==='album'?item.artist||'':''});
    return api('/api/collection?'+q);
  },
  async named(kind,name,item){
    const rev=Profile.revision,request=++this.request;
    try{
      const data=await this.collection(kind,name,item);
      if(rev!==Profile.revision||request!==this.request)return;
      if(data.open)return kind==='artist'?Artists.open(data.open.id):openPreview({id:data.open.id,type:'album'});
      Artists.close();$('results').hidden=true;$('results-heading').hidden=true;$('welcome').hidden=true;
      const panel=$('artist-panel');panel.hidden=false;
      panel.replaceChildren(this.button('quiet','← Volver a resultados',()=>Artists.close()),el('h2','',data.title));
      const grid=el('div','record-grid');
      for(const song of data.songs)grid.append(this.card(song));
      if(data.songs.length)panel.append(grid);else panel.append(el('p','section-copy','Esta fuente todavía no tiene otras pistas de '+name+'.'));
      panel.scrollIntoView({block:'start'});
    }catch(e){if(rev===Profile.revision&&request===this.request)toast(e.message);}
  },
  artist(item,name){
    navigate('buscar');this.request++;
    const id=item.artists?.find(a=>a.name===name)?.id||(item.type==='artist'?item.id:'');
    if(id?.startsWith('UC'))return Artists.open(id);
    return this.named('artist',name,item);
  },
  async release(item){
    if(item.type==='album')return SourceUI.open(item);
    const rev=Profile.revision,token=++this.request;
    if(!item.album)return openPreview(item.reference?{url:item.url}:{id:item.id,type:'song'});
    let album=item.album_browse_id||(item.source==='youtube'?item.album_id:'');
    if(!album&&item.source==='youtube'){
      try{const track=(await this.resolve(item)).tracks[0];album=track?.album_id;}catch{}
    }
    if(token!==this.request||rev!==Profile.revision)return;
    if(album)return openPreview({type:'album',id:album});
    navigate('buscar');return this.named('album',item.album,item);
  },
  previewReady(request,tracks){
    const coverNode=$('preview-cover');
    if(request.type==='playlist'&&Profile.owner()){
      const follow=this.button('quiet artwork-action','Seguir playlist',async()=>{
        $('preview-dialog').close();await navigate('playlists');
        $('playlist-url').value='https://music.youtube.com/playlist?list='+encodeURIComponent(request.id);$('playlist-url').focus();
      });coverNode.append(follow);
    }
    if(tracks.length===1&&Profile.owner()){
      const track=tracks[0];
      if(request.url&&track.video_cover&&/youtu(?:\.be|be\.com)/i.test(request.url))track.crop_source=track.video_cover;
      const edit=CoverEditor.button(track,true);edit.className='review-art-edit';coverNode.append(edit);
    }
  },
  undo(action,values,message){
    toast(message);const undo=this.button('text-action','Deshacer',async()=>{
      const rev=Profile.revision;
      try{await post('/api/home/choices',{action:action==='hide'?'unhide':'unfavorite',values});
        if(rev===Profile.revision){toast('Cambio deshecho.');if(state.page==='inicio')await SourceUI.load();}
      }catch(e){if(rev===Profile.revision)toast(e.message);}
    });if(values.length)$('toast').append(' ',undo);
  }
};
window.RecordCards=RecordCards;
const compactSearch=matchMedia('(max-width:720px)');
function searchHint(){ $('query').placeholder=compactSearch.matches?'Buscá música o pegá un enlace…':'Buscá una canción, artista o álbum, o pegá un enlace…'; }
compactSearch.addEventListener('change',searchHint);searchHint();
$('listen-mode').onclick=()=>{RecordCards.streamMode=!RecordCards.streamMode;localStorage.setItem(RecordCards.modeKey(),RecordCards.streamMode?'stream':'download');RecordCards.paintMode();};
RecordCards.streamMode=localStorage.getItem(RecordCards.modeKey())!=='download';RecordCards.paintMode();
const Player={
  sequence:0,
  async stream(item){
    if(MediaUI.playing?.id===item.id&&$('music-audio').getAttribute('src')&&!$('music-audio').error){
      if($('music-audio').paused)await $('music-audio').play().catch(()=>toast('Tocá reproducir para continuar.'));
      return;
    }
    // Start native playback within the tap, including Safari's first media gesture.
    // The same authenticated local URL prepares the audio and then serves byte ranges.
    if(!item.reference&&/^(?:[\w-]{11}|qb:\d{1,16}|ex:[a-f0-9]{32})$/.test(item.id||'')){
      this.start(item,Profile.scope('/api/listen/'+encodeURIComponent(item.id)+'?native=1'));return;
    }
    const token=++this.sequence,rev=Profile.revision;
    try{
      const data=await RecordCards.resolve(item);
      if(token!==this.sequence||rev!==Profile.revision)return;
      const t=data.tracks?.[0];if(!t)throw Error('Esta pista no está disponible.');
      this.start({...item,...t},Profile.scope('/api/listen/'+encodeURIComponent(t.id)+'?native=1'));
    }catch(e){if(token===this.sequence&&rev===Profile.revision)toast(e.message);}
  },
  start(item,url){
    const token=++this.sequence;MediaUI.playing=item;window.ListeningCollection?.starting(item);
    const audio=$('music-audio');
    if(audio.getAttribute('src')!==url||audio.error){audio.src=url;audio.load();}
    this.paint();$('music-player').hidden=false;document.body.classList.add('has-player');
    $('player-artist').textContent='Preparando audio…';window.Transport?.begin();
    audio.play().then(()=>{if(token===this.sequence)this.paint();}).catch(e=>{
      if(token===this.sequence&&e.name==='NotAllowedError'){
        this.paint();toast('Tocá ▶ en el reproductor para escuchar.');
      }
    });
  },
  paint(){
    const t=MediaUI.playing;if(!t)return;
    $('player-title').textContent=t.title||t.name;
    $('player-artist').textContent=[t.artist,t.album].filter(Boolean).join(' · ');
    $('player-cover').replaceChildren(cover(t.cover));DownloadUI.playerState(t);
    if($('player-detail').open)this.details();
  },
  stop(){
    this.sequence++;MediaUI.playing=null;window.ListeningCollection?.stop();window.Transport?.reset();
    const audio=$('music-audio');audio.pause();audio.removeAttribute('src');audio.load();
    $('music-player').hidden=true;document.body.classList.remove('has-player');$('player-detail').close();$('large-art').close();
  },
  details(){
    const t=MediaUI.playing;if(!t)return;
    $('detail-title').textContent=t.title||t.name;$('detail-artist').textContent=[t.artist,t.album].filter(Boolean).join(' · ');
    $('detail-art').replaceChildren(cover(t.cover));
    const actions=$('detail-actions');
    actions.replaceChildren(RecordCards.button('quiet',$('music-audio').paused?'Reproducir':'Pausa',()=>{
      const audio=$('music-audio');if(audio.paused)audio.play().catch(()=>toast('No se pudo reproducir.'));else audio.pause();
    }));
    actions.append(RecordCards.button('primary',DownloadUI.isSaved(t)?'Datos de la rola':'Revisar y descargar',()=>DownloadUI.details(t)));
    actions.append(RecordCards.button('quiet','Detener',()=>this.stop()));
    if(!$('player-detail').open)$('player-detail').showModal();
  }
};
window.Player=Player;
$('player-cover').onclick=()=>Player.details();
$('player-download').onclick=()=>{if(MediaUI.playing)DownloadUI.quickQueue(MediaUI.playing);};
$('detail-art').onclick=()=>{if(MediaUI.playing){$('large-image').replaceChildren(cover(MediaUI.playing.cover));$('large-art').showModal();}};
for(const e of ['pause','playing'])$('music-audio').addEventListener(e,()=>{if($('player-detail').open)Player.details();});
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$(b.dataset.close).close();
