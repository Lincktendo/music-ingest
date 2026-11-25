'use strict';

const RecordUX = {
  pending: new Set(), busyTimer: 0, tourTimer: 0, spotlight: null,
  skeleton(root, replace = false) {
    if (!root || root.querySelector('.record-skeleton-grid') || (!replace && root.childElementCount)) return;
    const grid = el('div', 'record-grid record-skeleton-grid');
    grid.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 8; i++) {
      const card = el('div', 'record-skeleton');
      for (const part of ['art', 'title', 'artist', 'release']) card.append(el('i', 'skeleton-' + part));
      grid.append(card);
    }
    root.replaceChildren(grid);
  },
  request(path, method = 'GET') {
    const route = path.split('?')[0];
    const jobs = route === '/api/jobs' && method === 'GET';
    // Ignore background polling after the initial visible load.
    if (route.startsWith('/api/health') || route.startsWith('/api/maintenance/') ||
        route === '/api/suggestions' || jobs && (state.page !== 'descargas' || $('jobs').childElementCount) ||
        route === '/api/proposals' && method === 'GET' && state.page !== 'perfil') return;
    const token = {}; this.pending.add(token);
    if (!this.busyTimer && $('ux-progress').hidden) {
      this.busyTimer = setTimeout(() => {
        this.busyTimer = 0;
        if (this.pending.size) $('ux-progress').hidden = false;
      }, 150);
    }
    const results = route === '/api/search' ? $('results') : null;
    if (results && state.page === 'buscar') {
      results.style.display = '';
      this.skeleton(results, true); results.setAttribute('aria-busy', 'true');
      $('welcome').hidden = true;
      this.resultRequest = token;
    }
    return () => {
      this.pending.delete(token);
      if (results && this.resultRequest === token) {
        results.querySelector('.record-skeleton-grid')?.remove();
        results.removeAttribute('aria-busy');
      }
      if (!this.pending.size) {
        clearTimeout(this.busyTimer); this.busyTimer = 0;
        $('ux-progress').hidden = true;
      }
    };
  },
  selectOnHold(button, item) {
    let timer, pointer, x, y, held = false;
    const cancel = () => { clearTimeout(timer); pointer = undefined; };
    button.addEventListener('pointerdown', event => {
      if (!event.isPrimary || event.pointerType === 'mouse' || Selection.items.size) return;
      cancel(); held = false;
      pointer = event.pointerId; x = event.clientX; y = event.clientY;
      timer = setTimeout(() => {
        if (button.isConnected && !Selection.busy) { held = true; Selection.toggle(item); }
      }, 460);
    });
    button.addEventListener('pointermove', e => {
      if (pointer === e.pointerId && Math.hypot(e.clientX - x, e.clientY - y) > 9) cancel();
    });
    for (const type of ['pointerup','pointercancel','pointerleave']) button.addEventListener(type, cancel);
    button.addEventListener('contextmenu', e => { if (pointer !== undefined || held) e.preventDefault(); });
    button.addEventListener('click', e => {
      if (held) { e.preventDefault(); e.stopImmediatePropagation(); held = false; }
    }, true);
  },
  reset() {
    this.pending.clear(); clearTimeout(this.busyTimer); this.busyTimer = 0;
    $('ux-progress').hidden = true;
    $('home-sections').removeAttribute('aria-busy');
    $('results').removeAttribute('aria-busy');
    if ($('music-tour').open) this.closeTour('', false);
    clearTimeout(this.tourTimer);
    this.tourTimer = setTimeout(() => this.maybeTour(), 200);
  },
  key() { return Profile.user?.id ? 'music-ingest:tour:' + Profile.user.id : ''; },
  maybeTour() {
    const key = this.key();
    if (!key || !Profile.library || $('auth-dialog').open || document.hidden || $('music-tour').open) return;
    try { if (localStorage.getItem(key) || sessionStorage.getItem(key)) return; } catch {}
    if (this.seen === key || document.querySelector('dialog[open]')) return;
    this.startTour();
  },
  startTour() {
    if (!Profile.user || !Profile.library || $('music-tour').open) return;
    this.seen = this.key();
    this.tourSteps = tourSteps.filter(step => !step.owner || Profile.owner());
    this.tourIndex = 0; this.returnScroll = { x: scrollX, y: scrollY };
    this.returnFocus = document.activeElement;
    this.spotlight = null; $('music-tour').showModal(); this.drawStep();
    $('tour-next').focus({preventScroll:true});
  },
  drawStep() {
    const step = this.tourSteps[this.tourIndex];
    $('tour-step').textContent = (this.tourIndex+1) + ' de ' + this.tourSteps.length;
    $('tour-title').textContent = step.title; $('tour-copy').textContent = step.copy;
    const last = this.tourIndex === this.tourSteps.length - 1;
    $('tour-next').textContent = last ? 'Terminar' : 'Siguiente';
    $('tour-prev').disabled = !this.tourIndex;
    const demo = $('tour-example'); demo.replaceChildren(); demo.hidden = !step.legend;
    if (step.legend) {
      for (const [icon, text] of [['music','Single'],['album','Álbum'],['stack','Rola de álbum'],['source','Fuente'],['check','En biblioteca']]) {
        const sample=el('span','tour-example-key');
        const symbol=el('i', 'tour-demo-symbol demo-'+icon);
        symbol.append(icon==='source'?sourceMark('youtube','YouTube Music'):actionIcon(icon==='stack'?'music':icon));
        sample.append(symbol,el('span','',text)); demo.append(sample);
      }
    }
    this.spotlight = step.target.split(',').flatMap(selector => Array.from(document.querySelectorAll(selector.trim()))).find(n => n.getClientRects().length && n.offsetWidth && n.offsetHeight);
    if (this.spotlight) this.spotlight.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
    this.positionTour();
  },
  positionTour() {
    if (!$('music-tour').open) return;
    const popup = $('tour-box'),spot = $('tour-outline'),shade=$('tour-shade');
    const w = innerWidth, h = window.visualViewport?.height || innerHeight;
    const bounds = this.spotlight?.getBoundingClientRect();
    const visible = bounds && bounds.bottom>0 && bounds.top<h && bounds.width>0;
    spot.hidden = !visible;
    shade.style.clipPath='none';
    if (visible) {
      const left=Math.max(4,bounds.left-4), top=Math.max(4,bounds.top-4);
      const right=Math.min(w-4,bounds.right+4),bottom=Math.min(h-4,bounds.bottom+4);
      Object.assign(spot.style,{left:left+'px',top:top+'px',
        width:(right-left)+'px',height:(bottom-top)+'px'});
      shade.style.clipPath='polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, 0 0, '+left+'px '+top+'px, '+right+'px '+top+'px, '+right+'px '+bottom+'px, '+left+'px '+bottom+'px, '+left+'px '+top+'px)';
    }
    const pw=popup.offsetWidth, ph=popup.offsetHeight, gap=14;
    let left=(w-pw)/2, top=(h-ph)/2;
    if (visible) {
      if (w>740 && bounds.right+gap+pw<=w-10) { left=bounds.right+gap; top=bounds.top; }
      else if (bounds.bottom+gap+ph<=h-10) { left=bounds.left; top=bounds.bottom+gap; }
      else if (bounds.top-gap-ph>=10) { left=bounds.left; top=bounds.top-gap-ph; }
      else { left=w>740?bounds.left:10; top=bounds.top<h/2?h-ph-10:10; }
    }
    popup.style.left=Math.max(10,Math.min(left,w-pw-10))+'px';
    popup.style.top=Math.max(10,Math.min(top,h-ph-10))+'px';
  },
  closeTour(choice, restore=true) {
    const key=this.key();
    if (key && choice) {
      try { (choice==='later'?sessionStorage:localStorage).setItem(key,choice); } catch {}
    }
    this.spotlight=null; $('music-tour').close();
    if (restore && this.returnScroll) {
      window.scrollTo({left:this.returnScroll.x,top:this.returnScroll.y,behavior:'instant'});
      if(this.returnFocus?.isConnected)this.returnFocus.focus({preventScroll:true});
    }
  },
};
window.RecordUX=RecordUX;

