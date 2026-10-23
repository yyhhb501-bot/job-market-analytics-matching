const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const L=require('./lifecycle.js');

test('review queue orders oldest due IDs and retries uncertainty after two hours',()=>{
  const now=Date.parse('2026-09-24T02:00:00Z');
  const candidates=[{id:'1',seen:'2026-09-23T00:00:00Z'}, {id:'2',seen:'2026-09-24T01:00:00Z'}];
  assert.equal(L.due(candidates,{},now).id,'1');
  assert.equal(L.due(candidates,{'1':{status:'active',checked_at:'2026-09-24T01:00:00Z'}},now),undefined);
  assert.equal(L.due(candidates,{'1':{status:'unknown',checked_at:'2026-09-24T00:00:00Z'}},now).id,'1');
});

async function inspect({header='',description='',path='/jobs/view/123/',body='',apply=false,roleOnly=false,source='linkedin_user_import'}={}) {
  const details={innerText:description};
  const main={innerText:header+'\n'+description, querySelector:selector=>
    selector.includes('top-card')?null:selector.includes('apply')?(apply?{getAttribute:()=>null}:null):{innerText:'Data Analyst'}};
  let waited=0;
  const context=vm.createContext({location:{pathname:path,hostname:source==='seek_user_import'?'au.seek.com':'www.linkedin.com'},document:{title:'Job',body:{innerText:body},
    querySelector:selector=>selector==='main'?(roleOnly?null:main):selector==='[role="main"]'?main:details},setTimeout:fn=>{waited+=10000;fn();},Promise,globalThis:{}});
  const fn=vm.runInContext(`(${L.inspectPage.toString()})`,context);
  const result=await fn(source,'123');
  assert.equal(waited,10000);
  return result;
}
test('explicit original-page closure, active evidence, and uncertainty are distinct',async()=>{
  assert.equal((await inspect({header:'No longer accepting applications'})).status,'closed');
  assert.equal((await inspect({header:'Data Analyst',description:'No longer accepting applications '.repeat(8)})).status,'unknown');
  assert.equal((await inspect({header:'Data Analyst',description:'Full details '.repeat(20),apply:true})).status,'active');
  assert.equal((await inspect({header:'No longer accepting applications',path:'/jobs/'})).status,'unknown');
  assert.equal((await inspect({body:'captcha',header:'No longer accepting applications'})).blocked,true);
  assert.equal((await inspect({roleOnly:true,header:'Data Analyst',description:'Full details '.repeat(20),apply:true})).status,'active');
  assert.equal((await inspect({roleOnly:true,source:'seek_user_import',path:'/job/123',header:'Registered Nurse',description:'Full details '.repeat(20),apply:true})).status,'active');
});
test('both standalone extensions ship identical review logic',()=>{
  assert.equal(fs.readFileSync(__dirname+'/lifecycle.js','utf8'),fs.readFileSync(__dirname+'/../linkedin_edge_extension/lifecycle.js','utf8'));
});

test('failed delivery persists an observation and quota denial never opens a tab',async()=>{
  const data={};let opens=0,delivered=0;
  const chrome={storage:{local:{get:async key=>({[key]:structuredClone(data[key])}),set:async value=>Object.assign(data,structuredClone(value))}},
    tabs:{create:async()=>{opens++;return {id:1};},get:async()=>({status:'complete'}),remove:async()=>{}},
    scripting:{executeScript:async()=>[{result:{status:'closed',evidence:'job has closed'}}]}};
  const context=vm.createContext({chrome,Date,Promise,setTimeout,clearTimeout,globalThis:{}});
  vm.runInContext(fs.readFileSync(__dirname+'/lifecycle.js','utf8'),context);
  const options={source:'seek_user_import',candidates:async()=>[{id:'123',seen:'2020-01-01'}],
    reserve:async()=>false,pause:async()=>{},deliver:async()=>{throw Error('offline');}};
  assert.equal(await context.globalThis.JobLifecycle.run(options),false);assert.equal(opens,0);
  options.reserve=async()=>true;
  assert.equal(await context.globalThis.JobLifecycle.run(options),true);
  assert.equal(data.lifecycleReview.pending.status,'closed');
  assert.ok(data.lifecycleReview.syncRetryAt>Date.now());
  assert.equal(await context.globalThis.JobLifecycle.run(options),false);
  assert.equal(opens,1);
  data.lifecycleReview.syncRetryAt=0;
  options.deliver=async()=>{delivered++;};
  await context.globalThis.JobLifecycle.run(options);
  assert.equal(delivered,1);assert.equal(opens,1);
  assert.equal(data.lifecycleReview.pending,null);
});

test('saved observations can synchronize without reserving or opening a new review page',async()=>{
 const data={lifecycleReview:{reviews:{},pending:{source_job_id:'123',status:'unknown'}}};let opened=0,delivered=0;
 const chrome={storage:{local:{get:async key=>({[key]:structuredClone(data[key])}),set:async value=>Object.assign(data,structuredClone(value))}},
  tabs:{create:async()=>{opened++;return{id:1};}}};
 const context=vm.createContext({chrome,Date,Promise,setTimeout,clearTimeout,globalThis:{}});
 vm.runInContext(fs.readFileSync(__dirname+'/lifecycle.js','utf8'),context);
 assert.equal(await context.globalThis.JobLifecycle.run({allowNew:false,deliver:async()=>{delivered++;},reserve:async()=>{throw Error('must not reserve');}}),false);
 assert.equal(opened,0);assert.equal(delivered,1);assert.equal(data.lifecycleReview.pending,null);
});

test('review inspection cannot hang forever and hourly spacing preserves unknown evidence',async()=>{
 const data={};let removed=0;
 const chrome={storage:{local:{get:async key=>({[key]:structuredClone(data[key])}),set:async value=>Object.assign(data,structuredClone(value))}},
  tabs:{create:async()=>({id:1}),get:async()=>({status:'complete'}),remove:async()=>{removed++;}},
  scripting:{executeScript:()=>new Promise(()=>{})}};
 const context=vm.createContext({chrome,Date,Promise,globalThis:{},clearTimeout:()=>{},
  setTimeout:(fn,ms)=>{assert.equal(ms,90000);queueMicrotask(fn);return 1;}});
 vm.runInContext(fs.readFileSync(__dirname+'/lifecycle.js','utf8'),context);
 const before=Date.now();await context.globalThis.JobLifecycle.run({source:'seek_user_import',intervalMs:3600000,
  candidates:async()=>[{id:'123',seen:'2020-01-01'}],reserve:async()=>true,pause:async()=>{throw Error('no invented restriction');},deliver:async()=>{}});
 assert.equal(removed,1);assert.equal(data.lifecycleReview.reviews['123'].status,'unknown');
 assert.ok(data.lifecycleReview.nextAt>=before+3600000);
});
