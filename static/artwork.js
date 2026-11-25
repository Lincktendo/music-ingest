'use strict';
const CoverEditor={
  serial:0, track:null, image:null, busy:false, x:.5,y:.5, drag:null,
  button(item,compact=false){
    const b=RecordCards.button(compact?'record-edit':'quiet artwork-action',compact?'✎':'Editar portada',()=>this.open(item));
    b.setAttribute('aria-label','Editar portada de '+(item.title||item.name));b.title='Editar portada';return b;
  },
  reset(){this.serial++;this.track=null;this.image=null;this.busy=false;this.drag=null;$('edit-art').close();},
  async open(item){
    if(!Profile.owner())return;
    const token=++this.serial;
    this.track=item;this.image=null;this.busy=false;this.drag=null;
    $('crop-save').disabled=true;$('crop-mode').value='fill';$('crop-zoom').value=1;
    $('crop-file').value='';this.x=this.y=.5;this.paint();status('crop-status','Cargando portada…');
    if(!$('edit-art').open)$('edit-art').showModal();
    try{
      if(!item.job_id){
        const data=await RecordCards.resolve(item);
        if(token!==this.serial)return;
        const track=data.tracks?.[0];if(!track)throw Error('La pista ya no está disponible.');
        this.track={...item,...track};
      }
      const t=this.track;
      const source=safeUrl(t.crop_source||t.original_cover||t.cover||t.video_cover,'/api/covers/');
      if(!source)throw Error('Elegí una imagen para crear la portada.');
      await this.load(source.startsWith('/api/covers/custom/')?Profile.scope(source):source,token);
    }catch(e){if(token===this.serial)status('crop-status',e.message,true);}
  },
  async load(url,token){
    const pic=new Image();pic.src=url;
    try{await pic.decode();}catch{throw Error('No se pudo leer la imagen. Podés elegir otra.');}
    if(token!==this.serial)return;
    this.image=pic;this.x=this.y=.5;$('crop-zoom').value=1;$('crop-save').disabled=false;
    status('crop-status','Arrastrá para elegir qué parte queda en la portada.');this.paint();
  },
  paint(){
    const cv=$('crop-view'),c=cv.getContext('2d'),n=cv.width;
    c.fillStyle='#12171f';c.fillRect(0,0,n,n);
    if(!this.image)return;
    const img=this.image,mode=$('crop-mode').value,zoom=Number($('crop-zoom').value);
    const w=img.naturalWidth,h=img.naturalHeight;
    const scale=(mode==='fill'?Math.max(n/w,n/h):Math.min(n/w,n/h))*zoom*(mode==='tile'?.5:1);
    const dw=scale*w,dh=scale*h;
    this.spanX=mode==='tile'?dw:n-dw;this.spanY=mode==='tile'?dh:n-dh;
    if(mode==='tile'){
      const tile=document.createElement('canvas');tile.width=Math.max(1,Math.round(dw));tile.height=Math.max(1,Math.round(dh));
      tile.getContext('2d').drawImage(img,0,0,tile.width,tile.height);
      c.save();c.translate(this.x*dw,this.y*dh);c.fillStyle=c.createPattern(tile,'repeat');c.fillRect(-dw,-dh,n+dw,n+dh);c.restore();
    }else c.drawImage(img,this.x*this.spanX,this.y*this.spanY,dw,dh);
  },
  async save(){
    if(this.busy||!this.image||!this.track)return;
    const item=this.track,rev=Profile.revision,token=this.serial;this.busy=true;$('crop-save').disabled=true;
    status('crop-status',item.job_id?'Guardando en el archivo…':'Guardando el encuadre…');
    const key=item.source_id||item.id;
    try{
      const image=$('crop-view').toDataURL('image/jpeg',.94).split(',')[1];
      const data=await api('/api/artwork/'+encodeURIComponent(key),{method:'PUT',body:JSON.stringify({image})});
      if(rev!==Profile.revision)return;
      const change=t=>{if(t&&(t.id===key||t.source_id===key||t.youtube_id===key)){t.original_cover=t.original_cover||t.cover;t.cover=data.cover;}};
      change(MediaUI.playing);change(item);
      change(DownloadUI.editing);if($('metadata-dialog').open&&DownloadUI.editing?.source_id===key)$('tag-image').firstElementChild?.replaceWith(cover(data.cover));
      for(const t of state.preview?.tracks||[])change(t);
      if(state.preview?.tracks?.length===1&&state.preview.tracks[0].id===key){
        const hero=$('preview-cover');hero.firstElementChild?.replaceWith(cover(data.cover));
      }
      for(const card of document.querySelectorAll('.record-card')){
        if(card.dataset.recordId===key)card.querySelector('.record-open').replaceChildren(cover(data.cover));
      }
      for(const section of Discovery.sections)for(const t of section.items)change(t);
      MediaUI.items.forEach(change);Player.paint();state.libraryKey='';state.jobsKey='';
      if(state.page==='biblioteca')await loadLibrary();
      if(state.page==='descargas')await loadJobs();
      if(rev===Profile.revision&&token===this.serial){$('edit-art').close();toast('Portada guardada.');}
    }catch(e){if(rev===Profile.revision&&token===this.serial)status('crop-status',e.message,true);}
    finally{if(token===this.serial){this.busy=false;$('crop-save').disabled=!this.image;}}
  }
};
window.CoverEditor=CoverEditor;
$('edit-art').addEventListener('close',()=>{CoverEditor.serial++;CoverEditor.image=null;CoverEditor.drag=null;});
const cropView=$('crop-view');
cropView.onpointerdown=e=>{if(!CoverEditor.image||!e.isPrimary)return;cropView.setPointerCapture(e.pointerId);CoverEditor.drag={x:e.clientX,y:e.clientY};};
cropView.onpointermove=e=>{
  const edit=CoverEditor,last=edit.drag;if(!last||!cropView.hasPointerCapture(e.pointerId))return;
  const scale=cropView.width/cropView.getBoundingClientRect().width;
  const clamp=v=>Math.max(0,Math.min(1,v));
  if(Math.abs(edit.spanX)>1)edit.x=clamp(edit.x+(e.clientX-last.x)*scale/edit.spanX);
  if(Math.abs(edit.spanY)>1)edit.y=clamp(edit.y+(e.clientY-last.y)*scale/edit.spanY);
  edit.drag={x:e.clientX,y:e.clientY};edit.paint();
};
cropView.onlostpointercapture=()=>CoverEditor.drag=null;
cropView.onkeydown=e=>{
  const delta={ArrowLeft:[-.05,0],ArrowRight:[.05,0],ArrowUp:[0,-.05],ArrowDown:[0,.05]}[e.key];
  if(!delta)return;e.preventDefault();const ed=CoverEditor;
  ed.x=Math.max(0,Math.min(1,ed.x+delta[0]));ed.y=Math.max(0,Math.min(1,ed.y+delta[1]));ed.paint();
};
$('crop-mode').onchange=()=>{CoverEditor.x=CoverEditor.y=.5;CoverEditor.paint();};
$('crop-zoom').oninput=()=>CoverEditor.paint();
$('crop-file').onchange=async e=>{
  const file=e.target.files[0];if(!file)return;
  if(file.size>12*1024*1024){status('crop-status','Elegí una imagen más pequeña.',true);return;}
  const token=++CoverEditor.serial,reader=new FileReader();
  reader.onload=()=>CoverEditor.load(reader.result,token).catch(err=>{if(token===CoverEditor.serial)status('crop-status',err.message,true);});
  reader.readAsDataURL(file);
};
$('crop-save').onclick=()=>CoverEditor.save();
