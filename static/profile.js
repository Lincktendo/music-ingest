'use strict';

// Account state stays in memory; only the selected library id is remembered.
const Profile = {
  user:null, libraries:[], library:null, revision:0, mode:'login', loading:false, proposalsKey:null,
  owner(){return this.library?.role==='owner';},
  scope(path){
    if(!this.library || !path.startsWith('/api/') || /^\/api\/(auth|health|libraries)(?:\/|\?|$)/.test(path))return path;
    const url=new URL(path,location.origin);
    if(!url.searchParams.has('library'))url.searchParams.set('library',this.library.id);
    return url.pathname+url.search;
  },
  forgetKey(){ $('key-value').value=''; $('new-key').hidden=true; },
  reset(){
    this.revision++; window.MediaUI?.reset(); window.Selection?.reset(); window.Navigation?.refresh(); window.AutomationUI?.reset(); this.proposalsKey=null; this.forgetKey(); closeSuggestions(); state.search++; state.previewRequest++;
    window.Artists?.close(); $('search-submit').disabled=false;
    state.jobsKey=''; state.libraryKey=''; state.preview=null; state.selected.clear();
    $('preview-dialog').close(); $('queue-count').hidden=true;
    for(const id of ['jobs','library','members','keys','proposals','providers'])$(id).replaceChildren();
    for(const id of ['profile-status','jobs-status','library-status','preview-status'])status(id,'');
    $('owner-settings').hidden=true; $('enqueue').textContent=this.owner()?'Guardar en mi biblioteca':'Proponer a esta biblioteca';
  },
  requireLogin(message=''){
    this.user=null;this.library=null;this.libraries=[];this.reset();
    $('library-switch').hidden=true; $('profile-name').textContent=''; $('profile-username').textContent='';
    if(!$('auth-dialog').open)$('auth-dialog').showModal();
    if(message)status('auth-status',message,true);
  },
  async init(){
    try{this.accept(await api('/api/auth/me'));}
    catch(err){this.requireLogin();try{const result=await api('/api/auth/status');if(!result.has_users)this.setMode('register');}catch{status('auth-status','No pudimos conectar con el servidor. Podés intentar entrar de nuevo.',true);}}
  },
  accept(data){
    this.user=data.user;this.libraries=Array.isArray(data.libraries)?data.libraries:[];
    let remembered='';try{remembered=sessionStorage.getItem('mi-library-'+this.user.id)||'';}catch{}
    this.library=this.libraries.find(x=>x.id===remembered)||this.libraries.find(x=>x.id===data.default_library)||this.libraries[0]||null;
    this.reset();this.renderAccount();$('auth-password').value='';status('auth-status','');$('auth-dialog').close();
    navigate(state.page||'buscar',false);loadJobs();
  },
  setMode(mode){
    this.mode=mode;const register=mode==='register';
    $('mode-login').classList.toggle('active',!register);$('mode-register').classList.toggle('active',register);
    $('mode-login').setAttribute('aria-pressed',String(!register));$('mode-register').setAttribute('aria-pressed',String(register));
    $('display-name-field').hidden=!register;$('password-help').hidden=!register;
    $('auth-password').autocomplete=register?'new-password':'current-password';
    $('auth-submit').textContent=register?'Crear mi biblioteca':'Entrar';
    $('auth-title').textContent=register?'Vos y tu música, maje.':'Tu música empieza acá.';
    $('auth-subtitle').textContent=register?'Creá tu cuenta. Tu biblioteca será tuya, y vos elegís con quién compartirla.':'Entrá a tu cuenta para abrir tu biblioteca.';
    status('auth-status','');
  },
  renderAccount(){
    if(!this.user)return; window.Navigation?.refresh();
    $('profile-name').textContent=this.user.display_name||this.user.username;
    $('profile-username').textContent='@'+this.user.username;
    $('profile-avatar').textContent=(this.user.display_name||this.user.username).slice(0,1).toLocaleUpperCase();
    $('active-library').replaceChildren();
    for(const library of this.libraries){const option=el('option','',library.role==='owner'?'Mi biblioteca':library.name);option.value=library.id;option.selected=library.id===this.library?.id;$('active-library').append(option);}
    $('library-switch').hidden=!this.library;$('active-role').textContent=this.owner()?'PROPIETARIO':'COLABORADOR';
    $('profile-intro').textContent=this.owner()?'Tu biblioteca, tus colaboradores y las herramientas que conectás.':'Estás colaborando en '+(this.library?.name||'una biblioteca')+'. Proponé música y seguí su estado acá.';
    $('proposal-description').textContent=this.owner()?'Revisá las selecciones que te proponen tus colaboradores y tus IA.':'Las propuestas que enviaste a esta biblioteca, con su estado actualizado.';
    $('owner-settings').hidden=!this.owner();$('auto-approve').checked=!!this.library?.auto_approve;
    $('enqueue').textContent=this.owner()?'Guardar en mi biblioteca':'Proponer a esta biblioteca';
    $('agent-guide').textContent='Music Ingest está en '+location.origin+'\n\nUsá la clave que te proporcioné como Authorization: Bearer <CLAVE>.\n1. Buscá con GET /api/search?q=...&kind=songs (también albums o artists).\n2. Revisá con POST /api/preview y JSON {"id":"ID","type":"song"} o {"url":"ENLACE"}.\n3. Elegí pistas verificadas y proponelas con POST /api/proposals y JSON {"tracks":[{"id":"ID_PISTA"}],"format":"mp3"}.\n4. Consultá GET /api/proposals para ver su estado.\n\nNo descargues directamente ni intentes cambiar configuraciones. Las propuestas necesitan aprobación salvo que yo haya activado la aprobación automática. La clave solo funciona con mi biblioteca.';
  },
  async show(){
    if(!this.user)return;this.renderAccount();const rev=this.revision;status('profile-status','');
    const actions=[this.loadProposals()];if(this.owner())actions.push(this.loadMembers(),this.loadKeys(),this.loadProviders(),window.AutomationUI?.load());
    const results=await Promise.allSettled(actions);
    if(rev!==this.revision)return;
    const failed=results.find(x=>x.status==='rejected');if(failed)status('profile-status',failed.reason.message,true);
  },
  async loadMembers(){
    const rev=this.revision,id=this.library?.id;if(!this.owner())return;
    const data=await api('/api/libraries/'+encodeURIComponent(id)+'/members');if(rev!==this.revision)return;
    $('members').replaceChildren();
    for(const member of data.items||[]){
      const row=el('div','member-row'),info=el('div','row-info');info.append(el('strong','',member.display_name||member.username),el('small','','@'+member.username));row.append(info);
      if(member.role==='owner')row.append(el('span','status-tag','Propietario'));
      else{const button=el('button','quiet danger-link','Quitar');button.type='button';button.setAttribute('aria-label','Quitar a '+member.username);button.addEventListener('click',async()=>{button.disabled=true;try{await api('/api/libraries/'+encodeURIComponent(id)+'/members/'+encodeURIComponent(member.id),{method:'DELETE',body:'{}'});if(rev!==this.revision)return;await this.loadMembers();toast('Colaborador eliminado.');}catch(err){if(rev===this.revision){status('profile-status',err.message,true);button.disabled=false;}}});row.append(button);}
      $('members').append(row);
    }
  },
  async loadProposals(){
    if(!this.user||!this.library)return;const rev=this.revision;const data=await api('/api/proposals');if(rev!==this.revision)return;
    const key=JSON.stringify(data.items||[]);if(key===this.proposalsKey)return;this.proposalsKey=key;
    const container=$('proposals');container.replaceChildren();const items=data.items||[];
    if(!items.length){container.append(el('p','section-copy',this.owner()?'Todavía no hay propuestas para revisar.':'Buscá música y tocá «Proponer» para enviar tu primera selección.'));return;}
    for(const item of items){
      const row=el('article','proposal-row'),head=el('div','job-head'),info=el('div','row-info');
      info.append(el('h3','',item.title||'Selección de música'),el('small','',[item.actor_name,(item.tracks?.length||0)+' pistas',item.format==='original'?'Original':'MP3'].filter(Boolean).join(' · ')));
      const label={pending:'Por revisar',approved:'Aprobada',rejected:'Rechazada'}[item.status]||item.status;
      head.append(info,el('span','status-tag'+(item.status==='rejected'?' bad':''),label));row.append(head);
      const list=el('details','proposal-details');list.append(el('summary','','Ver selección'));
      const tracks=el('ul');for(const track of item.tracks||[])tracks.append(el('li','',[track.title,track.artist].filter(Boolean).join(' · ')));list.append(tracks);row.append(list);
      if(item.job_status)row.append(el('p','section-copy','Descarga: '+(statusLabels[item.job_status]||'Procesando')+(item.job_status==='running'?' · '+Math.round(Number(item.progress)||0)+'%':'')));
      if(item.error)row.append(el('p','job-error','La descarga no se pudo completar. Revisá el detalle en Descargas.'));
      if(this.owner()&&item.status==='pending'){
        const actions=el('div','row-actions');
        for(const [action,text,cls] of [['approve','Aprobar y guardar','primary'],['reject','Rechazar','quiet']]){
          const button=el('button',cls,text);button.type='button';button.addEventListener('click',async()=>{for(const child of actions.children)child.disabled=true;try{await post('/api/proposals/'+encodeURIComponent(item.id)+'/'+action);if(rev!==this.revision)return;await this.loadProposals();loadJobs();toast(action==='approve'?'Propuesta aprobada. Ya está en la cola.':'Propuesta rechazada.');}catch(err){if(rev===this.revision){status('profile-status',err.message,true);for(const child of actions.children)child.disabled=false;}}});actions.append(button);
        }row.append(actions);
      }container.append(row);
    }
  },
  async loadKeys(){
    if(!this.owner())return;const rev=this.revision,id=this.library.id;const data=await api('/api/libraries/'+encodeURIComponent(id)+'/keys');if(rev!==this.revision)return;$('keys').replaceChildren();
    const active=(data.items||[]).filter(x=>!x.revoked_at);
    if(!active.length)$('keys').append(el('p','section-copy','Todavía no conectaste ninguna IA.'));
    for(const key of active){const row=el('div','member-row'),info=el('div','row-info');info.append(el('strong','',key.name),el('small','',(key.prefix||'Clave')+'… · '+(key.last_used_at?'Ya utilizada':'Sin usar')));const revoke=el('button','quiet danger-link','Revocar');revoke.type='button';revoke.addEventListener('click',async()=>{revoke.disabled=true;try{await api('/api/libraries/'+encodeURIComponent(id)+'/keys/'+encodeURIComponent(key.id),{method:'DELETE',body:'{}'});if(rev!==this.revision)return;this.forgetKey();await this.loadKeys();toast('Acceso revocado.');}catch(err){if(rev===this.revision){status('profile-status',err.message,true);revoke.disabled=false;}}});row.append(info,revoke);$('keys').append(row);}
  },
  async loadProviders(){
    if(!this.owner())return;const rev=this.revision;const data=await api('/api/integrations');if(rev!==this.revision)return;$('providers').replaceChildren();
    for(const provider of data.providers||[]){
      const details=el('details','provider'),summary=el('summary'),intro=el('div','row-info');intro.append(el('strong','',provider.name),el('small','',provider.description||''));summary.append(intro,el('span','status-tag',provider.enabled?(provider.requires_key&&!provider.configured?'Falta clave':'Activo'):'Desactivado'));details.append(summary);
      const form=el('form','provider-form'),label=el('label','toggle-line'),enabled=document.createElement('input');enabled.type='checkbox';enabled.checked=!!provider.enabled;enabled.setAttribute('role','switch');enabled.disabled=provider.available===false;label.append(el('span','','Usar '+provider.name),enabled);form.append(label);
      const keyInputs=[];
      for(const field of provider.fields||[]){const wrapper=el('label','field-label',field.label||'Clave de API'),input=document.createElement('input');input.type='password';input.autocomplete='new-password';input.maxLength=512;input.placeholder=provider.configured?'Clave guardada · Dejá vacío para conservarla':'Ingresá una clave si querés conectar tu cuenta';wrapper.append(input);form.append(wrapper);keyInputs.push({input,name:field.name||'api_key'});}
      let remove=null;if(provider.configured&&keyInputs.length){const row=el('label','check-line');remove=document.createElement('input');remove.type='checkbox';row.append(remove,document.createTextNode('Eliminar la clave guardada'));form.append(row);}
      if(provider.steps?.length){const steps=el('ol','provider-steps');for(const step of provider.steps)steps.append(el('li','',step));form.append(steps);}
      const links=el('div','provider-links');for(const link of provider.links||[]){try{const url=new URL(link.url);if(url.protocol!=='https:')continue;const anchor=el('a','',link.label||'Guía oficial');anchor.href=url.href;anchor.target='_blank';anchor.rel='noopener noreferrer';links.append(anchor);}catch{}}form.append(links);
      const feedback=el('p','inline-status');feedback.setAttribute('role','status');const save=el('button','quiet','Guardar ajustes');save.type='submit';save.disabled=provider.available===false;form.append(feedback,save);
      form.addEventListener('submit',async(event)=>{event.preventDefault();save.disabled=true;feedback.textContent='Guardando…';feedback.classList.remove('error');const settings={enabled:enabled.checked};for(const field of keyInputs){if(remove?.checked)settings[field.name]='';else if(field.input.value.trim())settings[field.name]=field.input.value.trim();}try{await api('/api/integrations',{method:'PATCH',body:JSON.stringify({providers:{[provider.id]:settings}})});for(const field of keyInputs)field.input.value='';if(rev!==this.revision)return;await this.loadProviders();toast('Ajustes guardados.');}catch(err){if(rev===this.revision){feedback.textContent=err.message;feedback.classList.add('error');save.disabled=false;}}});details.append(form);$('providers').append(details);
    }
  }
};
window.Profile=Profile;

