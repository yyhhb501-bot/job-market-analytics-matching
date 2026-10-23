const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const C=require('./core.js');
function harness(initialData={}){
 const data=initialData, navigations=[], alarms=new Map(), downloads=[];let listener;
 let now=Date.parse('2026-09-23T01:00:00Z');
 class Clock extends Date {constructor(...args){super(...(args.length?args:[now]));}static now(){return now;}}
 const event=()=>({listeners:[],addListener(fn){this.listeners.push(fn);}});
 const chrome={storage:{local:{get:async key=>Array.isArray(key)?Object.fromEntries(key.map(k=>[k,structuredClone(data[k])])):{[key]:structuredClone(data[key])},set:async value=>Object.assign(data,structuredClone(value))}},
  runtime:{getURL:path=>'chrome-extension://test/'+path,onMessage:{addListener:fn=>listener=fn},onInstalled:event(),onStartup:event()},
  alarms:{clear:async name=>alarms.delete(name),create:async(name,options)=>alarms.set(name,options),onAlarm:event()},
  tabs:{get:async id=>({id,url:navigations.findLast(n=>n.id===id)?.url || 'https://www.linkedin.com/feed/'}),
    reload:async id=>navigations.push({id,url:navigations.findLast(n=>n.id===id)?.url,reloaded:true}),
    query:async()=>[{id:7,url:'https://www.linkedin.com/feed/'}],create:async props=>({id:9,...props}),update:async(id,props)=>navigations.push({id,...props})},
  downloads:{download:async options=>{downloads.push(options);return 123;},search:async()=>[{state:'complete'}]}};
 const {PRESETS}=require('./presets.js');
 const context=vm.createContext({chrome,importScripts(){},LinkedInCollector:C,LINKEDIN_PRESETS:PRESETS,crypto:require('node:crypto').webcrypto,URL,URLSearchParams,Date:Clock,Promise,encodeURIComponent});
 vm.runInContext(fs.readFileSync(__dirname+'/pacing.js','utf8'),context);
 vm.runInContext(fs.readFileSync(__dirname+'/controller.js','utf8'),context);
 vm.runInContext(fs.readFileSync(__dirname+'/background.js','utf8'),context);
 return {data,navigations,alarms,downloads,chrome,context,now:()=>now,advance:ms=>now+=ms,
  tick:()=>vm.runInContext('pacedTick()',context),
  watchdog:()=>vm.runInContext('watchdogTick()',context),
  retry:()=>vm.runInContext('retryPage()',context),
  sync:()=>vm.runInContext('syncCheckpoint()',context),
  send:(m,sender={url:'chrome-extension://test/popup.html'})=>new Promise(resolve=>listener(m,sender,resolve))};
}
const config={keywords:'Data Analyst',excludes:'',location:'usa',workplace:'any',days:7,maxJobs:1,maxPages:3,delay:5,strictTitle:true};

test('resume migrates only the checkpoint failed by the obsolete layout guard once',async()=>{
 const h=harness();await h.send({type:'startPaced'});await add(h,101);
 const q=h.data.run.queue[h.data.run.queueIndex];
 q.status='failed';q.attempts=3;q.lastError='搜索条件或页面已改变，采集已暂停。';
 h.data.run.status='paused';h.data.run.message='当前分区失败次数已超过 2 次，请导出报告后缩小分区。';
 const originalId=h.data.run.id;
 const resumed=await h.send({type:'resume',defer:true});assert.equal(resumed.ok,true);
 assert.ok(h.alarms.has('linkedin-next-detail'));
 const recovered=h.data.run.queue[h.data.run.queueIndex];
 assert.equal(recovered.layoutRecoveryVersion,1);assert.equal(recovered.previousLayoutError.attempts,3);
 assert.ok(h.data.run.jobs['101']);assert.equal(h.data.run.id,originalId);
 recovered.status='failed';recovered.attempts=3;h.data.run.status='paused';
 assert.equal((await h.send({type:'resume',defer:true})).ok,true);
 assert.equal(h.data.run.queue.find(q=>q.id===recovered.id).status,'split');
 assert.equal(h.data.run.queue.find(q=>q.id===recovered.id).attempts,3);
 assert.notEqual(h.data.run.queueIndex,0);
});

test('explicit resume splits a failed ordinary query and preserves its report and saved jobs',async()=>{
 const h=harness();await h.send({type:'start',config});
 const q=h.data.run.queue[0];q.status='failed';q.lastError='卡片结构暂时不可用';q.attempts=3;
 h.data.run.status='paused';h.data.run.jobs['101']={source_job_id:'101',description:'preserved'};
 const result=await h.send({type:'resume'});assert.equal(result.ok,true);
 assert.equal(h.data.run.queue[0].status,'split');assert.equal(h.data.run.queue[0].lastError,q.lastError);
 assert.ok(h.data.run.queue.length>1);assert.equal(h.data.run.page,0);assert.ok(h.data.run.jobs['101']);
});

