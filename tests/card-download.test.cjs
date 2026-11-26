const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function node(tag='div',cls='',text){
  const classes=new Set(cls.split(' ').filter(Boolean));
  const n={tag,className:cls,children:[],style:{},dataset:{},attrs:{},events:{},isConnected:true,offsetWidth:260,offsetHeight:320,
    textContent:text===undefined?'':String(text),classList:{add:s=>classes.add(s),toggle:(s,v)=>v?classes.add(s):classes.delete(s),contains:s=>classes.has(s)},
    append(...xs){this.children.push(...xs);xs.forEach(x=>{if(x&&typeof x==='object')x.parentElement=this;});},
    prepend(...xs){this.children.unshift(...xs);},replaceChildren(...xs){this.children=[];this.append(...xs);},
    setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k];},removeAttribute(k){delete this.attrs[k];},
    addEventListener(k,f){this.events[k]=f;},remove(){this.isConnected=false;},
    focus(){this.focused=true;},closest(){return null;},getBoundingClientRect(){return {top:10,left:10,bottom:41,right:41};},
    showPopover(){this.popoverOpened=true;},hidePopover(){this.popoverOpened=false;},
    querySelector(){return this.children.find(x=>x.tag==='button')||null;},querySelectorAll(){return []}}
  return n;
}
function setup(){
  const ids=new Map(),calls=[],messages=[],body=node('body');
  const media={playing:{id:'current',title:'Current audio'}};
  const env={window:{},Profile:{revision:1,user:{id:'u'},library:{id:'l'},owner:()=>true},MediaUI:media,state:{},
    document:{body,addEventListener(){},querySelectorAll:()=>[]},innerWidth:900,innerHeight:700,
    localStorage:{setItem(){},getItem(){return null;}},clearInterval(){},setInterval(){},setTimeout(){},
    el:node,$:id=>{if(!ids.has(id))ids.set(id,node());return ids.get(id);},
    actionIcon:name=>node('svg',name),cover:()=>node('div','cover'),toast:text=>messages.push(text),
    loadJobs:async()=>calls.push('loadJobs'),SourceUI:{label:f=>f},CSS:{escape:s=>s},
    RecordCards:{resolve:async item=>({tracks:[item]}),enqueue:async tracks=>{calls.push(tracks);return {kind:'job',id:'job'+calls.length};},
      button:(cls,label,fn)=>{const b=node('button',cls,label);b.onclick=fn;return b;}},
    ListeningCollection:{likes:new Set(),key:t=>t.id,icon:name=>node('svg',name)},
    Selection:{items:new Map(),toggle:item=>calls.push(['select',item.id])},
    Player:{stream(){throw Error('Background downloads must never start audio');}}
  };
  env.window=Object.assign(env.window,{addEventListener(){},MediaUI:media});vm.createContext(env);
  const src=fs.readFileSync(path.join(__dirname,'..','static','downloads.js'),'utf8').split('window.DownloadUI=DownloadUI;')[0];
  vm.runInContext(src+';globalThis.ui=DownloadUI;',env);
  const ui=env.ui;ui.playerState=()=>{};ui.openQuick=task=>calls.push(['details',task]);ui.drawQuick=()=>{};
  env.DownloadUI=ui;return {env,ui,calls,messages,media,ids};
}
test('quick download queues once, a second click opens progress and playback stays untouched',async()=>{
  const {env,ui,calls,media}=setup();let finish;
  env.RecordCards.resolve=()=>new Promise(resolve=>{finish=resolve;});
  const item={id:'fixture_A01',title:'Fixture'},playing=media.playing;
  const first=ui.quickQueue(item),second=ui.quickQueue({...item});
  assert.equal(calls.length,1);assert.equal(calls[0][0],'details');
  finish({tracks:[item]});await Promise.all([first,second]);
  assert.equal(calls.filter(Array.isArray).filter(c=>c[0]?.id).length,1);
  assert.equal(ui.watched.size,1);assert.equal(media.playing,playing);
});
test('saved songs open metadata without making another download job',async()=>{
  const {ui,calls}=setup();const item={id:'fixture_A01',downloaded:true};
  ui.details=async t=>calls.push(['metadata',t]);await ui.quickQueue(item);
  assert.equal(calls.length,1);assert.equal(calls[0][0],'metadata');
});
test('changing libraries while resolving a download cannot enqueue into the new library',async()=>{
  const {env,ui,calls}=setup();let finish;
  env.RecordCards.resolve=()=>new Promise(resolve=>{finish=resolve;});
  const pending=ui.quickQueue({id:'fixture_A01'});env.Profile.revision++;
  finish({tracks:[{id:'fixture_A01'}]});await pending;assert.equal(calls.length,0);
});
test('an album queues bounded batches without opening the preview or stopping playback',async()=>{
  const {env,ui,calls,media}=setup();const playing=media.playing;
  env.RecordCards.resolve=async()=>({tracks:Array.from({length:51},(_,i)=>({id:'track'+i}))});
  await ui.quickQueue({id:'album-one',type:'album'});
  const batches=calls.filter(Array.isArray);assert.deepEqual(batches.map(b=>b.length),[50,1]);
  assert.equal(ui.watched.size,2);assert.equal(media.playing,playing);
});
test('source limits remain visible and do not retry automatically',async()=>{
  const {env,ui,calls,messages}=setup();const item={id:'fixture_A01'};
  env.RecordCards.resolve=async()=>{throw Error('YouTube limitó las solicitudes. Esperá antes de reintentar.');};
  await ui.quickQueue(item);assert.equal(ui.pendingFor(item).status,'failed');
  assert.match(messages[0],/YouTube/);await ui.quickQueue(item);
  assert.equal(calls.length,1);assert.equal(calls[0][0],'details');
});
test('cover menu stays anchored, uses a popover and dispatches background download',async()=>{
  const {env,ui,calls}=setup();
  const src=fs.readFileSync(path.join(__dirname,'..','static','menus.js'),'utf8');vm.runInContext(src,env);
  const menus=env.window.RecordMenus,anchor=node('button'),item={id:'fixture_A01',type:'song',title:'Fixture'};
  ui.quickQueue=async t=>calls.push(['background',t.id]);
  menus.open(item,anchor);
  assert.equal(menus.node.tag,'div');assert.equal(menus.node.popoverOpened,true);
  assert.equal(anchor.attrs['aria-expanded'],'true');assert.equal(menus.node.style.left,'8px');
  assert.equal(menus.node.children[0].textContent,''); // No accidental literal "null" before the icon.
  await menus.node.children[0].onclick();
  assert.deepEqual(calls,[['background','fixture_A01']]);assert.equal(anchor.attrs['aria-expanded'],'false');
});
test('right-click and cover dots share a single menu and never double-register',()=>{
  const {env}=setup();vm.runInContext(fs.readFileSync(path.join(__dirname,'..','static','menus.js'),'utf8'),env);
  const menus=env.window.RecordMenus,frame=node(),card=node(),item={id:'fixture_A01',type:'song'};
  card.querySelector=()=>frame;menus.attach(card,item);menus.attach(card,item);assert.equal(frame.children.length,1);
  let opened=0;menus.open=()=>opened++;
  card.events.contextmenu({preventDefault(){},stopPropagation(){},clientX:25,clientY:25});
  frame.children[0].onclick({stopPropagation(){}});assert.equal(opened,2);
});
