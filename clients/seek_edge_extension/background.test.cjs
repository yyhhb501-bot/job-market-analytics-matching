const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function detailReply(id) {
  return {ok:true,pageUrl:`https://au.seek.com/job/${id}`,jobs:[{source_job_id:id,title:'Registered Nurse',
    company:'Example Hospital',city:'Sydney',state:'NSW',description:'Responsibilities and requirements for registered nurses. '.repeat(4)}]};
}

function loadBackground({run, messages, activeTab, runTab, seenJobIds = {}, validJobs = false, fetcher, reviewHandler, timer=setTimeout, stored={},openTabs=[],createPending=false}) {
  let now = Date.parse('2026-09-23T01:00:00Z');
  class Clock extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } }
  const calls = [], reloads = [], created = [], removed=[], injections=[], tabs = new Map([[runTab.id,runTab],...openTabs.map(tab=>[tab.id,tab])]);
  const data = {continuousRun: run, seenJobIds,...stored};
  let listener;
  const chrome = {
    storage: {local: {
      get: async keys => structuredClone(Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(key => [key, data[key]]))),
      set: async values => Object.assign(data, structuredClone(values)),
      remove: async keys => (Array.isArray(keys) ? keys : [keys]).forEach(key => delete data[key])
    }},
    tabs: {
      query: async () => [activeTab],
      get: async id => tabs.get(id) || activeTab,
      create: async options => {const tab={id:1000+created.length,...options,...(createPending?{url:'',pendingUrl:options.url,status:'loading'}:{status:'complete'})};created.push(tab);tabs.set(tab.id,tab);return tab;},
      sendMessage: async (id, message) => {
        calls.push({id, type: message.type});
        const response = messages[message.type];
        return typeof response === 'function' ? response(message,tabs.get(id)) : response;
      },
      update: async (id, options) => {const tab=tabs.get(id);Object.assign(tab,options);return tab;},
      remove: async id => {removed.push(id);tabs.delete(id);},
      reload: async id => { reloads.push(id); return runTab; },
      onUpdated: {addListener() {}, removeListener() {}}
    },
    alarms: {create: async () => {}, clear: async () => {}, onAlarm: {addListener() {}}},
    scripting: {executeScript: async value => {injections.push(value);}},
    runtime: {
      getURL: () => 'chrome-extension://seek/',
      onMessage: {addListener: fn => {listener = fn;}},
      onInstalled: {addListener() {}}, onStartup: {addListener() {}}
    }
  };
  const C = {
    seekUrl: value => typeof value === 'string' && value.startsWith('https://au.seek.com/') ? value : null,
    config: () => ({apiUrl:'http://localhost:8010', token:'test'}),
    registeredNurseTitle: require('./core.js').registeredNurseTitle,
    valid: () => validJobs
  };
  const context = {
    globalThis: {SeekCollector:C,...(reviewHandler?{JobLifecycle:{run:reviewHandler}}:{})}, importScripts() {}, chrome, URL, Date:Clock, setTimeout:timer, clearTimeout, AbortSignal,
    crypto: {randomUUID: () => 'test-id'},
    fetch: fetcher || (async () => ({ok:true, status:200, json:async () => ({received_count:1,accepted_count:1,duplicate_count:0,rejected_count:0})}))
  };
  vm.runInNewContext(fs.readFileSync(require.resolve('./schedule.js'), 'utf8'), context);
  vm.runInNewContext(fs.readFileSync(require.resolve('./background.js'), 'utf8'), context);
  const send = type => new Promise(resolve => {
    listener({type}, {url:'chrome-extension://seek/popup.html'}, resolve);
  });
  return {send, data, calls, reloads, created, removed, tabs, injections, setTime:value => {now = Date.parse(value);},
    step:()=>context.continuousTick(),
    tick:async () => { const result = await context.continuousTick(); now += 72000; return result; }};
}