test('failed verification or rate-limit checkpoints cannot be skipped or split',async()=>{
 for(const lastError of ['需要完成安全验证','HTTP 429 too many requests']) {
  const h=harness();await h.send({type:'start',config});
  h.data.run.queue[0].status='failed';h.data.run.queue[0].lastError=lastError;h.data.run.status='paused';
  assert.equal((await h.send({type:'resume'})).ok,false);
  assert.equal(h.data.run.queue.length,1);assert.equal(h.data.run.status,'paused');
 }
});

test('read-only dashboard status responds while a source operation holds the command queue',async()=>{
 const h=harness();await h.send({type:'startPaced'});h.data.run.status='paused';h.data.run.message='已停止，进度已保存。';
 vm.runInContext(fs.readFileSync(__dirname+'/controller.js','utf8'),h.context);
 vm.runInContext('globalThis.LinkedInSync={summary:async()=>({pendingSync:0,synced:0,needsSetup:true})}',h.context);
 let release;
 h.chrome.tabs.query=()=>new Promise(resolve=>{release=()=>resolve([{id:7,url:'https://www.linkedin.com/feed/'}]);});
 const operation=h.send({type:'startPaced'});
 await new Promise(resolve=>setImmediate(resolve));
 assert.ok(release);
 try {
  const result=await Promise.race([h.send({type:'collectorControl',platform:'linkedin',action:'status'},
    {url:'http://localhost:3000/admin/imports',tab:{url:'http://localhost:3000/admin/imports'},frameId:0}),
    new Promise((_,reject)=>setTimeout(()=>reject(Error('status blocked behind collection')),1000))]);
  assert.equal(result.ok,true);assert.equal(result.value.platform,'linkedin');assert.equal(result.value.status,'paused');
 } finally {release();await operation;}
});
test('daily refresh revisits an old ID and incremental export waits for download completion',async()=>{
 const h=harness();await h.send({type:'startPaced'});await add(h,777);
 await h.sync();assert.equal(h.downloads.length,1);
 h.chrome.downloads.search=async()=>[{state:'in_progress'}];
 await h.sync();assert.equal(h.downloads.length,1);assert.equal(h.data.run.syncPending,true);
 h.chrome.downloads.search=async()=>[{state:'complete'}];
 await h.sync();assert.equal(h.data.run.syncPending,false);
 h.advance(86400000);
 await add(h,777,{description:'Updated full description '.repeat(10)});
 assert.match(h.data.run.jobs['777'].description,/Updated/);
 await h.sync();assert.equal(h.downloads.length,2);
 const payload=JSON.parse(decodeURIComponent(h.downloads[1].url.split(',').slice(1).join(',')));
 assert.equal(payload.jobs.length,1);assert.match(payload.jobs[0].description,/Updated/);
});
test('interrupted automatic downloads retry and restart restores pending sync',async()=>{
 const h=harness();await h.send({type:'startPaced'});await add(h,778);await h.sync();
 h.chrome.downloads.search=async()=>[{state:'interrupted'}];
 await h.sync();assert.equal(h.downloads.length,2);assert.equal(h.data.run.syncPending,true);
 h.alarms.clear();
 for(const fn of h.chrome.runtime.onInstalled.listeners) await fn({reason:'update'});
 assert.ok(h.alarms.has('linkedin-database-sync'));
});
test('scope upgrade replaces obsolete AU query and preserves jobs and manual pause',async()=>{
 const h=harness();await h.send({type:'startPaced'});await add(h,101);
 h.data.run.scopeVersion=undefined;
 h.data.run.queue=[{...h.data.run.queue[0],id:'old-au-data',country:'AU',keyword:'Data Engineer'}];
 h.data.run.queueIndex=0;h.data.run.page=8;h.data.run.visit={source_job_id:'999'};
 h.data.run.status='paused';h.data.run.message='已手动暂停';
 for(const listener of h.chrome.runtime.onInstalled.listeners) await listener({reason:'update'});
 assert.ok(h.data.run.jobs['101']);assert.equal(h.data.run.status,'paused');
 assert.equal(h.data.run.page,0);assert.equal(h.data.run.visit,null);
 assert.ok(h.data.run.queue.filter(q=>q.country==='AU').every(q=>q.keyword==='Registered Nurse'));
});
test('daily start preserves paused work and queued country',async()=>{
 const h=harness();await h.send({type:'start',config});await h.send({type:'stop'});
 const id=h.data.run.id;h.data.dailyQueue=['sentinel'];
 const result=await h.send({type:'runDailyNow'});
 assert.equal(result.ok,false);assert.equal(h.data.run.id,id);assert.deepEqual(h.data.dailyQueue,['sentinel']);
});
test('schedule rejects invalid times before storing them',async()=>{
 const h=harness();
 for(const schedule of [{enabled:true,hour:24,minute:0},{enabled:true,hour:8,minute:60}]){
  assert.equal((await h.send({type:'setSchedule',schedule})).ok,false);
 }
 assert.equal(h.data.schedule,undefined);
 assert.equal((await h.send({type:'setSchedule',schedule:{enabled:true,hour:8,minute:0}})).ok,true);
});
test('daily completion exports US then starts Australia on the same tab',async()=>{
 const h=harness();const r=await h.send({type:'runDailyNow'});assert.equal(r.ok,true);
 assert.equal(h.data.run.config.location,'usa');h.data.run.config.maxJobs=1;
 await h.send({type:'job',runId:r.value.id,job:{source_job_id:'123',detail_status:'complete'}},{tab:{id:7}});
 const result=await h.send({type:'advance',runId:r.value.id,last:true},{tab:{id:7}});
 assert.equal(result.ok,true);assert.equal(h.data.run.config.location,'australia');
 assert.equal(h.data.run.tabId,7);assert.equal(h.data.previousRun.jobs['123'].detail_status,'complete');
});
test('start uses existing tab; completed limit stops without another navigation',async()=>{
 const h=harness();const r=await h.send({type:'start',config});assert.equal(r.ok,true);
 assert.equal(h.navigations[0].id,7);const runId=r.value.id;
 await h.send({type:'job',runId,job:{source_job_id:'1',detail_status:'complete'}},{tab:{id:7}});
 const done=await h.send({type:'advance',runId,last:false},{tab:{id:7}});
 assert.equal(done.value.status,'done');assert.equal(h.navigations.length,1);
});
test('other tabs cannot write; stopped run rejects in-flight results; resume retains jobs',async()=>{
 const h=harness();const start=await h.send({type:'start',config});const runId=start.value.id;
 await h.send({type:'job',runId,job:{source_job_id:'foreign'}},{tab:{id:8}});
 assert.equal(Object.keys(h.data.run.jobs).length,0);
 await h.send({type:'job',runId,job:{source_job_id:'1',detail_status:'complete'}},{tab:{id:7}});
 await h.send({type:'stop'});
 await h.send({type:'job',runId,job:{source_job_id:'late'}},{tab:{id:7}});
 assert.equal(h.data.run.jobs.late,undefined);
 const resumed=await h.send({type:'resume'});assert.equal(resumed.value.status,'running');assert.ok(resumed.value.jobs['1']);
});

