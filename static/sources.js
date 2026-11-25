'use strict';

const exportSite = ['Guardá las cookies de este sitio', 'Abrí tu exportador local de cookies desde Extensiones. Elegí solo el sitio actual y guardá el archivo .txt en formato Netscape.'];
const guideData = {
  youtube: {
    title:'Conectar YouTube Music',
    steps:[['Abrí tu Inicio de YouTube Music','En la computadora del servidor, entrá a music.youtube.com con la cuenta cuyas recomendaciones querés usar.'], exportSite, ['Elegí el archivo en Music Ingest','En Inicio, buscá YouTube Music y tocá «Cargar mis cookies .txt». Seleccioná el archivo que acabás de guardar.']],
    note:'El archivo permite usar tu sesión. Mantenelo en privado. Si necesitás un exportador, la guía de yt-dlp enlaza opciones para tu navegador.',
    link:'https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp', label:'Ver exportadores en la guía de yt-dlp ↗'
  },
  qobuz: {
    title:'Conectar Qobuz',
    steps:[['Abrí tu música en Qobuz','En la computadora del servidor, entrá a www.qobuz.com con tu cuenta y abrí «Mis compras».'], exportSite, ['Cargá tu archivo en la tarjeta FLAC','En Inicio → Qobuz, tocá «Cargar mis cookies .txt» y elegí el archivo. La app revisa las pistas disponibles.']],
    note:'Music Ingest es gratis. No todas las rolas están disponibles en FLAC. Depende del máster que entregue el artista o la disquera y de la edición que Qobuz te permita descargar. Guardá tu archivo de sesión en privado.',
    link:'https://help.qobuz.com/en/articles/369151-tutorial-how-to-download-without-qobuz-downloader', label:'Ver la ayuda oficial de Qobuz ↗'
  },
  html: {
    title:'Importar tu Inicio guardado',
    steps:[['Cargá tus recomendaciones','En un navegador de computadora, abrí Inicio en music.youtube.com y bajá un poco para que aparezcan más recomendaciones.'], ['Guardá la página','Presioná Ctrl + S (⌘ + S en Mac). Elegí «Página web, completa» y guardá el archivo .html.'], ['Importá el archivo .html','En Inicio → YouTube Music, tocá «Subir HTML». Elegí el archivo .html que guardaste.']],
    note:'Tu página guardada conserva las recomendaciones de ese momento. Para renovarlas, podés importar otra copia.',
    link:'https://music.youtube.com/', label:'Abrir YouTube Music ↗'
  }
};

guideData.qhtml={
  title:'Importar una página de Qobuz',
  steps:[['Abrí una página de música','En la computadora, abrí en Qobuz una página que muestre enlaces a pistas o álbumes.'],guideData.html.steps[1],['Elegí el HTML de Qobuz','En Inicio → Qobuz, tocá «Subir HTML» y elegí el archivo .html que guardaste.']],
  note:'El HTML agrega referencias a Inicio. Para guardar audio, Qobuz tiene que ofrecerte el archivo de esa pista.',
  link:'https://www.qobuz.com/',label:'Abrir Qobuz ↗'
};
const SourceGuide = {
  kind:'youtube', index:0, paused:false, motion:matchMedia('(prefers-reduced-motion: reduce)'),
  open(kind) {
    this.kind=kind; this.index=0; this.paused=this.motion.matches;
    const guide=guideData[kind];
    $('source-help-title').textContent=guide.title;
    $('guide-note').textContent=guide.note;
    $('help-official').href=guide.link; $('help-official').textContent=guide.label;
    $('qobuz-manual').hidden=kind!=='qobuz'; $('qobuz-manual').open=false;
    this.paint(); $('source-help').showModal(); $('help-close').focus();
  },
  paint() {
    const guide=guideData[this.kind], step=this.index+1;
    const [heading, instruction]=guide.steps[this.index];
    $('guide-count').textContent='Paso '+step+' de '+guide.steps.length;
    $('guide-heading').textContent=heading; $('guide-instruction').textContent=instruction;
    document.querySelectorAll('.guide-progress i').forEach((item,i)=>item.classList.toggle('filled',i<=this.index));
    const picture=$('help-image');
    picture.src='/static/help/'+this.kind+'-'+step+(this.paused?'.png':'.gif');
    picture.alt='Demostración de «'+heading+'».';
    $('guide-motion').textContent=this.paused?'Ver animación':'Ver imagen fija';
    const exportStep=['youtube','qobuz'].includes(this.kind) && this.index===1;
    $('guide-exporter').hidden=!exportStep;
    $('help-official').hidden=exportStep && this.kind==='youtube';
    $('guide-prev').disabled=this.index===0;
    $('guide-next').textContent=this.index===guide.steps.length-1?'Listo':'Siguiente →';
  },
  close() { $('source-help').close(); }
};
$('guide-prev').addEventListener('click',()=>{if(SourceGuide.index>0){SourceGuide.index--;SourceGuide.paint();}});
$('guide-next').addEventListener('click',()=>{
  if(SourceGuide.index===guideData[SourceGuide.kind].steps.length-1){SourceGuide.close();return;}
  SourceGuide.index++; SourceGuide.paint();
});
$('guide-motion').addEventListener('click',()=>{SourceGuide.paused=!SourceGuide.paused;SourceGuide.paint();});
SourceGuide.motion.addEventListener('change',event=>{if($('source-help').open){SourceGuide.paused=event.matches;SourceGuide.paint();}});
$('source-help').addEventListener('close',()=>{
  $('help-image').removeAttribute('src'); $('qobuz-link').value=''; status('guide-status','');
});

