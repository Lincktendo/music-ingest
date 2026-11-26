'use strict';
const Selection = {
  items:new Map(), busy:false, operation:0, limit:50,
  ensureBar(){
    if($('selection-bar'))return;
    const bar=el('section','record-selection');bar.id='selection-bar';bar.hidden=true;
    bar.setAttribute('aria-label','Acciones de selección');
    const count=el('strong');count.id='bulk-count';count.setAttribute('role','status');bar.append(count);
    for(const [id,label,action] of [
      ['bulk-download','Descargar',()=>this.download()],
      ['bulk-favorite','Favoritos',()=>this.preference('favorite')],
      ['bulk-hide','Ocultar de Inicio',()=>this.preference('hide')],
      ['bulk-clear','Deseleccionar',()=>this.clear()]]){
      const b=el('button',id==='bulk-download'?'primary':'quiet',label);b.type='button';b.id=id;b.onclick=action;bar.append(b);
    }
    document.querySelector('.topbar').after(bar);
  },
  register(card,item){
    const check=el('input','record-check');check.type='checkbox';check.dataset.bulkId=item.id;
    check.setAttribute('aria-label','Seleccionar '+item.title);check.title=check.getAttribute('aria-label');
    check.onchange=()=>this.toggle(item);card.querySelector('.record-picture').append(check);
    check.checked=this.items.has(item.id);card.classList.toggle('is-selected',check.checked);
  },
  toggle(item){
    if(this.busy)return;
    if(this.items.has(item.id))this.items.delete(item.id);
    else if(this.items.size>=this.limit)toast('Elegí hasta 50 elementos por tanda.');
    else this.items.set(item.id,item);
    this.render();
  },
  clear(){if(!this.busy){this.items.clear();this.render();}},
  reset(){this.operation++;this.busy=false;this.clear();},
  render(){
    this.ensureBar();
    const n=this.items.size,bar=$('selection-bar');bar.hidden=!n;
    document.body.classList.toggle('selecting-records',!!n);
    $('bulk-count').textContent=n+' '+(n===1?'selección':'selecciones');
    $('bulk-download').textContent=this.busy?'Un momento…':Profile.owner()?'Descargar':'Enviar selección';
    $('bulk-hide').hidden=!Profile.owner();$('bulk-favorite').hidden=false;
    bar.querySelectorAll('button').forEach(b=>b.disabled=this.busy);
    document.querySelectorAll('[data-bulk-id]').forEach(c=>{
      c.checked=this.items.has(c.dataset.bulkId);c.disabled=this.busy;
      c.closest('.record-card')?.classList.toggle('is-selected',c.checked);
    });
  },
  async run(action){
    if(this.busy||!this.items.size)return;
    const op=++this.operation;this.busy=true;this.render();
    try{await action([...this.items.values()],()=>op===this.operation);if(op===this.operation)this.items.clear();}
    catch(e){if(op===this.operation)toast(e.message);}
    finally{if(op===this.operation){this.busy=false;this.render();}}
  },
  preference(action){
    if(action==='favorite')return this.run((items,current)=>Artists.saveSelected(items,current));
    return this.run(async(items,current)=>{
      const values=action==='hide'?items.map(t=>t.id):items.flatMap(RecordCards.artistNames);
      const unique=[...new Set(values.filter(Boolean))];
      if(!unique.length)throw Error('Estas pistas todavía no tienen artista identificado.');
      const result=await post('/api/home/choices',{action,values:unique});if(!current())return;
      if(state.page==='inicio')await SourceUI.load();
      if(current())RecordCards.undo(action,result.changed,action==='hide'?'Ocultado de Inicio.':'Artistas agregados a favoritos.');
    });
  },
  download(){
    return this.run(async(items,current)=>{
      const groups=new Map();
      for(const item of items){
        if(!current())return;
        let tracks;
        if(item.type==='artist'){
          if(item.id.startsWith('UC'))tracks=(await api('/api/artists/'+encodeURIComponent(item.id))).songs;
          else tracks=(await RecordCards.collection('artist',item.title,item)).songs;
        }else tracks=(await RecordCards.resolve(item)).tracks;
        for(const t of tracks||[])groups.set(t.id,t);
      }
      if(!groups.size)throw Error('No hay pistas disponibles en la selección.');
      let sent=0;const tracks=[...groups.values()];
      while(sent<tracks.length){
        if(!current())return;
        const batch=tracks.slice(sent,sent+50);
        try{const result=await RecordCards.enqueue(batch);if(current()&&result.kind==='job')DownloadUI.trackJob(result.id);}catch(e){throw Error((sent?sent+' pistas ya están en la cola. ':'')+e.message);}
        sent+=batch.length;
      }
      if(current())toast(Profile.owner()?sent+' pistas en la cola.':'Selección enviada.');
    });
  }
};
window.Selection=Selection;