function validJob(id,now) {
 return {source_job_id:String(id),detail_status:'complete',title:'Data Engineer',company:'Example',location:'USA',
  description:'Real job description. '.repeat(10),canonical_url:`https://www.linkedin.com/jobs/view/${id}/`,
  posted_at:new Date(now-3600000).toISOString(),collected_at:new Date(now).toISOString(),closed:false};
}
const tab={tab:{id:7}};
async function add(h,id,extra={}) {
 return h.send({type:'job',runId:h.data.run.id,job:{...validJob(id,h.now()),...extra}},tab);
}
test('paced plan uses verified unique records and stops precisely at hourly budget',async()=>{
 const h=harness();assert.equal((await h.send({type:'startPaced'})).ok,true);
 assert.equal(h.data.run.config.maxJobs,600);assert.equal(h.data.run.config.delay,10);
 assert.equal(h.data.run.queue[0].country,'US');assert.equal(h.data.run.queue[1].country,'AU');
 for(const extra of [{detail_status:'failed'},{company:''},{closed:true},{closed:null},{posted_at:null}]) await add(h,99,extra);
 assert.equal(Object.keys(h.data.run.jobs).length,0);
 await add(h,1);await add(h,1);
 assert.equal(h.data.run.pacing.slotCount,1);
 for(let i=2;i<=50;i++) await add(h,i);
 await add(h,51);
 assert.equal(Object.keys(h.data.run.jobs).length,50);assert.equal(h.data.run.status,'waiting');
 assert.equal(h.downloads.length,1);
 const navCount=h.navigations.length;await h.tick();assert.equal(h.navigations.length,navCount);
 h.advance(3600000);await h.tick();assert.equal(h.data.run.status,'running');
 const skip=await h.send({type:'preflight',runId:h.data.run.id,jobId:'1'},tab);
 assert.equal(skip.value.skip,true);
 await add(h,51);assert.equal(h.data.run.pacing.slotCount,1);
});
test('daily target wait retains the same run and Beijing daily count survives posting age rollover',async()=>{
 const h=harness();await h.send({type:'startPaced'});h.advance(3*3600000);
 h.data.acceptedJobs=Object.fromEntries(Array.from({length:599},(_,i)=>[String(1000+i),new Date(h.now()-3*3600000).toISOString()]));
 await add(h,1);
 assert.equal(Object.keys(h.data.run.jobs).length,1);
 await h.send({type:'preflight',runId:h.data.run.id,jobId:'2'},tab);
 assert.equal(h.data.run.status,'waiting');
 assert.equal(h.data.run.pacing.notBefore,Date.parse('2026-09-24T01:00:00Z'));
 assert.equal((await h.send({type:'pacedState'})).value.count,600);
 h.advance(21*3600000);await h.tick();
 assert.equal(h.data.run.status,'running');
 assert.equal(h.data.run.pacing.phase,'backfill');
 assert.equal(h.data.run.pacing.target,600);
 assert.equal(h.data.run.config.maxJobs,600);
 assert.ok(h.data.acceptedJobs['1']);
 assert.equal(Object.keys(h.data.run.jobs).length,1);
 await add(h,1);assert.equal(Object.keys(h.data.run.jobs).length,1);
 await add(h,2,{title:'Registered Nurse',posted_at:new Date(h.now()-23.5*3600000).toISOString()});
 assert.equal(Object.keys(h.data.run.jobs).length,2);
 h.advance(3600000);
 const state=await h.send({type:'pacedState'});assert.equal(state.value.count,1);
});