const tourSteps=[
  {target:'#query',title:'Empezá con una rola',copy:'Escribí un nombre o pegá un enlace de canción, artista, álbum o playlist. En los resultados, el nombre del artista abre su ficha y el nombre del álbum abre sus pistas.'},
  {target:'#listen-mode',title:'Elegí qué hace una portada',copy:'En Stream, un toque reproduce la rola. En Descargar, abre sus datos y podés ajustar la portada antes de guardarla.'},
  {target:'.page:not([hidden]) .record-picture, #page-inicio:not([hidden]) .section-head, #query',title:'Leé los iconos de la portada',copy:'La esquina de abajo te dice qué estás viendo. La de arriba a la derecha identifica la plataforma. Pasá el mouse sobre un icono para leer su nombre.',legend:true},
  {target:'.page:not([hidden]) .record-picture, #page-inicio:not([hidden]) .section-head, #query',title:'Seleccioná varias a la vez',copy:'Acercá el mouse a la esquina superior izquierda y marcá la primera casilla. En el celular, mantené presionada una portada. Después, cada toque suma o quita una rola de la selección.'},
  {target:'#music-player:not([hidden]), #listen-mode',title:'Seguí escuchando mientras navegás',copy:'El reproductor te deja pausar, adelantar y ver la cola. Con clic derecho en una rola, elegí Reproducir a continuación. Arrastrá las filas de la cola para ordenarlas. Auto DJ elige las próximas y Seguir decide si avanzar al terminar.'},
  {target:'[data-page="descargas"]',title:'Elegí cómo descargar',copy:'Descargar muestra el avance en el momento. Mandar a cola te deja seguir explorando y te avisa cuando termina. En Descargas podés revisar y reintentar los intentos fallidos.'},
  {target:'[data-page="playlists"], [data-page="biblioteca"]',title:'Guardá música para volver',copy:'Tocá el corazón para guardar una favorita o usá Agregar a playlist en el reproductor. En Playlists y en Biblioteca, abrí Favoritas y playlists para escucharlas.'},
  {target:'[data-page="favoritos"]',title:'Seguí a tus artistas',copy:'Abrí la ficha de un artista para mantener su música al día. En Artistas podés revisar a quién seguís y ajustar las revisiones.',owner:true},
  {target:'#add-source, [data-page="inicio"]',title:'Elegí tus fuentes',copy:'En Inicio, Agregar fuente conecta otra plataforma. Los tres puntos de cada fuente reúnen los formatos de audio, las sugerencias y la ayuda para importar tu página o tus cookies.',owner:true},
  {target:'#rotation-card, [data-page="perfil"]',title:'Renová tu biblioteca',copy:'En Ajustes, Rotación de música puede descargar hasta 20 rolas por vuelta. Elegí el intervalo y conectá Navidrome si querés conservar las favoritas y renovar el resto de la tanda.',owner:true},
  {target:'.brand-icon',title:'Dale impulso al logo',copy:'Tocalo para ir a Inicio. Estando ahí, arrastralo en cualquier dirección y soltalo para hacerlo girar.'},
  {target:'[data-page="perfil"]',title:'Volvé cuando lo necesités',copy:'En Ajustes encontrás tu cuenta y el botón Ver recorrido. Podés volver a abrir esta guía desde ahí.'},
];

