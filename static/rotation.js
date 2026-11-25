'use strict';
const RotationUI={
  revision:0, loading:false, data:null,
  reset(){this.revision++;this.loading=false;this.data=null;$('rotation-password').value='';$('rotation-form').reset();status('rotation-status','');},
  mount(){
    const section=el('section','profile-card rotation-card');section.id='rotation-card';
    section.innerHTML='<h2>Rotación de música</h2><p class="section-copy">Sumá hasta 20 rolas aleatorias por vuelta, según tus fuentes y lo que escuchás.</p><form id="rotation-form"><label class="toggle-line"><span><strong>Alimentar mi biblioteca</strong><small>Descarga una tanda en el intervalo que elijás.</small></span><input id="rotation-enabled" type="checkbox" role="switch"></label><div class="rotation-interval"><label>Cada<input id="rotation-every" type="number" min="1" max="43200" value="1" required></label><label><span class="sr-only">Unidad de tiempo</span><select id="rotation-unit"><option value="60">minutos</option><option value="3600">horas</option><option value="86400" selected>días</option></select></label></div><label class="toggle-line"><span><strong>Renovar la tanda anterior</strong><small>Conservá las rolas con corazón en Navidrome. Se retiran las demás rolas de la tanda automática anterior.</small></span><input id="rotation-cleanup" type="checkbox" role="switch"></label><details id="rotation-connection"><summary>Conectar con Navidrome</summary><p class="section-copy">Usá la cuenta donde marcás tus favoritas.</p><label>Dirección de Navidrome<input id="rotation-url" type="url" placeholder="http://navidrome:4533" autocomplete="off"></label><label>Usuario<input id="rotation-user" autocomplete="off"></label><label>Contraseña<input id="rotation-password" type="password" autocomplete="new-password" placeholder="Tu contraseña de Navidrome"></label><small id="rotation-credential"></small><details class="help-details"><summary>Ya tengo Navidrome · ¿Qué dirección pongo?</summary><p>Si ambos vienen en el proyecto conjunto, usá http://navidrome:4533. Si Navidrome está en esta computadora y Music Ingest en Docker, probá http://host.docker.internal:4533. Para otra computadora, usá su dirección de red y puerto.</p><p>Ambos necesitan ver la misma carpeta de música. El proyecto conjunto ya la comparte.</p><label>Carpeta de esta biblioteca dentro de Navidrome<input id="rotation-prefix" autocomplete="off" placeholder="Se completa según tu biblioteca"></label><p>Subcarpeta sugerida. Navidrome también se reconoce por los datos y el contenido del archivo.</p></details><button id="rotation-test" type="button" class="quiet">Guardar conexión y probar</button></details><div class="row-actions"><button id="rotation-save" type="submit" class="primary">Guardar ajustes</button><button id="rotation-run" type="button" class="quiet" disabled>Traer una tanda ahora</button></div></form><p id="rotation-summary" class="section-copy"></p><p id="rotation-status" class="inline-status" role="status"></p>';
    $('owner-settings').prepend(section);
    const shortcut=el('button','quiet','Rotación y Navidrome');shortcut.type='button';shortcut.dataset.ownerAction='';shortcut.hidden=!Profile.owner();shortcut.onclick=async()=>{await navigate('perfil');section.scrollIntoView({block:'start'});};document.querySelector('.profile-shortcuts').append(shortcut);
    $('rotation-form').onsubmit=e=>{e.preventDefault();this.save(false);};
    $('rotation-test').onclick=()=>this.save(true);
    $('rotation-cleanup').onchange=()=>{if($('rotation-cleanup').checked)$('rotation-connection').open=true;};
    $('rotation-run').onclick=()=>this.run();
  },
  connection(){
    const result={navidrome_url:$('rotation-url').value.trim(),username:$('rotation-user').value.trim(),path_prefix:$('rotation-prefix').value.trim()};
    if($('rotation-password').value)result.password=$('rotation-password').value;
    return result;
  },
  paint(data,fill=true){
    this.data=data;
    if(fill){
      $('rotation-enabled').checked=!!data.enabled;$('rotation-cleanup').checked=!!data.cleanup;
      const seconds=data.interval_seconds||86400;
      const unit=seconds%86400===0?86400:seconds%3600===0?3600:60;
      $('rotation-unit').value=String(unit);$('rotation-every').value=seconds/unit;
      $('rotation-url').value=data.navidrome_url||'';$('rotation-user').value=data.username||'';
      $('rotation-prefix').value=data.path_prefix||'';$('rotation-password').value='';
    }
    $('rotation-credential').textContent=data.credential_set?'Contraseña guardada. Completá el campo para reemplazarla.':'';
    $('rotation-run').disabled=!data.enabled;
    const next=data.next_run?new Date(data.next_run*1000).toLocaleString('es'):'por programar';
    $('rotation-summary').textContent=(data.enabled?'Próxima tanda · '+next:'Rotación pausada')+
      (data.last_run?' · Última tanda · '+(data.latest_count||0)+' rolas':'')+
      (data.owned_count?' · '+data.owned_count+' rolas en rotación':'');
    if(data.error)status('rotation-status',data.error,true);
  },
  async load(){
    if(!Profile.owner()||this.loading)return;
    this.loading=true;for(const control of $('rotation-form').querySelectorAll('input,select,button'))control.disabled=true;const revision=Profile.revision,request=this.revision;
    try{const data=await api('/api/rotation');if(revision===Profile.revision&&request===this.revision)this.paint(data);}
    catch(e){if(revision===Profile.revision)status('rotation-status',e.message,true);}
    finally{if(request===this.revision){this.loading=false;for(const control of $('rotation-form').querySelectorAll('input,select,button'))control.disabled=!this.data;$('rotation-run').disabled=!this.data?.enabled;}}
  },
  async save(test){
    const revision=Profile.revision;
    const body=this.connection();
    if(!test)Object.assign(body,{enabled:$('rotation-enabled').checked,cleanup:$('rotation-cleanup').checked,
      interval_seconds:Number($('rotation-every').value)*Number($('rotation-unit').value)});
    if(!test&&body.interval_seconds>2592000){status('rotation-status','Elegí un intervalo de hasta 30 días.',true);return;}
    for(const id of ['rotation-save','rotation-test','rotation-run'])$(id).disabled=true;
    status('rotation-status',test?'Comprobando la conexión…':'Guardando…');
    try{
      const data=await api('/api/rotation',{method:'PATCH',body:JSON.stringify(body)});
      if(revision!==Profile.revision)return;
      if(test)await post('/api/rotation/test');
      if(revision!==Profile.revision)return;
      this.paint(data,!test);$('rotation-password').value='';
      status('rotation-status',test?'Conexión lista. Music Ingest puede consultar tus favoritas.':'Ajustes guardados.');
    }catch(e){if(revision===Profile.revision)status('rotation-status',e.message,true);}
    finally{if(revision===Profile.revision){$('rotation-save').disabled=false;$('rotation-test').disabled=false;$('rotation-run').disabled=!this.data?.enabled;}}
  },
  async run(){
    const revision=Profile.revision;$('rotation-run').disabled=true;
    try{await post('/api/rotation/run');if(revision!==Profile.revision)return;status('rotation-status','Tanda solicitada. Vas a ver el progreso en Descargas.');await this.load();}
    catch(e){if(revision===Profile.revision)status('rotation-status',e.message,true);}
    finally{if(revision===Profile.revision)$('rotation-run').disabled=!this.data?.enabled;}
  }
};
window.RotationUI=RotationUI;
RotationUI.mount();