test('600-per-day upgrade preserves historical jobs, checkpoint, manual pause and hourly visit ledger',async()=>{
 const h=harness();await h.send({type:'startPaced'});await add(h,1);
 h.data.run.scheduleVersion=2;h.data.run.pacing.target=1000;h.data.run.config.maxJobs=1000;
 h.data.run.page=7;h.data.run.status='paused';h.data.run.message='已手动暂停';
 h.data.pacedRate={hour:Math.floor(h.now()/3600000),count:17,nextAt:h.now()+72000};
 const id=h.data.run.id;
 for(const listener of h.chrome.runtime.onInstalled.listeners)await listener({reason:'update'});
 assert.equal(h.data.run.id,id);assert.equal(h.data.run.page,7);assert.ok(h.data.run.jobs['1']);
 assert.equal(h.data.run.status,'paused');assert.equal(h.data.run.pacing.target,600);
 assert.equal(h.data.run.config.maxJobs,600);assert.equal(h.data.pacedRate.count,17);
 assert.equal((await h.send({type:'pacedState'})).value.count,1);
});
test('paused restrictions cannot be restarted by the scheduler or by a new plan',async()=>{
 const h=harness();await h.send({type:'startPaced'});
 await h.send({type:'pause',runId:h.data.run.id,reason:'HTTP 429 too many requests'},tab);
 const count=h.navigations.length;h.advance(7*3600000);await h.tick();
 assert.equal(h.navigations.length,count);assert.equal(h.data.run.status,'paused');
 assert.equal((await h.send({type:'startPaced'})).ok,false);
 assert.equal((await h.send({type:'resume'})).ok,true);
 assert.equal(h.data.run.status,'running');
});
test('main plan button resumes an ordinary paused paced run from its checkpoint',async()=>{
 const h=harness();await h.send({type:'startPaced'});
 h.data.run.status='paused';h.data.run.message='搜索条件或页面已改变，采集已暂停。';
 const id=h.data.run.id;
 const result=await h.send({type:'startPaced'});
 assert.equal(result.ok,true);assert.equal(h.data.run.id,id);
 assert.equal(h.data.run.status,'running');
 assert.match(h.data.run.message,/继续|读取/);
});
test('stop disables background wakeups and prevents late job writes',async()=>{
 const h=harness();await h.send({type:'startPaced'});await h.send({type:'stop'});
 assert.equal(h.data.pacedEnabled,false);assert.equal(h.alarms.has('linkedin-paced-collector'),false);
 h.advance(3600000);await h.tick();await add(h,1);
 assert.equal(h.data.run.status,'paused');assert.equal(Object.keys(h.data.run.jobs).length,0);
});
test('跨午夜后次日继续同一队列，不重建分区也不丢失已采职位',async()=>{
 const h=harness();await h.send({type:'startPaced'});
 h.data.run.pacing.target=600;h.data.run.config.maxJobs=600;
 for(let i=1;i<=7;i++) await add(h,i);
 h.data.run.pacing.slotCount=50;
 await h.send({type:'preflight',runId:h.data.run.id,jobId:'8'},tab);
 assert.equal(h.data.run.status,'waiting');
 const queueBefore=h.data.run.queue.map(q=>q.id).join(',');
 const jobsBefore=Object.keys(h.data.run.jobs);
 h.advance(25*3600000);await h.tick();
 assert.equal(h.data.run.status,'running');
 assert.equal(h.data.run.pacing.slotCount,0);
 assert.equal(h.data.run.queue.map(q=>q.id).join(','),queueBefore);
 assert.equal(Object.keys(h.data.run.jobs).length,7);
 assert.deepEqual(Object.keys(h.data.run.jobs),jobsBefore);
 await add(h,8);assert.equal(Object.keys(h.data.run.jobs).length,8);
});
test('page advancement rotates countries and resumes each saved next page',async()=>{
 const h=harness();await h.send({type:'startPaced'});
 h.data.run.queue=h.data.run.queue.slice(0,2);
 await h.send({type:'advance',runId:h.data.run.id,last:false,resultCount:100},tab);
 assert.equal(h.data.run.queue[0].page,1);assert.equal(h.data.run.queue[0].status,'pending');
 assert.equal(h.data.run.queueIndex,1);assert.equal(h.data.run.page,0);
 assert.equal(h.data.run.queue[1].country,'AU');
 await h.send({type:'advance',runId:h.data.run.id,last:false,resultCount:100},tab);
 assert.equal(h.data.run.queue[1].page,1);assert.equal(h.data.run.queueIndex,0);
 assert.equal(h.data.run.page,1);
 assert.equal(new URL(h.navigations.at(-1).url).searchParams.get('start'),'25');
 await h.send({type:'advance',runId:h.data.run.id,last:true,resultCount:100},tab);
 assert.equal(h.data.run.queue[0].status,'done');assert.equal(h.data.run.queueIndex,1);
 assert.equal(h.data.run.queue[1].country,'AU');assert.equal(h.data.run.page,1);
});
test('exhausted coverage exports actual query statuses and waits six hours without claiming success',async()=>{
 const h=harness();await h.send({type:'startPaced'});await add(h,1);
 h.data.run.queue=h.data.run.queue.slice(0,1);
 await h.send({type:'advance',runId:h.data.run.id,last:true,resultCount:1},tab);
 assert.equal(h.data.run.status,'waiting');assert.equal(h.data.run.pacing.phase,'backfill');
 assert.equal(h.data.run.queue[0].status,'done');assert.equal(h.data.run.pacing.notBefore,h.now()+6*3600000);
 const payload=JSON.parse(decodeURIComponent(h.downloads[0].url.split(',').slice(1).join(',')));
 assert.equal(payload.queries[0].status,'done');assert.equal(payload.pacing.validCount,1);
 h.advance(6*3600000);await h.tick();assert.equal(h.data.run.status,'running');
 assert.ok(h.data.run.queue.length>1);assert.equal(h.data.run.pacing.phase,'backfill');
 assert.equal(h.data.coverageHistory[0].queries[0].status,'done');
});
test('new manual runs cannot bypass an unexpired rate-limit cooldown',async()=>{
 const h=harness();await h.send({type:'start',config});
 await h.send({type:'pause',runId:h.data.run.id,reason:'HTTP 429'},tab);
 await h.send({type:'stop'});
 assert.equal((await h.send({type:'startPaced'})).ok,false);
 assert.equal((await h.send({type:'start',config})).ok,false);
});

