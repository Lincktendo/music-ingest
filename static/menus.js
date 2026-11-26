'use strict';
// One small anchored menu is shared by covers, list rows and right-click actions.
const RecordMenus={
  attached:new WeakSet(),node:null,anchor:null,item:null,sequence:0,point:null,
  attach(card,item){
    if(this.attached.has(card))return;this.attached.add(card);
    const button=RecordCards.button('record-menu',undefined,event=>{
      event.stopPropagation();if(this.anchor===button&&this.node)this.close();else this.open(item,button);
    });
    button.append(ListeningCollection.icon('more'));button.title='Opciones de '+(item.title||'música');
    button.setAttribute('aria-label',button.title);button.setAttribute('aria-haspopup','menu');button.setAttribute('aria-expanded','false');
    (card.querySelector('.record-picture')||card).append(button);
    card.addEventListener('contextmenu',event=>{
      // Long-press selection consumes its own context event.
      if(event.defaultPrevented)return;
      event.preventDefault();event.stopPropagation();this.open(item,button,{x:event.clientX,y:event.clientY});
    });
    card.addEventListener('keydown',event=>{
      if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10'){
        event.preventDefault();this.open(item,button);
      }
    });
  },
  close(focus=true){
    this.sequence++;
    const node=this.node,anchor=this.anchor;this.node=null;this.anchor=null;this.item=null;
    if(node){try{node.hidePopover?.();}catch{}node.remove();}
    anchor?.setAttribute('aria-expanded','false');
    if(focus&&anchor?.isConnected)anchor.focus({preventScroll:true});
  },
  open(item,anchor,point=null){
    this.close(false);this.item=item;this.anchor=anchor;this.point=point;
    const menu=el('div','record-context-menu');menu.setAttribute('role','menu');
    menu.setAttribute('aria-label','Opciones de '+(item.title||'música'));menu.setAttribute('popover','manual');
    this.node=menu;(anchor.closest('dialog[open]')||document.body).append(menu);
    anchor.setAttribute('aria-expanded','true');this.root();
    if(menu.showPopover)menu.showPopover();this.position();
    menu.querySelector('button:not(:disabled)')?.focus({preventScroll:true});
    menu.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();this.close();return;}
      if(event.key==='Tab'){this.close(false);return;}
      if(event.target.matches('input'))return;
      const buttons=[...menu.querySelectorAll('button:not(:disabled)')];let i=buttons.indexOf(document.activeElement);
      if(event.key==='ArrowDown')i=(i+1)%buttons.length;
      else if(event.key==='ArrowUp')i=(i-1+buttons.length)%buttons.length;
      else if(event.key==='Home')i=0;else if(event.key==='End')i=buttons.length-1;else return;
      event.preventDefault();buttons[i]?.focus();
    });
  },
  position(){
    if(!this.node||!this.anchor?.isConnected){this.close(false);return;}
    const rect=this.anchor.getBoundingClientRect(),w=this.node.offsetWidth,h=this.node.offsetHeight;
    const viewport=window.visualViewport,margin=8;
    const leftEdge=viewport?.offsetLeft||0,topEdge=viewport?.offsetTop||0;
    const vw=viewport?.width||innerWidth,vh=viewport?.height||innerHeight;
    const x=this.point?.x??rect.right-w,y=this.point?.y??rect.bottom+6;
    this.node.style.left=Math.max(leftEdge+margin,Math.min(x,leftEdge+vw-w-margin))+'px';
    this.node.style.top=Math.max(topEdge+margin,Math.min(y,topEdge+vh-h-margin))+'px';
  },
  option(label,icon,action,{keep=false,disabled=false,active=false}={}){
    const button=RecordCards.button('record-menu-action',undefined,async()=>{
      if(disabled)return;
      if(!keep)this.close();
      try{await action();}catch(e){toast(e.message);}
    });
    const listening=['heart','plus','queue','continuous','play','more'].includes(icon);
    button.append(listening?ListeningCollection.icon(icon):actionIcon(icon),el('span','',label));
    button.setAttribute('role','menuitem');button.disabled=disabled;
    if(active)button.classList.add('is-active');this.node.append(button);return button;
  },
  root(){
    const item=this.item,song=(item.type||'song')==='song';this.node.replaceChildren();
    const saved=DownloadUI.isSaved(item),pending=DownloadUI.pendingFor(item);
    if(item.type!=='artist')this.option(saved?'Ver archivo y editar datos':pending?'Ver descarga':item.type==='album'?'Descargar álbum':'Descargar',
      saved?'check':'download',()=>DownloadUI.quickQueue(item));
    if(song){
      const liked=ListeningCollection.likes.has(ListeningCollection.key(item));
      this.option(liked?'Quitar de Favoritas':'Guardar en Favoritas','heart',()=>ListeningCollection.like(item),{active:liked});
      this.option('Reproducir ahora','play',()=>item.fromFavorites?ListeningCollection.playFavorites(item):Player.stream(item));
      this.option('Reproducir a continuación','continuous',()=>ListeningCollection.playNext(item));
      this.option('Agregar al final de la cola','queue',()=>ListeningCollection.appendQueue(item));
      this.option(item.album?'Ir al álbum':'Ver single','album',()=>RecordCards.release(item));
      this.option('Agregar a playlist','plus',()=>this.playlists(),{keep:true});
    }else if(item.type==='artist'){
      this.option('Ver artista','artist',()=>RecordCards.artist(item,item.title));
      const liked=!!Artists.findSaved(item);
      this.option(liked?'Quitar de tus artistas':'Guardar en Artistas','heart',()=>Artists.bookmark(item),{active:liked});
      if(Artists.savedRevision!==Profile.revision){const seq=this.sequence;Artists.loadSaved().then(()=>{if(seq===this.sequence&&this.node)this.root();}).catch(()=>{});}
    }
    else this.option('Ver '+(item.type==='playlist'?'playlist':'álbum'),'album',()=>RecordCards.open(item));
    this.node.append(el('hr','record-menu-separator'));
    this.option(Selection.items.has(item.id)?'Deseleccionar':'Seleccionar','check',()=>Selection.toggle(item));
    if(state.page==='inicio'&&Profile.owner())this.option('Ocultar de Inicio','close',async()=>{
      const rev=Profile.revision;const data=await post('/api/home/choices',{action:'hide',values:[item.id]});
      if(rev!==Profile.revision)return;await SourceUI.load();RecordCards.undo('hide',data.changed,'Ocultado de Inicio.');
    });
    this.position();
  },
  async playlists(){
    const seq=++this.sequence,item=this.item;
    this.node.replaceChildren();this.option('Volver','close',()=>this.root(),{keep:true});
    const loading=el('p','menu-hint','Cargando playlists…');this.node.append(loading);this.position();
    await ListeningCollection.load();if(seq!==this.sequence||!this.node)return;
    loading.remove();
    this.option('Crear playlist','plus',()=>this.createList(),{keep:true});
    for(const list of ListeningCollection.lists)this.option(list.name,'music',()=>this.addTo(list.id,item));
    if(!ListeningCollection.lists.length)this.node.append(el('p','menu-hint','Creá una playlist para guardar tus rolas juntas.'));
    this.position();
  },
  createList(){
    const item=this.item;this.node.replaceChildren();this.option('Volver','close',()=>this.playlists(),{keep:true});
    const form=el('form','record-menu-form'),label=el('label','','Nombre de la playlist'),input=el('input');
    input.required=true;input.maxLength=100;input.placeholder='Mi playlist';label.append(input);
    const button=el('button','primary','Crear y agregar');button.type='submit';form.append(label,button);this.node.append(form);
    const seq=this.sequence,rev=Profile.revision;
    form.onsubmit=async event=>{
      event.preventDefault();const name=input.value.trim();if(!name)return;button.disabled=true;
      try{
        const result=await post('/api/listening/lists',{name});
        if(rev!==Profile.revision)return;
        if(seq===this.sequence)this.close();await this.addTo(result.id,item,rev);
      }catch(e){if(rev===Profile.revision)toast(e.message);}finally{button.disabled=false;}
    };
    this.position();input.focus({preventScroll:true});
  },
  async addTo(id,item,rev=Profile.revision){
    const track=await ListeningCollection.identify(item);if(rev!==Profile.revision)return;
    await api('/api/listening/lists/'+encodeURIComponent(id)+'/'+encodeURIComponent(track),{method:'PUT',body:'{}'});
    if(rev!==Profile.revision)return;toast('Rola guardada en la playlist.');ListeningCollection.load();
  }
};
window.RecordMenus=RecordMenus;
document.addEventListener('pointerdown',event=>{
  if(RecordMenus.node&&!RecordMenus.node.contains(event.target)&&!RecordMenus.anchor?.contains(event.target))RecordMenus.close(false);
},true);
document.addEventListener('scroll',event=>{
  if(RecordMenus.node&&!RecordMenus.node.contains(event.target))RecordMenus.close(false);
},true);
window.addEventListener('resize',()=>RecordMenus.position());