const progress=el('div','ux-progress');progress.id='ux-progress';progress.hidden=true;
progress.setAttribute('role','status');progress.setAttribute('aria-live','polite');
progress.append(el('i','ux-spinner'),el('span','','Cargando…'));document.body.append(progress);

const tour=el('dialog','music-tour');tour.id='music-tour';tour.setAttribute('aria-labelledby','tour-title');
tour.setAttribute('aria-describedby','tour-copy');
const spot=el('div','tour-outline');spot.id='tour-outline';spot.setAttribute('aria-hidden','true');
const popup=el('section','tour-box');popup.id='tour-box';
const tourHead=el('div','tour-head'),step=el('small');step.id='tour-step';
const later=el('button','text-action','Ahora no');later.type='button';later.onclick=()=>RecordUX.closeTour('later');
tourHead.append(step,later);
const tourTitle=el('h2');tourTitle.id='tour-title';const tourCopy=el('p');tourCopy.id='tour-copy';
const sample=el('div','tour-example');sample.id='tour-example';
const foot=el('div','tour-foot');
const never=el('button','text-action','No volver a mostrar');never.type='button';never.onclick=()=>RecordUX.closeTour('dismissed');
const prev=el('button','quiet','Atrás');prev.id='tour-prev';prev.type='button';prev.onclick=()=>{if(RecordUX.tourIndex>0){RecordUX.tourIndex--;RecordUX.drawStep();}};
const next=el('button','primary','Siguiente');next.id='tour-next';next.type='button';
next.onclick=()=>{if(RecordUX.tourIndex===RecordUX.tourSteps.length-1)RecordUX.closeTour('done');else{RecordUX.tourIndex++;RecordUX.drawStep();}};
foot.append(never,prev,next);popup.append(tourHead,tourTitle,tourCopy,sample,foot);const shade=el('div','tour-shade');shade.id='tour-shade';shade.setAttribute('aria-hidden','true');tour.append(shade,spot,popup);document.body.append(tour);
tour.addEventListener('cancel',e=>{e.preventDefault();RecordUX.closeTour('later');});
window.addEventListener('resize',()=>RecordUX.positionTour());
window.addEventListener('scroll',()=>RecordUX.positionTour(),{passive:true});
window.visualViewport?.addEventListener('resize',()=>RecordUX.positionTour());
$('auth-dialog').addEventListener('close',()=>RecordUX.maybeTour());
document.addEventListener('visibilitychange',()=>{if(!document.hidden)RecordUX.maybeTour();});
const replay=el('button','quiet tour-replay','Ver recorrido');replay.type='button';replay.id='show-tour';
replay.onclick=()=>RecordUX.startTour();$('profile-intro').after(replay);
if (window.Profile?.user) RecordUX.reset();