async function batch(h,ids,last=false) {
 return h.send({type:'pageBatch',runId:h.data.run.id,jobs:ids.map(id=>({...validJob(id,h.now()),title:'Data Analyst'})),last,resultCount:100},
  {tab:{id:7},url:C.searchUrl(h.data.run)});
}
async function finish(h,id) {
 return h.send({type:'detailDone',runId:h.data.run.id,jobId:String(id)},
  {tab:{id:7},url:`https://www.linkedin.com/jobs/view/${id}/?trk=flagship3_search_srp_jobs`});
}
test('two full-document detail navigations survive worker restart then automatically advance search',async()=>{
 const first=harness();await first.send({type:'start',config:{...config,maxJobs:10}});
 assert.equal((await batch(first,[101,102])).ok,true);
 assert.equal(first.navigations.at(-1).url,'https://www.linkedin.com/jobs/view/101/');
 await add(first,101);
 const second=harness(first.data); // no content-script locals or worker globals survive
 assert.equal((await finish(second,101)).ok,true);
 assert.equal(second.data.run.status,'running');
 assert.equal(second.navigations.at(-1).url,'https://www.linkedin.com/jobs/view/102/');
 await add(second,102);await finish(second,102);
 assert.equal(second.data.run.status,'running');assert.equal(second.data.run.page,1);
 assert.equal(new URL(second.navigations.at(-1).url).searchParams.get('start'),'25');
 assert.equal(Object.keys(second.data.run.jobs).length,2);
});
test('unexpected job pages cannot complete or advance the queued detail',async()=>{
 const h=harness();await h.send({type:'start',config:{...config,maxJobs:10}});await batch(h,[101,102]);
 assert.equal((await finish(h,999)).ok,false);assert.equal(h.data.run.pageBatch.index,0);
 assert.equal(C.matchesDetailUrl('https://www.linkedin.com/jobs/view/999/',h.data.run),false);
 assert.equal(C.matchesDetailUrl('https://www.linkedin.com/jobs/view/101/?trk=test',h.data.run),true);
});
test('detail timeout retries twice, then preserves the failure and proceeds to the next queued job',async()=>{
 const h=harness();await h.send({type:'start',config:{...config,maxJobs:10}});await batch(h,[101,102]);
 for(let attempt=1;attempt<=3;attempt++) {
  await h.send({type:'pause',runId:h.data.run.id,reason:'页面加载超时',recoverable:true},tab);
  assert.equal(h.data.run.status,'retrying');
  const before=h.navigations.length;await h.retry();assert.equal(h.navigations.length,before);
  h.advance(attempt<=2?2*2**(attempt-1)*60000:120000);await h.retry();assert.equal(h.data.run.status,'running');
  if(attempt<=2)assert.equal(h.data.run.visit.source_job_id,'101');
 }
 assert.equal(h.data.run.visit.source_job_id,'102');
 assert.equal(h.data.run.pageBatch.index,1);
 assert.equal(h.data.run.failures['101'].attempts,3);
 assert.equal(h.data.run.failures['101'].job.source_job_id,'101');
});

