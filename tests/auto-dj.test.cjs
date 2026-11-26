const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname,'..','static','collection.js'),'utf8').split('ListeningCollection.mount();')[0];
const songs = Array.from({length:24},(_,i)=>Object.freeze({id:'fixture'+String(i).padStart(4,'0'),type:'song',title:'Track '+i}));
const tick = () => new Promise(resolve=>setImmediate(resolve));
function setup(){
  const scheduler=new Map();
  let nextTimer=0;
  const calls=[],storage=new Map(),media={playing:null,items:[]},events=[];
  const env={window:{MediaUI:media},MediaUI:media,Profile:{user:{id:'ana'},library:{id:'main'},scope:s=>s},
    URLSearchParams,AbortController,toast:()=>{},safeUrl:(s,p)=>s.startsWith(p)?s:null,
    localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
    setTimeout:(f,ms)=>{scheduler.set(++nextTimer,[f,ms]);return nextTimer;},
    clearTimeout:i=>scheduler.delete(i),
    post:async(route,params)=>{
      calls.push({route,params});return route.endsWith('/next')?
        {items:songs.filter(t=>t.id!==params.id&&!params.exclude.includes(t.id)).slice(0,params.limit)}:{saved:true};
    }
  };
  vm.createContext(env);vm.runInContext(source,env);
  const c=env.window.ListeningCollection;c.paint=()=>{};
  c.playItem=async item=>{
    media.playing=item;c.starting(item);events.push(item.id);await c.played(item);if(c.filling)await c.filling;
  };
  function fireWarm(){
    const timer=[...scheduler].find(([,v])=>v[1]===300);
    if(timer){scheduler.delete(timer[0]);return timer[1][0]();}
  }
  return {env,c,calls,media,events,storage,fireWarm};
}

test('Auto DJ respects refill threshold, manual priority and non-repeating selection',async()=>{
  const {c,calls,events}=setup();
  c.dj.enabled=c.shuffle=true;c.dj.limit=4;c.dj.refill=1;
  await c.playItem(songs[0]);assert.equal(c.queue.length,4);
  const initial=calls.filter(x=>x.route.endsWith('/next')).length;
  await c.next();assert.equal(c.queue.length,3);
  await c.next();assert.equal(c.queue.length,2);
  assert.equal(calls.filter(x=>x.route.endsWith('/next')).length,initial);
  await c.playNext(songs[18]);assert.equal(c.queue[0].id,songs[18].id);
  c.changeDJ('criterion','library');await c.filling;
  assert.equal(c.queue[0].id,songs[18].id);
  await c.next();assert.equal(events.at(-1),songs[18].id);
  assert.equal(new Set(events).size,events.length);
  c.changeDJ('duplicates',true);await c.filling;
  assert.equal(c.settings().duplicates,true);
});

test('context playback follows the clicked grid, skips artists/albums and accepts frozen tracks',async()=>{
  const {c,events}=setup();
  const first={},ignored={},second={},third={};
  first.isConnected=true;first.parentElement={children:[first,ignored,second,third]};
  c.cardFor.set(songs[1],first);
  [[first,1],[second,2],[third,3]].forEach(([card,i])=>c.cardData.set(card,songs[i]));
  c.pool.set(songs[17].id,songs[17]);
  await c.playItem(songs[1]);
  assert.deepEqual(Array.from(c.queue,t=>t.id),[songs[2].id,songs[3].id]);
  c.move(1,0);await c.next();
  assert.equal(events.at(-1),songs[3].id);
  c.previous();await tick();
  assert.equal(events.at(-1),songs[1].id);
  assert.equal(c.queue[0].id,songs[3].id);
});

test('prepares exactly the head with JSON, updates after reorder, and stop drops an in-flight result',async()=>{
  const {c,media,env,fireWarm}=setup();
  const requests=[];
  env.fetch=(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}));
  c.dj.continuous=true;media.playing=songs[0];c.queue=songs.slice(1,6);
  c.warmNext();const first=fireWarm();assert.equal(requests.length,1);
  assert.equal(requests[0].url,'/api/listen/'+songs[1].id+'/prepare?native=1');
  assert.equal(requests[0].options.headers['Content-Type'],'application/json');
  assert.equal(requests[0].options.body,'{}');
  c.move(2,0);c.warmNext();await fireWarm();assert.equal(requests.length,1);
  requests[0].resolve({ok:true,json:async()=>({url:'/api/listen/old/audio/mp3'})});await first;
  assert.equal(c.ready,undefined);
  const second=fireWarm();assert.equal(requests.length,2);
  assert.equal(requests[1].url,'/api/listen/'+songs[3].id+'/prepare?native=1');
  c.stop();media.playing=null;
  assert.equal(requests[1].options.signal.aborted,true);
  requests[1].resolve({ok:true,json:async()=>({url:'/api/listen/old/audio/mp3'})});await second;
  assert.equal(c.queue.length,0);assert.equal(c.ready,null);assert.equal(requests.length,2);
});

test('playing a favorite starts the chosen track immediately then queues all other favorites newest first',async()=>{
  const {c,env,events,calls}=setup();
  const all=Array.from({length:123},(_,i)=>({id:'favorite_'+String(i).padStart(3,'0'),type:'song',title:'Favorite '+i}));
  const offsets=[];
  env.api=async path=>{
    const offset=Number(new URL(path,'https://example.test').searchParams.get('offset'));
    offsets.push(offset);return {items:all.slice(offset,offset+50),next_offset:offset+50<all.length?offset+50:null};
  };
  c.shuffle=c.dj.enabled=true;
  const pending=c.playFavorites(all[64]);
  assert.deepEqual(events,[all[64].id]);
  await pending;
  assert.deepEqual(offsets,[0,50,100]);
  assert.deepEqual(Array.from(c.queue,t=>t.id),all.filter(t=>t!==all[64]).map(t=>t.id));
  assert.equal(calls.some(v=>v.route.endsWith('/next')),false);
  await c.playNext(songs[2]);await c.appendQueue(songs[3]);
  assert.equal(c.queue.length,124);assert.equal(c.queue.at(-1).id,songs[3].id);
  await c.next();assert.equal(events.at(-1),songs[2].id);
});

test('stop invalidates in-flight favorites pagination; manual tail stays after later pages',async()=>{
  const {c,env}=setup();
  let complete;
  env.api=()=>new Promise(resolve=>{complete=resolve;});
  const first=c.playFavorites(songs[1]);
  await c.appendQueue(songs[15]);
  complete({items:songs.slice(0,4),next_offset:4});await tick();
  assert.deepEqual(Array.from(c.queue,t=>t.id),[songs[0].id,songs[2].id,songs[3].id,songs[15].id]);
  complete({items:songs.slice(4,8),next_offset:null});await first;
  assert.equal(c.queue.at(-1).id,songs[15].id);
  const later=c.playFavorites(songs[9]);c.stop();
  complete({items:songs,next_offset:null});await later;
  assert.equal(c.queue.length,0);assert.equal(c.fixed,null);
});
