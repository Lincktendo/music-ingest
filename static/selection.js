'use strict';

// A selection belongs to one account/library and survives searches in that library.
// Only IDs are submitted; titles are display text, never download metadata.
const Selection={
 items:new Map(), revision:null, busy:false, operation:0, limit:50,
 icon(kind){
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
  const path=document.createElementNS(svg.namespaceURI,'path');
  path.setAttribute('d',kind==='download'?'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5':'m6 6 12 12M18 6 6 18');
  svg.append(path);return svg;
 },
 ensureBar(){
  if($('selection-bar'))return;
  const bar=el('section','selection-bar');bar.id='selection-bar';bar.hidden=true;bar.setAttribute('aria-label','Canciones seleccionadas');
  const count=el('strong','');count.id='bulk-count';count.setAttribute('role','status');
  const actions=el('div','selection-actions');
  const download=el('button','primary');download.type='button';download.id='bulk-download';download.append(this.icon('download'),el('span','','Descargar todo'));
  const clear=el('button','quiet');clear.type='button';clear.id='bulk-clear';clear.append(this.icon('clear'),el('span','','Deseleccionar'));
  const message=el('p','inline-status');message.id='bulk-message';message.setAttribute('role','status');
  download.addEventListener('click',()=>this.submit());clear.addEventListener('click',()=>this.clear());
  actions.append(download,clear);bar.append(count,actions,message);
  $('page-buscar').insertBefore(bar,$('artist-panel'));
 },
 sync(){
  const revision=window.Profile?.revision;
  if(this.revision!==revision){this.items.clear();this.revision=revision;this.busy=false;this.operation++;}
 },
 wrap(card,track){
  if(!track||typeof track.id!=='string'||!/^[A-Za-z0-9_-]{11}$/.test(track.id))return card;
  this.sync();this.ensureBar();
  const wrapper=el('div','selectable-card'+(card.classList.contains('artist-song')?' selectable-song':''));
  const label=el('label','track-select');const check=document.createElement('input');check.type='checkbox';
  check.dataset.bulkId=track.id;check.setAttribute('aria-label','Seleccionar '+(track.title||'canción'));
  check.title='Seleccionar '+(track.title||'canción');check.checked=this.items.has(track.id);check.disabled=this.busy;
  check.addEventListener('change',()=>this.toggle(track,check));label.append(check);wrapper.append(card,label);
  wrapper.classList.toggle('is-selected',check.checked);this.render();return wrapper;
 },
 // Optional adapter for callers that assign data-select-id/title to existing cards.
 decorate(root){
  for(const card of root.querySelectorAll('[data-select-id]')){
   if(card.parentElement?.classList.contains('selectable-card'))continue;
   const anchor=document.createComment('selection-card');card.before(anchor);
   const wrapper=this.wrap(card,{id:card.dataset.selectId,title:card.dataset.selectTitle||card.getAttribute('aria-label')||'canción'});
   if(wrapper===card)anchor.remove();else anchor.replaceWith(wrapper);
  }
 },
 toggle(track,input){
  this.sync();
  if(this.busy){input.checked=this.items.has(track.id);return;}
  if(input.checked){
   if(!this.items.has(track.id)&&this.items.size>=this.limit){input.checked=false;toast('Elegí hasta 50 canciones por descarga. Podés agregar otro grupo después.');return;}
   this.items.set(track.id,{id:track.id,title:track.title||'Canción'});
  }else this.items.delete(track.id);
  status('bulk-message','');this.render();
 },
 render(){
  this.ensureBar();
  const count=this.items.size;const bar=$('selection-bar');bar.hidden=!count;
  $('bulk-count').textContent=count+' '+(count===1?'canción seleccionada':'canciones seleccionadas')+' · máximo 50';
  const label=$('bulk-download').querySelector('span');
  label.textContent=this.busy?'Agregando…':Profile.owner()?'Descargar todo':'Enviar selección';
  $('bulk-download').disabled=this.busy||!count;$('bulk-clear').disabled=this.busy;
  for(const check of document.querySelectorAll('input[data-bulk-id]')){
   check.checked=this.items.has(check.dataset.bulkId);check.disabled=this.busy;
   check.closest('.selectable-card')?.classList.toggle('is-selected',check.checked);
  }
 },
 clear(){if(this.busy)return;this.items.clear();status('bulk-message','');this.render();},
 reset(){
  this.operation++;this.items.clear();this.busy=false;this.revision=window.Profile?.revision;
  if($('selection-bar')){status('bulk-message','');this.render();}
 },
 async submit(){
  this.sync();if(this.busy||!this.items.size||!Profile.user)return;
  const revision=Profile.revision,operation=++this.operation;
  const tracks=[...this.items.values()].map(track=>({id:track.id}));
  this.busy=true;status('bulk-message','Agregando '+tracks.length+' canciones…');this.render();
  try{
   const result=await post('/api/jobs',{tracks,format:'mp3'});
   if(revision!==Profile.revision||operation!==this.operation)return;
   for(const track of tracks)this.items.delete(track.id);
   this.busy=false;status('bulk-message','');this.render();state.jobsKey='';
   navigate(result.kind==='proposal'?'perfil':'descargas');
   toast(result.kind==='proposal'?(result.status==='approved'?'Tu selección se aprobó y ya está en la cola.':'Selección enviada. El dueño de la biblioteca la revisará.'):tracks.length+' canciones agregadas a Descargas.');
  }catch(error){
   if(revision!==Profile.revision||operation!==this.operation)return;
   const message=error.message||'No pudimos agregar la selección.';
   status('bulk-message',message+(message.includes('Revisá de nuevo')?' Actualizá la búsqueda o abrí de nuevo el artista y volvé a intentar.':' Tu selección se conserva para volver a intentar.'),true);
  }finally{
   if(revision===Profile.revision&&operation===this.operation){this.busy=false;this.render();}
  }
 }
};
window.Selection=Selection;