test('upgrade migrates an eleven-retry checkpoint without refreshing the failed job again',async()=>{
 const h=harness();await h.send({type:'startPaced'});await add(h,99);await batch(h,[101,102]);
 const id=h.data.run.id;h.data.run.status='retrying';h.data.run.retryAttempts=11;h.data.run.retryAt=h.now()+1800000;
 const before=h.navigations.length;
 for(const listener of h.chrome.runtime.onInstalled.listeners)await listener({reason:'update'});
 assert.equal(h.data.run.id,id);assert.ok(h.data.run.jobs['99']);
 assert.equal(h.data.run.failures['101'].attempts,11);assert.equal(h.data.run.pageBatch.index,1);
 assert.equal(h.data.run.retryAt,h.now()+120000);assert.equal(h.navigations.length,before);
 h.advance(120000);await h.retry();
 assert.equal(h.data.run.visit.source_job_id,'102');
 assert.equal(h.navigations.at(-1).url,'https://www.linkedin.com/jobs/view/102/');
});

test('search timeout exhausts its budget and retains the failed partition before selecting another',async()=>{
 const h=harness();await h.send({type:'startPaced'});const original=h.data.run.queue[0].id;
 for(let attempt=1;attempt<=3;attempt++) {
  await h.send({type:'pause',runId:h.data.run.id,reason:'search-results 加载超时',stage:'search-results',recoverable:true},tab);
  if(attempt<3) {h.advance(attempt===1?120000:240000);await h.retry();}
 }
 const prior=h.data.run.queue.find(q=>q.id===original);
 assert.ok(['failed','split'].includes(prior.status));assert.equal(prior.lastFailure.stage,'search-results');
 assert.notEqual(h.data.run.queue[h.data.run.queueIndex].id,original);
 assert.equal(h.data.run.status,'retrying');assert.equal(h.data.run.retryAttempts,0);
});

test('no remaining searchable partition pauses clearly instead of repeating forever',async()=>{
 const h=harness();await h.send({type:'start',config:{...config,maxSplitDepth:0}});
 for(let attempt=1;attempt<=3;attempt++) {
  await h.send({type:'pause',runId:h.data.run.id,reason:'加载超时',recoverable:true},tab);
  if(attempt<3) {h.advance(attempt===1?120000:240000);await h.retry();}
 }
 assert.equal(h.data.run.status,'paused');assert.equal(h.data.run.queue[0].status,'failed');
 assert.equal(h.alarms.has('linkedin-page-retry'),false);
});

test('upgrade never skips an over-limit checkpoint carrying a verification or cooldown restriction',async()=>{
 for(const reason of ['需要完成安全验证','HTTP 429 too many requests']) {
  const h=harness();await h.send({type:'startPaced'});await batch(h,[101,102]);
  h.data.run.status='retrying';h.data.run.retryAttempts=11;h.data.run.message=reason;
  const before=h.navigations.length;
  for(const listener of h.chrome.runtime.onInstalled.listeners)await listener({reason:'update'});
  assert.equal(h.data.run.status,'paused');assert.equal(h.data.run.pageBatch.index,0);
  assert.equal(h.navigations.length,before);assert.equal(h.data.run.failures,undefined);
 }
});

test('legacy white page is refreshed and browser restart resumes without a click',async()=>{
 const h=harness();await h.send({type:'start',config:{...config,maxJobs:10}});
 h.advance(120001);await h.watchdog();
 assert.equal(h.data.run.status,'retrying');
 h.advance(120000);await h.retry();
 assert.equal(h.data.run.status,'running');
 assert.equal(h.navigations.at(-1).reloaded,true);
 for(const listener of h.chrome.runtime.onStartup.listeners) listener();
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(h.data.run.status,'retrying');
 assert.equal(h.alarms.has('linkedin-page-retry'),true);
});
test('hourly waiting preserves a detail batch and resumes the next unvisited job',async()=>{
 const h=harness();await h.send({type:'startPaced'});await batch(h,[101,102]);
 h.data.run.pacing.slotCount=49;await add(h,101);await finish(h,101);
 assert.equal(h.data.run.status,'waiting');assert.equal(h.data.run.pageBatch.index,1);
 h.advance(3600000);await h.tick();
 assert.equal(h.data.run.status,'running');assert.equal(h.data.run.visit.source_job_id,'102');
 assert.equal(h.navigations.at(-1).url,'https://www.linkedin.com/jobs/view/102/');
});
test('stop cancels scheduled retry and security challenges never auto-retry',async()=>{
 const h=harness();await h.send({type:'start',config});
 await h.send({type:'pause',runId:h.data.run.id,reason:'加载超时',recoverable:true},tab);
 await h.send({type:'stop'});const before=h.navigations.length;
 h.advance(60000);await h.retry();assert.equal(h.navigations.length,before);
 assert.equal(h.alarms.has('linkedin-page-retry'),false);
 await h.send({type:'resume'});
 await h.send({type:'pause',runId:h.data.run.id,reason:'需要完成安全验证',recoverable:true},tab);
 assert.equal(h.data.run.status,'paused');assert.equal(h.alarms.has('linkedin-page-retry'),false);
});
test('paced minute alarm cannot bypass delayed retries',async()=>{
 const h=harness();await h.send({type:'startPaced'});await batch(h,[101,102]);
 await h.send({type:'pause',runId:h.data.run.id,reason:'加载超时',recoverable:true},tab);
 const before=h.navigations.length;await h.tick();
 assert.equal(h.navigations.length,before);assert.equal(h.data.run.status,'retrying');
});