const SourceUI = {
  epoch:0, read:0, busy:false, settings:null,
  label(value) {
    return ({flac:'FLAC',mp3:'MP3',original:'Audio original',auto:'Automático'})[value] || (value||'').toUpperCase();
  },
  tag(track) {
    const lossless=track.output_format==='flac';
    const badge=el('span','result-format'+(lossless?' lossless':''),this.label(track.output_format));
    if(track.has_flac&&!lossless)badge.title='También disponible en FLAC';
    return badge;
  },
  sourceName(key){return Discovery.name(key);},
  quality(file) {
    const info = [SourceUI.label(file.format)];
    if (file.format === 'flac') {
      if (file.bit_depth) info.push(file.bit_depth+' bits');
      if (file.sample_rate) info.push((file.sample_rate/1000).toLocaleString('es')+' kHz');
    }
    return info.filter(Boolean).join(' · ');
  },
  output(track, mode) {
    if (mode === 'auto') return track.output_format || 'mp3';
    if (mode === 'original' && track.only_qobuz) return 'flac';
    return mode;
  },
  refreshFormats() {
    const tracks = state.preview?.tracks || [];
    const selected = tracks.filter(t=>state.selected.has(t.id));
    const select = $('format');
    const before=select.value;
    const formats=[...new Set(selected.flatMap(t=>t.formats || (t.has_flac?['mp3','flac']:['mp3'])))];
    select.replaceChildren(new Option('Preferencia de mi biblioteca','auto'));
    for(const f of formats){
      const option=new Option(this.label(f),f);
      option.disabled=selected.some(t=>!(t.formats || (t.has_flac?['mp3','flac']:['mp3'])).includes(f));
      select.append(option);
    }
    select.value=[...select.options].some(o=>o.value===before&&!o.disabled)?before:'auto';
    const badges = new Map(Array.from($('preview-tracks').querySelectorAll('[data-format-id]'), n=>[n.dataset.formatId,n]));
    for (const track of tracks) {
      const badge = badges.get(track.id);
      if (!badge) continue;
      const fmt = this.output(track, select.value);
      const via = track.source?.includes('.') ? track.source : (fmt === 'flac' || track.only_qobuz ? 'qobuz' : 'youtube');
      badge.replaceChildren(document.createTextNode(this.label(fmt)), sourceMark(via, this.sourceName(via)));
      badge.classList.toggle('lossless',fmt==='flac');
    }
  },
  reset() {
    this.epoch++; this.read++; this.settings=null; this.busy=false;
    $('home-sections').replaceChildren();
    for (const id of ['home-status','source-status','youtube-state','qobuz-state','html-state']) $(id).textContent='';
    for (const id of ['youtube-file','qobuz-file','html-file','qobuz-link']) $(id).value='';
    for (const id of ['youtube-clear','qobuz-clear','html-clear','qobuz-sync']) $(id).hidden=true;
    $('source-best').checked=true; $('source-best').disabled=true; $('qobuz-manual').open=false;
    if ($('source-help').open) $('source-help').close();
    this.lockControls(false);
  },
  local() { return ['localhost','127.0.0.1','[::1]'].includes(location.hostname); },
  lockControls(busy) {
    this.busy=busy;
    for (const item of document.querySelectorAll('#page-inicio input, #home-refresh, #page-inicio .source-box button:not(.help-dot)')) item.disabled=busy;
    const allowed=this.local() && this.settings?.can_import_sessions===true;
    for(const id of ['youtube-file','qobuz-file','qobuz-link']) $(id).disabled=busy||!allowed;
    $('qobuz-link-form').querySelector('button').disabled=busy||!allowed;
    document.querySelectorAll('[data-session-file]').forEach(input=>{input.disabled=busy||!allowed;});
    document.querySelectorAll('[data-local-note]').forEach(note=>note.hidden=allowed||(!this.settings&&this.local()));
    $('source-best').disabled=busy || !this.settings;
  },
  showSettings(data) {
    this.settings=data; Discovery.sources(data); this.lockControls(this.busy);
    $('source-best').checked=data.best; $('source-best').disabled=this.busy;
    $('youtube-state').textContent=data.youtube?'Archivo de sesión guardado':'';
    $('qobuz-state').textContent=(data.qobuz?'Sesión guardada · ':'')+(data.purchases?data.purchases+' pistas disponibles':'');
    $('html-state').textContent=data.html_count?data.html_count+' elementos importados':'';
    $('youtube-clear').hidden=!data.youtube;
    $('qobuz-clear').hidden=!data.qobuz&&!data.purchases;
    $('qobuz-sync').hidden=!data.qobuz;
    $('html-clear').hidden=!data.html_count;
  },
  async load(refresh=false) {
    if (!window.Profile?.owner()) return;
    const read=++this.read, epoch=this.epoch;
    if(!$('home-sections').childElementCount)window.RecordUX?.skeleton($('home-sections'));
    $('home-sections').setAttribute('aria-busy','true');
    status('home-status','Cargando tu Inicio…');
    try {
      const settings=await api('/api/sources');
      if (epoch!==this.epoch||read!==this.read) return;
      this.showSettings(settings);
      const data=await api('/api/home'+(refresh?'?refresh=true':''));
      if (epoch!==this.epoch||read!==this.read) return;
      Discovery.favorites=data.favorite_artists||[];
      this.render(data.sections);
      if(data.checking&&!data.sections.some(s=>s.items.length))window.RecordUX?.skeleton($('home-sections'),true);
      clearTimeout(this.verifyTimer);
      if(data.checking)this.verifyTimer=setTimeout(()=>{if(epoch===this.epoch&&state.page==='inicio'&&!document.hidden&&!this.busy)this.load();},6000);
      status('home-status',data.warning||(data.checking?'Verificando audio oficial y portadas…':''),!!data.warning);
    } catch (error) {
      if (epoch===this.epoch&&read===this.read){
        $('home-sections').querySelector('.record-skeleton-grid')?.remove();status('home-status',error.message,true);
      }
    } finally {
      if(epoch===this.epoch&&read===this.read)$('home-sections').setAttribute('aria-busy',String(!!$('home-sections').querySelector('.record-skeleton-grid')));
    }
  },
  render(sections) {
    Discovery.feed(sections);
  },
  async open(item) {
    if(item.reference)return Discovery.openReference(item);
    if (item.type==='artist') {navigate('buscar'); return Artists.open(item.id);}
    if (item.type==='playlist') {
      const epoch=this.epoch;
      await navigate('playlists'); if(epoch!==this.epoch||state.page!=='playlists')return;
      $('playlist-url').value='https://music.youtube.com/playlist?list='+encodeURIComponent(item.id);
      $('playlist-url').focus(); return;
    }
    return openPreview({type:item.type,id:item.id});
  },
  async action(message,work,output='source-status') {
    if (this.busy||!Profile.owner()) return;
    const epoch=this.epoch;
    this.read++; this.lockControls(true); status(output,message);
    try {
      const result=await work();
      if(epoch!==this.epoch)return;
      status(output,result||'Listo.'); toast(result||'Listo.');
      await this.load();
    } catch(error) {
      if(epoch===this.epoch) {
        status(output,error.message,true); toast(error.message);
        await this.load();
      }
    } finally {
      if(epoch===this.epoch)this.lockControls(false);
    }
  },
  async upload(kind,input) {
    const file=input.files[0]; input.value='';
    if (!file) return;
    const html=kind==='html';
    if(!html&&file.size>60000) {
      status('source-status','Elegí un archivo de cookies del sitio de hasta 60 KB.',true); return;
    }
    if(!html && (!this.local()||!this.settings?.can_import_sessions)){
      status('source-status','Abrí tu instalación en localhost desde la computadora del servidor para conectar una cuenta.',true);return;
    }
    const epoch=this.epoch;
    await this.action(html?'Leyendo tus recomendaciones…':'Conectando tu cuenta…',async()=>{
      const content=html?await readSourceHTML(file,'youtube'):await file.text();
      if(epoch!==this.epoch)return;
      if(!html){
        const valid=kind==='youtube'?['youtube.com','www.youtube.com','music.youtube.com']:['qobuz.com','www.qobuz.com'];
        const rows=content.replace(/^\uFEFF/,'').split(/\r?\n/).map(line=>line.replace(/^#HttpOnly_/,'')).filter(line=>line.trim()&&!line.startsWith('#'));
        if(!rows.length||rows.some(line=>!valid.includes(line.split('\t')[0].replace(/^\./,'').toLowerCase())))throw Error('Exportá solo las cookies del sitio elegido en formato Netscape (.txt).');
      }
      const data=await api(html?'/api/sources/home-html':'/api/sources/'+kind+'/cookies',{method:'PUT',body:JSON.stringify({content})});
      if(html)return 'Se importaron '+data.imported+' elementos.';
      if(kind==='qobuz'&&epoch===this.epoch) {
        status('source-status','Sesión guardada. Buscando tus pistas…');
        return this.scan('');
      }
      return 'Cookies guardadas. Revisá tus recomendaciones arriba.';
    });
  },
  async scan(link) {
    const data=await post('/api/sources/qobuz/purchases',{link});
    return data.indexed+' pistas disponibles.'+(data.partial?' Algunas pistas quedaron pendientes.':'');
  }
};
window.SourceUI=SourceUI;
$('format').addEventListener('change',()=>SourceUI.refreshFormats());
$('source-best').addEventListener('change',()=>{
  const best=$('source-best').checked;
  SourceUI.action('Guardando tu preferencia…',async()=>{
    await api('/api/sources',{method:'PATCH',body:JSON.stringify({best})});
    return best?'La biblioteca elegirá FLAC cuando esté disponible.':'La biblioteca preferirá MP3.';
  });
});
$('home-refresh').addEventListener('click',()=>SourceUI.load(true));
for(const kind of ['youtube','qobuz','html']){
  const input=$(kind+'-file');
  input.addEventListener('change',()=>SourceUI.upload(kind,input));
  $(kind+'-clear').addEventListener('click',()=>SourceUI.action('Guardando cambios…',async()=>{
    const path=kind==='html'?'/api/sources/home-html':'/api/sources/'+kind+'/cookies';
    await api(path,{method:'DELETE',body:'{}'});
    return kind==='html'?'Se quitó la página importada.':'Se desconectó la fuente de esta biblioteca.';
  }));
}
$('qobuz-sync').addEventListener('click',()=>SourceUI.action('Revisando tus pistas de Qobuz…',()=>SourceUI.scan('')));
$('qobuz-link-form').addEventListener('submit',event=>{
  event.preventDefault(); const link=$('qobuz-link').value.trim(); $('qobuz-link').value='';
  if(link&&SourceUI.local()&&SourceUI.settings?.can_import_sessions)SourceUI.action('Revisando el enlace…',()=>SourceUI.scan(link),'guide-status');
});
for(const button of document.querySelectorAll('[data-source-help]'))button.addEventListener('click',()=>SourceGuide.open(button.dataset.sourceHelp));
$('help-close').addEventListener('click',()=>$('source-help').close());
