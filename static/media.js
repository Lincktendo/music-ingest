'use strict';
function actionIcon(name){
 const paths={play:'m8 5 11 7-11 7Z',download:'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',trash:'M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7',music:'M9 18V5l11-2v13M9 18c0 3-6 4-6 1s6-4 6-1m11-2c0 3-6 4-6 1s6-4 6-1',lyrics:'M5 4h14v16H5ZM8 8h8m-8 4h8m-8 4h5',close:'m6 6 12 12M6 18 18 6',refresh:'M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1',check:'m5 12 4 4L19 6',album:'M4 4h16v16H4ZM16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0'};
 const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.classList.add('action-svg');
 const p=document.createElementNS(NS,'path');p.setAttribute('d',paths[name]||paths.music);svg.append(p);return svg;
}
const MediaUI={
 items:[],playing:null,deleting:null,
 button(label,icon,handler,cls='quiet'){
  const button=el('button',cls+' action-button');button.type='button';button.append(actionIcon(icon),document.createTextNode(label));button.addEventListener('click',handler);return button;
 },
 link(url,label,icon){const link=fileLink(url,label);if(link){link.classList.add('action-button');link.prepend(actionIcon(icon));}return link;},
 controls(file,allowDelete=false){
  const row=el('div','track-actions');
  row.append(this.button('Escuchar','play',()=>this.play(file)));
  const download=this.link(file.url,'Guardar archivo','download');if(download)row.append(download);
  if(file.lyrics_url){const lyrics=this.link(file.lyrics_url,'Letra','lyrics');if(lyrics)row.append(lyrics);}
  if(allowDelete&&Profile.owner()&&file.source_id&&file.format)row.append(this.button('Eliminar','trash',()=>this.askDelete(file),'quiet danger-action'));
  return row;
 },
 play(file){
  const url=safeUrl(file.url,'/api/files/');if(!url){toast('Este archivo ya no está disponible. Actualizá la biblioteca.');return;}
  this.playing=file;const audio=$('music-audio');
  if(audio.getAttribute('src')!==url)audio.src=url;
  $('player-title').textContent=file.title||file.name||'Tu música';$('player-artist').textContent=[file.artist,file.album].filter(Boolean).join(' · ');
  $('music-player').hidden=false;document.body.classList.add('has-player');
  audio.play().catch(()=>toast('Tocá reproducir en el reproductor. Si tu navegador no admite el formato original, probá la versión MP3.'));
 },
 stop(){const audio=$('music-audio');audio.pause();audio.removeAttribute('src');audio.load();this.playing=null;$('music-player').hidden=true;document.body.classList.remove('has-player');},
 askDelete(file){this.deleting={file,revision:Profile.revision};$('delete-song-name').textContent=(file.title||file.name)+' — '+(file.artist||'Artista');status('delete-status','');$('delete-confirm').disabled=false;$('delete-song-dialog').showModal();},
 reset(){this.items=[];this.stop();this.deleting=null;$('delete-song-dialog').close();$('library-filter').value='';},
 render(items){this.items=items;this.draw();},
 draw(){
  const query=$('library-filter').value.trim().toLocaleLowerCase();
  const items=this.items.filter(x=>[x.artist,x.album,x.title].join(' ').toLocaleLowerCase().includes(query));
  const root=$('library');root.replaceChildren();
  if(!items.length){empty(root,query?'No encontramos esas canciones':'Todavía no hay música guardada',query?'Probá otro título, artista o álbum.':'Buscá tu primera canción y aparecerá acá al terminar.');return;}
  const groups=new Map(),normalize=s=>s.trim().toLocaleLowerCase();
  for(const file of items){const artist=file.artist?.trim()||'Artista sin identificar',album=file.album?.trim()||'Sencillos y sin álbum';const key=normalize(artist);if(!groups.has(key))groups.set(key,{name:artist,albums:new Map(),count:0});const group=groups.get(key);group.count++;const ak=normalize(album);if(!group.albums.has(ak))group.albums.set(ak,{name:album,tracks:[]});group.albums.get(ak).tracks.push(file);}
  let index=0;
  for(const artist of [...groups.values()].sort((a,b)=>a.name.localeCompare(b.name,'es'))){
   const box=el('details','artist-group');box.open=!!query||index++===0;const summary=el('summary','group-heading');const info=el('span','group-info');info.append(el('strong','',artist.name),el('small','',artist.albums.size+' álbumes · '+artist.count+' canciones'));summary.append(actionIcon('music'),info);box.append(summary);
   for(const album of [...artist.albums.values()].sort((a,b)=>a.name.localeCompare(b.name,'es'))){
    const card=el('details','album-group');card.open=!!query||artist.albums.size===1;const heading=el('summary','album-heading'),text=el('span','group-info');text.append(el('strong','',album.name),el('small','',album.tracks.length+' canciones'));heading.append(cover(album.tracks.find(t=>t.cover)?.cover),text);card.append(heading);
    for(const file of album.tracks.sort((a,b)=>(Number(a.track)||0)-(Number(b.track)||0)||(a.title||'').localeCompare(b.title||'','es'))){
     const row=el('div','saved-track'),info=el('div','saved-track-info');info.append(el('h3','',file.title||file.name),el('small','',[(file.format==='mp3'?'MP3':'Audio original'),duration(file.duration)].filter(Boolean).join(' · ')));const details=libraryMetadata(file);if(details)info.append(details);row.append(info,this.controls(file,true));card.append(row);
    }
    box.append(card);
   }
   root.append(box);
  }
 }
};
window.MediaUI=MediaUI;
$('close-player').append(actionIcon('close'));$('close-player').addEventListener('click',()=>MediaUI.stop());
$('library-filter').addEventListener('input',()=>MediaUI.draw());
$('music-audio').addEventListener('error',()=>{if(MediaUI.playing)toast('No pudimos reproducir este archivo. Actualizá la biblioteca o probá descargarlo.');});
$('delete-cancel').addEventListener('click',()=>$('delete-song-dialog').close());
$('delete-confirm').addEventListener('click',async()=>{
 const pending=MediaUI.deleting;if(!pending||pending.revision!==Profile.revision||!Profile.owner())return;
 $('delete-confirm').disabled=true;status('delete-status','Eliminando…');
 try{const file=pending.file;const result=await api('/api/library/'+encodeURIComponent(file.source_id)+'/'+encodeURIComponent(file.format),{method:'DELETE',body:'{}'});
  if(pending.revision!==Profile.revision)return;
  if(MediaUI.playing?.url===file.url)MediaUI.stop();$('delete-song-dialog').close();state.libraryKey='';state.jobsKey='';await Promise.all([loadLibrary(),loadJobs()]);toast(result.warning||'Canción eliminada de tu biblioteca.');
 }catch(error){if(pending.revision===Profile.revision)status('delete-status',error.message,true);}finally{$('delete-confirm').disabled=false;}
});
for(const id of ['refresh-library','refresh-following','refresh-artists','refresh-proposals'])$(id).prepend(actionIcon('refresh'));