test('night start does not navigate; the 09:00 alarm begins automatically',async()=>{
 const h=harness();h.advance(14*3600000);
 await h.send({type:'startPaced'});
 assert.equal(h.data.run.status,'waiting');assert.equal(h.navigations.length,0);
 assert.equal(h.data.run.pacing.notBefore,Date.parse('2026-09-24T01:00:00Z'));
 h.advance(10*3600000);await h.tick();
 assert.equal(h.data.run.status,'running');assert.equal(h.navigations.length,1);
});

test('23:00 preserves page and batch; next morning reads the remaining detail',async()=>{
 const h=harness();await h.send({type:'startPaced'});await batch(h,[101,102]);await add(h,101);
 h.advance(14*3600000);await finish(h,101);
 assert.equal(h.data.run.status,'waiting');assert.equal(h.data.run.pageBatch.index,1);
 const before=h.navigations.length;
 h.advance(9*3600000);await h.tick();assert.equal(h.navigations.length,before);
 h.advance(3600000);await h.tick();
 assert.equal(h.navigations.at(-1).url,'https://www.linkedin.com/jobs/view/102/');
});

test('detail spacing persists through worker restart and waits without re-reading the previous detail',async()=>{
 const h=harness();await h.send({type:'startPaced'});await batch(h,[101,102]);await add(h,101);await finish(h,101);
 assert.equal(h.data.run.status,'waiting');assert.equal(h.data.run.pageBatch.index,1);
 assert.equal(h.data.run.pacing.notBefore,h.now()+72000);
 const restored=harness(h.data);restored.advance(71999);await restored.tick();
 assert.equal(restored.navigations.length,0);
 restored.advance(1);await restored.tick();
 assert.equal(restored.navigations.at(-1).url,'https://www.linkedin.com/jobs/view/102/');
});

test('detail request budget includes failed or invalid records, not only accepted jobs',async()=>{
 const h=harness();await h.send({type:'startPaced'});await batch(h,[101,102]);
 h.data.pacedRate.count=50;
 await finish(h,101);
 assert.equal(h.data.run.status,'waiting');
 assert.equal(h.data.run.pacing.notBefore,Date.parse('2026-09-23T02:00:00Z'));
 h.advance(3600000);await h.tick();
 assert.equal(h.data.pacedRate.count,1);
 assert.equal(h.navigations.at(-1).url,'https://www.linkedin.com/jobs/view/102/');
});

test('same URL timeout forces reload and retry deferred overnight retains its count',async()=>{
 const h=harness();await h.send({type:'startPaced'});await batch(h,[101,102]);
 await h.send({type:'pause',runId:h.data.run.id,reason:'加载超时',recoverable:true},tab);
 h.advance(120000);await h.retry();
 assert.equal(h.navigations.at(-1).reloaded,true);
 await h.send({type:'pause',runId:h.data.run.id,reason:'加载超时',recoverable:true},tab);
 h.advance(14*3600000);await h.retry();
 assert.equal(h.data.run.status,'waiting');assert.equal(h.data.run.pacing.retryPending,true);
 assert.equal(h.data.run.retryAttempts,2);
 h.advance(10*3600000);await h.tick();
 assert.equal(h.data.run.status,'running');assert.equal(h.data.run.retryAttempts,2);
});

test('stalled document gets bounded retry instead of remaining running forever',async()=>{
 const h=harness();await h.send({type:'startPaced'});h.advance(120001);await h.tick();
 assert.equal(h.data.run.status,'retrying');assert.equal(h.data.run.retryAttempts,1);
 assert.equal(h.alarms.has('linkedin-page-retry'),true);
});

test('upgrade preserves collected data and retry checkpoint while applying new schedule',async()=>{
 const h=harness();await h.send({type:'startPaced'});await add(h,101);
 h.data.run.scheduleVersion=undefined;h.data.run.config.delay=60;
 h.data.run.status='retrying';h.data.run.retryAt=h.now()+120000;h.data.run.retryAttempts=2;
 for(const listener of h.chrome.runtime.onInstalled.listeners) await listener({reason:'update'});
 assert.equal(h.data.run.config.delay,10);assert.ok(h.data.run.jobs['101']);
 assert.equal(h.data.run.retryAttempts,2);assert.equal(h.data.run.status,'retrying');
 assert.equal(h.alarms.has('linkedin-page-retry'),true);
});

test('达到 600 条日目标后等待至次日 09:00，第 601 条当日不再采集，次日同一队列继续',async()=>{
 const h=harness();assert.equal((await h.send({type:'startPaced'})).ok,true);
 assert.equal(h.data.run.config.maxJobs,600);
 for(let i=1;i<=600;i++){
   if(i>1&&(i-1)%50===0)h.advance(3600000);
   await add(h,i);
 }
 assert.equal(Object.keys(h.data.run.jobs).length,600);
 await h.tick();
 assert.equal(h.data.run.status,'waiting');
 assert.equal(h.data.run.pacing.notBefore,Date.parse('2026-09-24T01:00:00Z'));
 await add(h,601);
 assert.equal(Object.keys(h.data.run.jobs).length,600);
 assert.equal(h.data.run.status,'waiting');
 h.advance(86400000);await h.tick();
 assert.equal(h.data.run.status,'running');
 assert.equal(Object.keys(h.data.run.jobs).length,600);
 await add(h,601);
 assert.equal(Object.keys(h.data.run.jobs).length,601);
});

