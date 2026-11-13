'use strict';
const Navigation={
 refresh(){
  const owner=!!window.Profile?.owner();
  document.querySelectorAll('[data-owner-action]').forEach(node=>node.hidden=!owner);
  $('collaborator-start').hidden=!Profile.user||owner;
  const card=document.querySelector('[data-go="songs"] strong');
  card.textContent='Buscar música';document.body.classList.toggle('library-owner',owner);
 },
 async go(action){
  if(!Profile.user)return;
  if(['playlist','schedule','favorites'].includes(action)){if(!Profile.owner())return;const revision=Profile.revision;const page=action==='favorites'?'favoritos':'playlists';await navigate(page);if(revision!==Profile.revision||state.page!==page)return;const target=$(action==='schedule'?'schedule-card':action==='favorites'?'page-favoritos':'playlist-url');target.tabIndex=target.tabIndex<0?-1:target.tabIndex;target.focus({preventScroll:true});target.scrollIntoView({block:'start',behavior:'smooth'});return;}
  const targets={playlist:['following-card','playlist-url'],folder:['folder-card','folder-select'],people:['people-card','member-username'],ai:['ai-card','key-label'],providers:['providers-card',null],proposals:['proposals-card',null]};
  if(action==='songs'||action==='artists'){
   navigate('buscar');Artists.close();
   document.querySelector('input[name="kind"][value="'+(action==='artists'?'artists':'songs')+'"]').checked=true;
   $('query').placeholder=action==='artists'?'Buscá tu artista favorito…':'Una canción, un artista o un enlace…';
   $('query').focus({preventScroll:true});$('search-form').scrollIntoView({block:'start',behavior:'smooth'});
   if(action==='artists')toast('Buscá un artista, abrí su ficha y tocá «Mantener su música al día».');
   return;
  }
  const target=targets[action];if(!target||(action!=='proposals'&&!Profile.owner()))return;
  const revision=Profile.revision;await navigate('perfil');if(revision!==Profile.revision||state.page!=='perfil')return;
  const section=$(target[0]);section.tabIndex=-1;
  (target[1]?$(target[1]):section).focus({preventScroll:true});
  section.scrollIntoView({block:'start',behavior:'smooth'});
 }
};
window.Navigation=Navigation;
document.querySelectorAll('[data-go]').forEach(button=>button.addEventListener('click',()=>Navigation.go(button.dataset.go)));
Navigation.refresh();