test('an unrelated user tab is preserved while the collector rebuilds its saved page',async()=>{
  const unrelated={id:22,url:'https://example.org/user-work',status:'complete'};
  const app=loadBackground({runTab:unrelated,activeTab:unrelated,
    run:{id:'recover',status:'running',tabId:22,page:7,pageUrl:'https://au.seek.com/Registered-Nurse-jobs?page=7',attemptedIds:['88']},
    messages:{checkSeekPage:{ok:false,error:'人工验证'}}});
  await app.tick();assert.equal(unrelated.url,'https://example.org/user-work');
  assert.equal(app.created.length,1);assert.equal(app.created[0].url,'https://au.seek.com/Registered-Nurse-jobs?page=7');
  assert.equal(app.data.continuousRun.page,7);assert.equal(app.data.continuousRun.attemptedIds[0],'88');
});

test('an upload failure persists the detail and retries without another upstream read',async()=>{
  const runTab={id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
  let offline=true;const keys=[];
  const app=loadBackground({runTab,activeTab:runTab,validJobs:true,
    run:{id:'outbox',status:'running',tabId:22,page:1,pageUrl:runTab.url,attemptedIds:[],accepted:0,duplicates:0,rejected:0,failed:0},
    messages:{checkSeekPage:{ok:true},listSearchSeekJobs:{ok:true,cardCount:1,readableCardCount:1,jobs:[{id:'1',title:'Registered Nurse'}],pageUrl:runTab.url},
      collectCurrentSeekPage:detailReply('1')},
    fetcher:async(_url,options)=>{keys.push(options.headers['Idempotency-Key']);if(offline)throw Error('offline');
      return {ok:true,json:async()=>({received_count:1,accepted_count:1,duplicate_count:0,rejected_count:0})};}});
  await app.tick();assert.ok(app.data.continuousRun.pendingDetail);assert.equal(keys.length,0);
  await app.tick();assert.ok(app.data.continuousRun.pendingUpload);
  const calls=app.calls.length;offline=false;await app.tick();
  assert.equal(app.calls.length,calls);assert.equal(app.data.continuousRun.pendingUpload,null);
  assert.equal(app.data.continuousRun.accepted,1);assert.equal(keys[0],keys[1]);
});

test('manual pause prevents a persisted upload from restarting collection',async()=>{
  const tab={id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
  let uploads=0;const app=loadBackground({runTab:tab,activeTab:tab,
    run:{id:'paused',status:'paused',tabId:22,pendingUpload:{job:{source_job_id:'1'}}},messages:{},
    fetcher:async()=>{uploads++;throw Error('must not run');}});
  await app.tick();assert.equal(uploads,0);assert.equal(app.created.length,0);assert.ok(app.data.continuousRun.pendingUpload);
});

test('live daily progress ignores an old 24/200 receipt and uses a cached authenticated read',async()=>{
 const tab={id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};let requests=0,offline=false;
 const app=loadBackground({runTab:tab,activeTab:tab,messages:{},run:{id:'live',status:'paused'},
  fetcher:async(url,options)=>{requests++;assert.match(url,/\/api\/v1\/import\/seek\/progress$/);
   assert.ok(options.signal);assert.equal(options.headers.Authorization,'Bearer test');if(offline)throw Error('offline');
   return{ok:true,json:async()=>({today_valid:0,today_target:600,hour_valid:0,hour_limit:50})};}});
 app.data.lastResult={progress:{today_valid:24,today_target:200}};
 const first=await app.send('seekProgress');assert.equal(first.ok,true);assert.equal(first.value.value.today_target,600);assert.equal(first.value.fresh,true);
 await app.send('seekProgress');assert.equal(requests,1);assert.equal(app.calls.length,0);
 offline=true;app.setTime('2026-09-23T01:01:01Z');
 const failed=await app.send('seekProgress');assert.equal(failed.value.fresh,false);assert.ok(failed.value.error);
 assert.equal(failed.value.value.today_target,600);assert.equal(app.data.lastResult.progress.today_target,200);
 app.setTime('2026-09-24T01:00:00Z');assert.equal((await app.send('seekProgress')).value.fresh,false);
});

test('unknown review backlog cannot take the first new collection slot of the day',async()=>{
 const tab={id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'},reviews=[];
 const app=loadBackground({runTab:tab,activeTab:tab,validJobs:true,
  reviewHandler:async options=>{reviews.push(options.allowNew);assert.equal(options.intervalMs,3600000);return options.allowNew;},
  run:{id:'priority',status:'running',tabId:22,page:9,pageUrl:tab.url,attemptedIds:[],accepted:141,duplicates:0,rejected:0,failed:0,lastSyncAt:'2026-09-22T01:00:00Z'},
  messages:{checkSeekPage:{ok:true},listSearchSeekJobs:{ok:true,cardCount:2,readableCardCount:2,jobs:[{id:'1',title:'Registered Nurse'},{id:'2',title:'Registered Nurse'}],pageUrl:tab.url},
   collectCurrentSeekPage:detailReply('1')}});
 await app.tick();await app.tick();assert.equal(app.data.continuousRun.accepted,142);assert.deepEqual(reviews,[false]);
 await app.tick();assert.deepEqual(reviews,[false,false,true]);
 assert.equal(app.created.length,1);assert.equal(app.calls.filter(x=>x.type==='collectOneSeekJob').length,0);
});

test('an unresponsive source reply is bounded without reinjecting or clicking again',async()=>{
 const tab={id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
 const app=loadBackground({runTab:tab,activeTab:tab,
  timer:(fn,ms)=>setTimeout(fn,ms===8000?0:ms),
  run:{id:'timeout',status:'running',tabId:22,page:9,pageUrl:tab.url,attemptedIds:[],accepted:141,duplicates:0,rejected:0,failed:0},
  messages:{checkSeekPage:()=>new Promise(()=>{})}});
 await app.tick();assert.equal(app.data.continuousRun.status,'waiting');
 assert.match(app.data.continuousRun.message,/响应超时/);assert.equal(app.calls.length,1);assert.equal(app.injections.length,0);
 assert.equal(app.data.continuousRun.accepted,141);assert.equal(app.data.continuousRun.page,9);
});

test('outside working hours makes no page requests and resumes next morning', async () => {
  const runTab = {id:22,url:'https://au.seek.com/Registered-Nurse-jobs?page=2',status:'complete'};
  const app = loadBackground({runTab,activeTab:runTab,
    run:{id:'schedule',status:'running',tabId:22,page:2,pageUrl:runTab.url,attemptedIds:[]},
    messages:{checkSeekPage:{ok:false,error:'人工验证'}}});
  app.setTime('2026-09-23T15:00:00Z');
  await app.tick();
  assert.equal(app.calls.length,0);
  assert.equal(app.data.continuousRun.waitUntil,Date.parse('2026-09-24T01:00:00Z'));
  app.setTime('2026-09-24T01:00:00Z');
  await app.tick();
  assert.equal(app.calls.length,1);
  assert.equal(app.data.continuousRun.status,'paused');
  assert.equal(app.data.continuousRun.page,2);
});

test('SEEK revisits IDs after 24 hours but skips recently uploaded IDs', async () => {
  const runTab = {id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
  const app = loadBackground({runTab,activeTab:runTab,validJobs:true,
    seenJobIds:{'1':'2026-09-22T00:00:00Z','2':'2026-09-23T00:30:00Z'},
    run:{id:'refresh',status:'running',tabId:22,page:1,pageUrl:runTab.url,attemptedIds:[],accepted:0,duplicates:0,rejected:0,failed:0},
    messages:{checkSeekPage:{ok:true},listSearchSeekJobs:{ok:true,cardCount:2,readableCardCount:2,pageUrl:runTab.url,
      jobs:[{id:'1',title:'Registered Nurse'},{id:'2',title:'Registered Nurse'}]},
      collectCurrentSeekPage:(_message,tab)=>detailReply(tab.url.split('/').at(-1))}});
  await app.tick();await app.tick();
  assert.equal(app.created.length,1);
  assert.equal(app.data.seenJobIds['1'],'2026-09-23T01:01:12.000Z');
  assert.equal(app.data.seenJobIds['2'],'2026-09-23T00:30:00Z');
  assert.equal(app.data.continuousRun.waitUntil,Date.parse('2026-09-23T01:31:12Z'));
});

test('hourly budget survives task state and releases in the next hour', async () => {
  const runTab = {id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
  const app = loadBackground({runTab,activeTab:runTab,
    run:{id:'limit',status:'running',tabId:22,page:1,pageUrl:runTab.url,attemptedIds:[]},
    messages:{checkSeekPage:{ok:false,error:'人工验证'}}});
  app.data.seekRate = {hour:Math.floor(Date.parse('2026-09-23T01:00:00Z')/3600000),count:50};
  await app.tick();
  assert.equal(app.calls.length,0);
  assert.equal(app.data.continuousRun.status,'waiting');
  app.setTime('2026-09-23T02:00:00Z');
  await app.tick();
  assert.equal(app.calls.length,1);
});

test('repeated start cannot bypass persisted 72 second spacing', async () => {
  const runTab = {id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
  const app = loadBackground({runTab,activeTab:runTab,
    run:{id:'spacing',status:'running',tabId:22,page:1,pageUrl:runTab.url,attemptedIds:[]},messages:{}});
  app.data.seekRate = {hour:Math.floor(Date.parse('2026-09-23T01:00:00Z')/3600000),count:1,
    nextAt:Date.parse('2026-09-23T01:01:12Z')};
  await app.send('startContinuous');
  assert.equal(app.calls.length,0);
  assert.equal(app.data.continuousRun.waitUntil,app.data.seekRate.nextAt);
});

test('automatic RN scope skips unrelated cards and advances pages without a click', async () => {
  const runTab = {id:22, url:'https://au.seek.com/Registered-Nurse-jobs?page=2', status:'complete'};
  const run = {id:'auto', status:'running', tabId:22, page:2, pageUrl:runTab.url,
    attemptedIds:[], accepted:0, duplicates:0, rejected:0, failed:0};
  const app = loadBackground({run, runTab, activeTab:runTab, validJobs:true, messages:{
    checkSeekPage:{ok:true},
    listSearchSeekJobs:() => ({ok:true, cardCount:2, readableCardCount:2,
      jobs:runTab.url.endsWith('page=2')
        ? [{id:'1', title:'Registered Nurse'}, {id:'2', title:'Clinical Assessor'}]
        : [{id:'3', title:'Enrolled Nurse'}],
      pageUrl:runTab.url, nextPageUrl:`https://au.seek.com/Registered-Nurse-jobs?page=${runTab.url.endsWith('page=2') ? 3 : 4}`}),
    collectCurrentSeekPage:(_message,tab) => detailReply(tab.url.split('/').at(-1))
  }});
  await app.tick();await app.tick();
  assert.equal(app.data.continuousRun.page, 3);
  await app.tick();
  assert.equal(app.data.continuousRun.page, 4);
  assert.equal(app.data.continuousRun.accepted, 1);

  assert.deepEqual([...app.data.continuousRun.attemptedIds], ['1']);
});

test('incomplete detail is bounded, reports failure and retries the same job automatically', async () => {
  const runTab = {id:22, url:'https://au.seek.com/Registered-Nurse-jobs?page=2', status:'complete'};
  const run = {id:'failure', status:'running', tabId:22, page:2, pageUrl:runTab.url,
    attemptedIds:[], accepted:0, duplicates:0, rejected:0, failed:0};
  const messages = {
    checkSeekPage:{ok:true},
    listSearchSeekJobs:{ok:true, cardCount:1, readableCardCount:1,
      jobs:[{id:'1',title:'Registered Nurse'}],nextPageUrl:'https://au.seek.com/Registered-Nurse-jobs?page=3'},
    collectCurrentSeekPage:{ok:false,error:'详情未完整加载'}
  };
  const app = loadBackground({run, runTab, activeTab:runTab, messages, validJobs:true});
  await app.tick();
  assert.equal(app.data.continuousRun.status,'running');
  app.setTime('2026-09-23T01:01:31Z');await app.tick();
  assert.equal(app.data.continuousRun.status, 'waiting');
  assert.equal(app.data.continuousRun.page, 2);
  assert.equal(app.data.continuousRun.attemptedIds.length, 0);
  messages.collectCurrentSeekPage = detailReply('1');
  await app.tick();
  assert.equal(app.reloads.length,0);
  await app.tick();
  assert.equal(app.reloads.length,1);
  await app.tick();
  assert.equal(app.data.continuousRun.accepted,1);
});

test('blank SEEK page refreshes after backoff while verification stays paused', async () => {
  const runTab = {id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
  const messages = {checkSeekPage:{ok:false,error:'页面暂时空白'}};
  const run = {id:'blank',status:'running',tabId:22,page:1,pageUrl:runTab.url,
    attemptedIds:[],accepted:0,duplicates:0,rejected:0,failed:0};
  const app = loadBackground({run,runTab,activeTab:runTab,messages});
  await app.tick();
  assert.equal(app.data.continuousRun.status,'waiting');
  messages.checkSeekPage={ok:false,error:'页面要求人工验证'};
  await app.tick();await app.tick();
  assert.equal(app.data.continuousRun.status,'paused');
  assert.equal(app.reloads.length,0);
});

test('page batch button collects from the active continuous SEEK tab and updates its counters', async () => {
  const runTab = {id:22, url:'https://au.seek.com/Registered-Nurse-jobs?page=2', status:'complete'};
  const run = {id:'r1', status:'running', tabId:22, page:2, pageUrl:runTab.url,
    attemptedIds:[], accepted:0, duplicates:0, rejected:0, failed:0};
  const app = loadBackground({run, runTab,
    activeTab:{id:11, url:'https://au.seek.com/'},
    messages:{
      listSearchSeekJobs:{ok:true, cardCount:32, readableCardCount:32, jobs:[{id:'94821179'}]},
      collectVisibleSeekJobs:{ok:true, jobs:[{source_job_id:'94821179'}], attempted:1,
        failures:[], pageUrl:runTab.url}
    }});
  const response = await app.send('collectVisibleAndUpload');
  assert.equal(response.ok, true);
  assert.equal(response.value.attempted, 1);
  assert.deepEqual(app.calls.map(call => call.id), [22, 22]);
  assert.equal(app.data.continuousRun.rejected, 1);
  assert.deepEqual([...app.data.continuousRun.attemptedIds], ['94821179']);
});

test('continuous task advances immediately after the last page two job', async () => {
  const runTab = {id:22, url:'https://au.seek.com/Registered-Nurse-jobs?page=2', status:'complete'};
  const run = {id:'r2', status:'running', tabId:22, page:2, pageUrl:runTab.url,
    attemptedIds:[], accepted:0, duplicates:0, rejected:0, failed:0};
  const app = loadBackground({run, runTab, activeTab:runTab, messages:{
    checkSeekPage:{ok:true},
    listSearchSeekJobs:{ok:true, cardCount:32, readableCardCount:32,
      jobs:[{id:'94821179', title:'Registered Nurse'}],
      nextPageUrl:'https://au.seek.com/Registered-Nurse-jobs?page=3'},
    collectCurrentSeekPage:detailReply('94821179')
  }});
  assert.equal((await app.send('startContinuous')).ok, true);
  app.setTime('2026-09-23T01:00:10Z');await app.tick();
  assert.deepEqual([...app.data.continuousRun.attemptedIds], ['94821179']);
  assert.equal(app.data.continuousRun.page, 3);
  assert.equal(runTab.url, 'https://au.seek.com/Registered-Nurse-jobs?page=3');
  assert.match(app.data.continuousRun.message, /本页 1\/1 条已处理/);
});

test('continuous task finishes all matching jobs before advancing', async () => {
  const runTab = {id:22, url:'https://au.seek.com/Registered-Nurse-jobs?page=2', status:'complete'};
  const run = {id:'r4', status:'running', tabId:22, page:2, pageUrl:runTab.url,
    attemptedIds:[], accepted:0, duplicates:0, rejected:0, failed:0};
  const app = loadBackground({run, runTab, activeTab:runTab, messages:{
    checkSeekPage:{ok:true},
    listSearchSeekJobs:{ok:true, cardCount:32, readableCardCount:32,
      jobs:[{id:'94821179', title:'Registered Nurse'}, {id:'94820855', title:'Registered Nurse'}],
      nextPageUrl:'https://au.seek.com/Registered-Nurse-jobs?page=3'},
    collectCurrentSeekPage:detailReply('94821179')
  }});
  assert.equal((await app.send('startContinuous')).ok, true);
  app.setTime('2026-09-23T01:00:10Z');await app.tick();
  assert.equal(app.data.continuousRun.page, 2);
  assert.equal(app.data.continuousRun.pageProcessed, 1);
  assert.equal(app.data.continuousRun.pageMatched, 2);
});

test('continuous task pauses on verification before moving the tab', async () => {
  const runTab = {id:22, url:'https://au.seek.com/Registered-Nurse-jobs?page=2', status:'complete'};
  const run = {id:'r3', status:'running', tabId:22, page:2,
    pageUrl:'https://au.seek.com/Registered-Nurse-jobs?page=3',
    attemptedIds:[], accepted:0, duplicates:0, rejected:0, failed:0};
  const app = loadBackground({run, runTab, activeTab:runTab,
    messages:{checkSeekPage:{ok:false, error:'页面要求人工验证'}}});
  assert.equal((await app.send('startContinuous')).ok, true);
  assert.equal(app.data.continuousRun.status, 'paused');
  assert.equal(runTab.url, 'https://au.seek.com/Registered-Nurse-jobs?page=2');
});

test('detail checkpoint survives restart and does not reserve another visit during dwell',async()=>{
 const source={id:22,url:'https://au.seek.com/Registered-Nurse-jobs?page=9',status:'complete'};
 const messages={checkSeekPage:{ok:true},listSearchSeekJobs:{ok:true,cardCount:2,readableCardCount:2,
  jobs:[{id:'1',title:'Registered Nurse'},{id:'2',title:'Registered Nurse'}],pageUrl:source.url},collectCurrentSeekPage:detailReply('1')};
 const first=loadBackground({runTab:source,activeTab:source,validJobs:true,messages,
  run:{id:'restart',status:'running',tabId:22,page:9,pageUrl:source.url,attemptedIds:[],accepted:141}});
 await first.step();assert.equal(first.data.seekRate.count,1);assert.equal(first.data.continuousRun.accepted,141);
 assert.equal(first.created.length,1);assert.equal(source.url,'https://au.seek.com/Registered-Nurse-jobs?page=9');
 const next=loadBackground({runTab:source,activeTab:source,validJobs:true,messages,
  stored:structuredClone(first.data),openTabs:first.created});
 next.setTime('2026-09-23T01:00:09Z');await next.step();assert.equal(next.calls.length,0);
 assert.equal(next.data.continuousRun.accepted,141);
 next.setTime('2026-09-23T01:00:10Z');await next.step();
 assert.equal(next.data.continuousRun.accepted,142);assert.equal(next.data.seekRate.count,1);
 assert.equal(next.created.length,0);assert.deepEqual(next.removed,[1000]);assert.equal(next.data.continuousRun.page,9);
 assert.equal(next.data.continuousRun.pendingDetail,null);assert.equal(next.data.continuousRun.pendingUpload,null);
});

test('detail challenge pauses without closing the page or altering saved counts',async()=>{
 const tab={id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
 const app=loadBackground({runTab:tab,activeTab:tab,messages:{checkSeekPage:{ok:true},listSearchSeekJobs:{ok:true,
  cardCount:1,readableCardCount:1,jobs:[{id:'1',title:'Registered Nurse'}]},collectCurrentSeekPage:{ok:false,error:'Cloudflare 安全验证'}},
  run:{id:'challenge',status:'running',tabId:22,page:9,pageUrl:tab.url,attemptedIds:[],accepted:141}});
 await app.step();assert.equal(app.data.continuousRun.status,'paused');assert.equal(app.removed.length,0);
 assert.equal(app.data.continuousRun.pendingDetail.tabId,1000);assert.equal(app.data.continuousRun.accepted,141);
 const calls=app.calls.length;await app.step();assert.equal(app.calls.length,calls);assert.equal(app.data.seekRate.count,1);
});

test('wrong detail identity cannot upload and two failed reads preserve a report then move on',async()=>{
 const tab={id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
 let uploads=0;
 const app=loadBackground({runTab:tab,activeTab:tab,validJobs:true,messages:{checkSeekPage:{ok:true},listSearchSeekJobs:{ok:true,
  cardCount:1,readableCardCount:1,jobs:[{id:'1',title:'Registered Nurse'}]},collectCurrentSeekPage:detailReply('999')},
  run:{id:'wrong',status:'running',tabId:22,page:9,pageUrl:tab.url,attemptedIds:[],accepted:141},fetcher:async()=>{uploads++;throw Error('must not upload');}});
 await app.step();app.setTime('2026-09-23T01:01:31Z');await app.step();
 assert.equal(app.data.seekDetailFailures['1'].attempts,1);assert.equal(app.data.continuousRun.attemptedIds.length,0);
 app.setTime('2026-09-23T01:03:32Z');await app.step();
 app.setTime('2026-09-23T01:05:03Z');await app.step();
 assert.equal(uploads,0);assert.equal(app.data.seekDetailFailures['1'].attempts,2);
 assert.deepEqual([...app.data.continuousRun.attemptedIds],['1']);assert.equal(app.data.continuousRun.page,9);
 assert.equal(app.data.continuousRun.status,'running');assert.equal(app.data.continuousRun.accepted,141);
 assert.equal(app.data.seekRate.count,2);assert.equal(app.removed.length,2);
});

test('manual pause during a detail reply survives and prevents upload',async()=>{
 const tab={id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};let app,uploads=0;
 app=loadBackground({runTab:tab,activeTab:tab,messages:{checkSeekPage:{ok:true},listSearchSeekJobs:{ok:true,
  cardCount:1,readableCardCount:1,jobs:[{id:'1',title:'Registered Nurse'}]},collectCurrentSeekPage:()=>{
   app.data.continuousRun.status='paused';app.data.continuousRun.message='已手动暂停';return detailReply('1');}},
  run:{id:'pause',status:'running',tabId:22,page:9,pageUrl:tab.url,attemptedIds:[],accepted:141},fetcher:async()=>{uploads++;}});
 await app.step();assert.equal(app.data.continuousRun.status,'paused');assert.equal(uploads,0);
 assert.equal(app.data.continuousRun.accepted,141);assert.ok(app.data.continuousRun.pendingDetail);
});

test('overlapping alarm ticks cannot open a second detail or consume another reservation',async()=>{
 const tab={id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
 let release,entered;const waiting=new Promise(resolve=>{entered=resolve;});
 const app=loadBackground({runTab:tab,activeTab:tab,messages:{checkSeekPage:{ok:true},listSearchSeekJobs:{ok:true,
  cardCount:1,readableCardCount:1,jobs:[{id:'1',title:'Registered Nurse'}]},collectCurrentSeekPage:()=>{
   entered();return new Promise(resolve=>{release=()=>resolve(detailReply('1'));});}},
  run:{id:'overlap',status:'running',tabId:22,page:9,pageUrl:tab.url,attemptedIds:[],accepted:141}});
 const first=app.step();await waiting;await app.step();
 assert.equal(app.created.length,1);assert.equal(app.data.seekRate.count,1);
 assert.equal(app.calls.filter(call=>call.type==='collectCurrentSeekPage').length,1);
 release();await first;assert.equal(app.data.continuousRun.accepted,141);assert.ok(app.data.continuousRun.pendingDetail.readyAt);
});

test('a newly created detail with pendingUrl waits for navigation rather than pausing',async()=>{
 const tab={id:22,url:'https://au.seek.com/Registered-Nurse-jobs',status:'complete'};
 const app=loadBackground({runTab:tab,activeTab:tab,createPending:true,validJobs:true,
  messages:{checkSeekPage:{ok:true},listSearchSeekJobs:{ok:true,cardCount:1,readableCardCount:1,
   jobs:[{id:'1',title:'Registered Nurse'}]},collectCurrentSeekPage:detailReply('1')},
  run:{id:'pending-url',status:'running',tabId:22,page:9,pageUrl:tab.url,attemptedIds:[],accepted:141}});
 await app.step();assert.equal(app.data.continuousRun.status,'running');assert.match(app.data.continuousRun.message,/正在加载/);
 assert.equal(app.calls.filter(call=>call.type==='collectCurrentSeekPage').length,0);
 Object.assign(app.created[0],{url:app.created[0].pendingUrl,status:'complete'});
 app.setTime('2026-09-23T01:00:05Z');await app.step();
 assert.equal(app.data.continuousRun.accepted,141);
 app.setTime('2026-09-23T01:00:15Z');await app.step();
 assert.equal(app.data.continuousRun.accepted,142);assert.equal(app.data.seekRate.count,1);assert.equal(app.created.length,1);
});
