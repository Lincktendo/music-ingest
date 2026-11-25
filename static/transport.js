'use strict';
// Keep one native media element alive across pages. The controls mirror media events,
// including pauses, seeks or volume changes made by the OS.
const Transport = (() => {
  const audio = $('music-audio');
  const box = el('div','music-transport');
  box.id='music-transport';
  box.setAttribute('aria-label','Controles de reproducción');
  const icons={
    play:'M7 4.8 19 12 7 19.2Z',pause:'M7 5h3.3v14H7zM14 5h3.3v14H14z',
    volume:'M3 9h4l5-4v14l-5-4H3z M16 8a6 6 0 0 1 0 8 M19 5a10 10 0 0 1 0 14',
    mute:'M3 9h4l5-4v14l-5-4H3z M16 9l5 6m0-6-5 6',
    previous:'M5 5v14m13-14L8 12l10 7Z',next:'M19 5v14M6 5l10 7-10 7Z'
  };
  function icon(key){
    const svg=document.createElementNS(NS,'svg'),p=document.createElementNS(NS,'path');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
    p.setAttribute('d',icons[key]);p.setAttribute('fill',['play','pause'].includes(key)?'currentColor':'none');
    p.setAttribute('stroke','currentColor');p.setAttribute('stroke-width','1.6');
    p.setAttribute('stroke-linecap','round');p.setAttribute('stroke-linejoin','round');svg.append(p);return svg;
  }
  function button(action){
    const b=el('button','transport-button');b.type='button';b.onclick=action;return b;
  }
  function describe(b,label,key){
    if(b.title===label)return;
    b.setAttribute('aria-label',label);b.title=label;b.replaceChildren(icon(key));
  }
  function slider(label,name,max,step){
    const input=el('input','transport-range');input.type='range';input.id=name;
    input.min=0;input.max=max;input.step=step;input.value=0;input.setAttribute('aria-label',label);return input;
  }
  function clock(value){
    const seconds=Math.floor(value)||0;
    return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
  }
  const toggle=button(()=>{
    if(audio.error&&MediaUI.playing){
      const current=MediaUI.playing,src=audio.getAttribute('src');
      if(src)Player.start(current,src);
    }else if(audio.paused){audio.play().catch(err=>{if(err.name==='NotAllowedError')toast('Tocá reproducir para iniciar.');});}
    else audio.pause();
  });
  toggle.id='transport-play';
  const previous=button(()=>ListeningCollection.previous());previous.id='transport-previous';describe(previous,'Rola anterior','previous');
  const next=button(()=>ListeningCollection.next());next.id='transport-next';describe(next,'Rola siguiente','next');
  const progress=slider('Posición de reproducción','transport-seek',1,.1);
  const times=el('span','transport-times'),elapsed=el('span','','0:00'),total=el('span','','—');
  times.append(elapsed,document.createTextNode(' / '),total);
  const mute=button(()=>{if(audio.volume===0){audio.volume=.65;audio.muted=false;}else audio.muted=!audio.muted;});
  mute.id='transport-mute';
  const volume=slider('Volumen','transport-volume',1,.01);
  volume.oninput=()=>{audio.muted=false;audio.volume=Number(volume.value);};
  const controls=el('div','transport-volume');controls.append(mute,volume);
  const seekBox=el('div','transport-timeline');seekBox.append(progress,times);
  box.append(previous,toggle,next,seekBox,controls);
  audio.after(box);audio.controls=false;audio.hidden=true;
  let dragging=false,counted=false,sequence=0,pending=false;
  function selectedDuration(){
    const t=MediaUI.playing;
    if(!t)return 0;
    const raw=t.duration_seconds||t.duration||0;
    return String(raw).split(':').reduce((acc,v)=>acc*60+Number(v),0)||0;
  }
  function paint(){
    const duration=Number.isFinite(audio.duration)&&audio.duration>0?audio.duration:0;
    const current=audio.currentTime||0;
    const display=duration||selectedDuration();
    progress.disabled=!duration||!!audio.error;
    progress.max=duration||display||1;
    if(!dragging)progress.value=current;
    const shown=dragging?Number(progress.value):current;
    elapsed.textContent=clock(shown);total.textContent=display?clock(display):'—';
    progress.setAttribute('aria-valuetext',clock(shown)+' de '+(display?clock(display):'duración pendiente'));
    progress.style.setProperty('--played',(display?Math.min(100,shown/display*100):0)+'%');
    const silent=audio.muted||audio.volume===0;
    volume.value=silent?0:audio.volume;volume.setAttribute('aria-valuetext',Math.round(Number(volume.value)*100)+' %');
    volume.style.setProperty('--played',Number(volume.value)*100+'%');
    describe(toggle,audio.error?'Reintentar reproducción':audio.paused?'Reproducir':'Pausa',audio.paused||audio.error?'play':'pause');
    describe(mute,silent?'Activar sonido':'Silenciar',silent?'mute':'volume');
    toggle.setAttribute('aria-busy',String(pending));
    box.classList.toggle('is-buffering',pending);
  }
  progress.oninput=()=>{dragging=true;paint();};
  progress.onchange=()=>{
    const value=Number(progress.value);dragging=false;
    if(Number.isFinite(audio.duration)&&audio.duration>0)audio.currentTime=Math.min(value,audio.duration);
    paint();
  };
  progress.onpointercancel=()=>{dragging=false;paint();};
  progress.onblur=()=>{dragging=false;paint();};
  for(const evt of ['timeupdate','durationchange','loadedmetadata','volumechange','play','ended']) audio.addEventListener(evt,paint);
  audio.addEventListener('waiting',()=>{pending=!audio.paused;paint();});
  audio.addEventListener('stalled',()=>{pending=!audio.paused&&audio.readyState<3;paint();});
  audio.addEventListener('pause',()=>{pending=false;paint();});
  audio.addEventListener('playing',()=>{
    pending=false;paint();
    if(!counted&&MediaUI.playing){counted=true;window.ListeningCollection?.played(MediaUI.playing);}
  });
  async function error(){
    pending=false;paint();
    const item=MediaUI.playing,serial=sequence;
    if(!item)return;
    let message=item.job_id?'No se pudo reproducir este archivo en tu navegador.':'No se pudo preparar el audio. Volvé a tocar reproducir.';
    const ident=item.id||item.source_id;
    if(audio.getAttribute('src')?.startsWith('/api/listen/')&&ident){
      try{const data=await api('/api/listen/'+encodeURIComponent(ident)+'/status');if(data.error)message=data.error;}catch{}
    }
    if(serial===sequence&&item===MediaUI.playing){$('player-artist').textContent=message;toast(message);}
  }
  audio.addEventListener('error',error);
  paint();
  return {
    begin(){sequence++;dragging=false;pending=true;counted=false;paint();},
    reset(){sequence++;dragging=false;pending=false;counted=false;paint();}
  };
})();
window.Transport=Transport;