async function copyText(text,field){
  try{if(!navigator.clipboard?.writeText)throw Error();await navigator.clipboard.writeText(text);toast('Copiado.');}
  catch{if(field){field.focus();field.select();toast('Texto seleccionado. Usá copiar en tu navegador.');}else{const range=document.createRange();range.selectNodeContents($('agent-guide'));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);toast('Instrucciones seleccionadas. Usá copiar en tu navegador.');}}
}
$('auth-dialog').addEventListener('cancel',event=>event.preventDefault());
$('mode-login').addEventListener('click',()=>Profile.setMode('login'));
$('mode-register').addEventListener('click',()=>Profile.setMode('register'));
$('auth-form').addEventListener('submit',async event=>{
  event.preventDefault();if(Profile.loading)return;Profile.loading=true;$('auth-submit').disabled=true;status('auth-status','');
  const body={username:$('auth-username').value.trim().toLowerCase(),password:$('auth-password').value};if(Profile.mode==='register')body.display_name=$('auth-displayname').value.trim();
  try{Profile.accept(await post('/api/auth/'+(Profile.mode==='register'?'register':'login'),body));}
  catch(err){status('auth-status',err.message,true);}finally{Profile.loading=false;$('auth-submit').disabled=false;}
});
$('logout').addEventListener('click',async()=>{const button=$('logout');button.disabled=true;try{await post('/api/auth/logout');Profile.requireLogin();}catch(err){status('profile-status',err.message,true);}finally{button.disabled=false;}});
$('active-library').addEventListener('change',()=>{
  const library=Profile.libraries.find(x=>x.id===$('active-library').value);if(!library)return;Profile.library=library;try{sessionStorage.setItem('mi-library-'+Profile.user.id,library.id);}catch{}
  Profile.reset();Profile.renderAccount();navigate(state.page,false);loadJobs();
});
$('member-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!Profile.owner())return;const rev=Profile.revision,button=event.submitter;button.disabled=true;status('profile-status','');
  try{await post('/api/libraries/'+encodeURIComponent(Profile.library.id)+'/members',{username:$('member-username').value.trim().toLowerCase()});if(rev!==Profile.revision)return;$('member-username').value='';await Profile.loadMembers();toast('Colaborador agregado.');}catch(err){if(rev===Profile.revision)status('profile-status',err.message,true);}finally{button.disabled=false;}
});
$('auto-approve').addEventListener('change',async()=>{
  if(!Profile.owner())return;const rev=Profile.revision,input=$('auto-approve'),value=input.checked;input.disabled=true;
  try{await api('/api/libraries/'+encodeURIComponent(Profile.library.id),{method:'PATCH',body:JSON.stringify({auto_approve:value})});if(rev!==Profile.revision)return;Profile.library.auto_approve=value;toast(value?'Las propuestas nuevas se aprobarán automáticamente.':'Las propuestas nuevas necesitarán tu aprobación.');}catch(err){if(rev===Profile.revision){input.checked=!value;status('profile-status',err.message,true);}}finally{input.disabled=false;}
});
$('key-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!Profile.owner())return;const rev=Profile.revision,button=event.submitter;button.disabled=true;Profile.forgetKey();
  try{const result=await post('/api/libraries/'+encodeURIComponent(Profile.library.id)+'/keys',{name:$('key-label').value.trim()});if(rev!==Profile.revision)return;$('key-label').value='';$('key-value').value=result.token;$('new-key').hidden=false;await Profile.loadKeys();$('key-value').focus();}
  catch(err){if(rev===Profile.revision)status('profile-status',err.message,true);}finally{button.disabled=false;}
});
$('copy-key').addEventListener('click',()=>copyText($('key-value').value,$('key-value')));
$('hide-key').addEventListener('click',()=>Profile.forgetKey());
$('copy-guide').addEventListener('click',()=>copyText($('agent-guide').textContent));
$('refresh-proposals').addEventListener('click',async()=>{const button=$('refresh-proposals');button.disabled=true;try{await Profile.loadProposals();}catch(err){status('profile-status',err.message,true);}finally{button.disabled=false;}});
document.addEventListener('DOMContentLoaded',()=>Profile.init());