test('跨午夜/等待后次日继续同一队列，各分区保存下一页',async()=>{
 const h=harness();await h.send({type:'startPaced'});
 h.data.run.queue=h.data.run.queue.slice(0,2);
 await h.send({type:'advance',runId:h.data.run.id,last:false,resultCount:100},{tab:{id:7},url:C.searchUrl(h.data.run)});
 await h.send({type:'advance',runId:h.data.run.id,last:false,resultCount:100},{tab:{id:7},url:C.searchUrl(h.data.run)});
 const usId=h.data.run.queue[0].id,auId=h.data.run.queue[1].id;
 h.data.run.queue[1].page=4;
 await h.send({type:'advance',runId:h.data.run.id,last:true,resultCount:100},{tab:{id:7},url:C.searchUrl(h.data.run)});
 assert.equal(h.data.run.queue[0].status,'done');
 assert.equal(h.data.run.queue[0].page,1);
 assert.equal(h.data.run.queueIndex,1);
 assert.equal(h.data.run.page,4);
 assert.equal(new URL(h.navigations.at(-1).url).searchParams.get('geoId'),'101452733');
 assert.equal(new URL(h.navigations.at(-1).url).searchParams.get('start'),'100');
 const before=h.data.run.id;
 h.data.run.status='waiting';h.data.run.pacing.notBefore=h.now()-1000;
 h.advance(86400000);await h.tick();
 assert.equal(h.data.run.id,before);
 assert.equal(h.data.run.status,'running');
 assert.equal(h.data.run.queueIndex,1);
 assert.equal(h.data.run.page,4);
 assert.equal(h.data.run.queue.find(q=>q.id===usId).status,'done');
 assert.equal(h.data.run.queue.find(q=>q.id===auId).page,4);
});

test('upgrading a 200-target wait releases only that wait while preserving the detail visit budget',async()=>{
 const h=harness();await h.send({type:'startPaced'});await batch(h,[101]);
 h.data.run.pacing.target=200;h.data.run.config.maxJobs=200;
 h.data.run.status='waiting';h.data.run.pacing.notBefore=h.now()+86400000;
 h.data.run.message='今日有效职位已达到 200 条，明天 09:00 自动继续。';
 h.data.pacedRate={hour:Math.floor(h.now()/3600000),count:50,nextAt:h.now()+72000};
 for(const fn of h.chrome.runtime.onInstalled.listeners) await fn({reason:'update'});
 assert.equal(h.data.run.pacing.target,600);assert.equal(h.data.pacedRate.count,50);
 assert.equal(h.data.run.status,'waiting');
 assert.equal(h.data.run.pacing.notBefore,Date.parse('2026-09-23T02:00:00Z'));
});

test('全部分区 done/limited/failed 时进入等待而不宣称完成',async()=>{
 const h=harness();await h.send({type:'startPaced'});
 h.data.run.queue=h.data.run.queue.slice(0,1);
 h.data.run.queue[0].status='limited';
 h.data.run.page=39;
 await h.send({type:'advance',runId:h.data.run.id,last:true,resultCount:1},{tab:{id:7},url:C.searchUrl(h.data.run)});
 assert.equal(h.data.run.status,'waiting');
 assert.equal(h.data.run.queue[0].status,'limited');
 assert.ok(h.data.run.queue[0].finishedAt);
 assert.equal(h.data.run.pacing.notBefore,h.now()+6*3600000);
});

test('已处于 v3 但仍按 200 预算运行的任务会补齐至 600，队列与职位不重建',async()=>{
 const h=harness();await h.send({type:'startPaced'});await add(h,7);
 h.data.run.scheduleVersion=3;h.data.run.scopeVersion=1;
 h.data.run.pacing.target=200;h.data.run.config.maxJobs=200;
 const id=h.data.run.id;
 const queueBefore=h.data.run.queue.map(q=>q.id).join(',');
 for(const listener of h.chrome.runtime.onInstalled.listeners)await listener({reason:'update'});
 assert.equal(h.data.run.id,id);
 assert.equal(h.data.run.pacing.target,600);
 assert.equal(h.data.run.config.maxJobs,600);
 assert.ok(h.data.run.jobs['7']);
 assert.equal(h.data.run.queue.map(q=>q.id).join(','),queueBefore);
});

test('starting an already waiting task clears a stale layout pause message without changing its pacing',async()=>{
 const h=harness();await h.send({type:'startPaced'});
 h.data.run.status='waiting';h.data.run.message='搜索条件或页面已改变，采集已暂停。';
 const before=h.data.run.pacing.notBefore;
 assert.equal((await h.send({type:'startPaced'})).ok,true);
 assert.equal(h.data.run.pacing.notBefore,before);assert.equal(h.data.run.status,'waiting');
 assert.doesNotMatch(h.data.run.message,/已暂停/);
});
