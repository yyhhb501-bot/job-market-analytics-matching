const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const crypto=require('node:crypto').webcrypto;
function setup(data={},fetcher=async()=>({ok:true,json:async()=>({received_count:1,accepted_count:1,duplicate_count:0,rejected_count:0})})) {
  const alarms=new Map();
  const context=vm.createContext({crypto,TextEncoder,AbortSignal,Date,URL,Promise,
    fetch:fetcher,chrome:{storage:{local:{get:async key=>({[key]:structuredClone(data[key])}),
      set:async value=>Object.assign(data,structuredClone(value))}},
      alarms:{create:async(k,v)=>alarms.set(k,v),clear:async k=>alarms.delete(k),onAlarm:{addListener(){}}}}});
  vm.runInContext(fs.readFileSync(__dirname+'/sync.js','utf8'),context);
  return {sync:context.LinkedInSync,data,alarms};
}
const run=(text='Full job description')=>({config:{location:'usa'},jobs:{'123':{
  source_job_id:'123',title:'Project Manager',company:'Example',description:text,
  collected_at:'2026-10-19T02:00:00Z',canonical_url:'https://www.linkedin.com/jobs/view/123/'}}});
const config={apiUrl:'http://localhost:8010',deviceToken:'jagg_test_device'};
test('existing jobs are uploaded directly and only a confirmed API receipt is acknowledged',async()=>{
  const sent=[];const h=setup({},async(url,options)=>{sent.push(JSON.parse(options.body));
    return {ok:true,json:async()=>({received_count:1,accepted_count:1,duplicate_count:0,rejected_count:0})};});
  await h.sync.configure(config);await h.sync.capture(run());
  assert.equal((await h.sync.summary()).pendingSync,1);
  await h.sync.flush();assert.equal((await h.sync.summary()).pendingSync,0);
  assert.equal((await h.sync.summary()).synced,1);assert.equal(sent[0].jobs[0].country,'US');
});
test('network failure survives service worker restart and reuses the same idempotency key',async()=>{
  let key;const h=setup({},async(_url,options)=>{key=options.headers['Idempotency-Key'];throw Error('offline');});
  await h.sync.configure(config);await h.sync.capture(run());await h.sync.flush();
  assert.equal((await h.sync.summary()).pendingSync,1);
  h.data.linkedinOutbox.items['123'].retryAt=0;
  const recovered=setup(h.data,async(_url,options)=>{
    assert.equal(options.headers['Idempotency-Key'],key);
    return {ok:true,json:async()=>({received_count:1,accepted_count:0,duplicate_count:1,rejected_count:0})};});
  await recovered.sync.flush();assert.equal((await recovered.sync.summary()).pendingSync,0);
});
test('server rejection or an incomplete receipt cannot turn into a successful sync',async()=>{
  for(const receipt of [{received_count:1,accepted_count:0,duplicate_count:0,rejected_count:1},{accepted_count:1}]) {
    const h=setup({},async()=>({ok:true,json:async()=>receipt}));
    await h.sync.configure(config);await h.sync.capture(run());await h.sync.flush();
    const summary=await h.sync.summary();assert.equal(summary.synced,0);assert.equal(summary.pendingSync,1);
    assert.equal(summary.rejectedSync,1);assert.equal(h.data.linkedinOutbox.items['123'].job.title,'Project Manager');
  }
});
test('a job changed during an inflight upload remains pending with its newer revision',async()=>{
  let release,started;const start=new Promise(resolve=>started=resolve);
  const h=setup({},async()=>{started();await new Promise(resolve=>release=resolve);
    return {ok:true,json:async()=>({received_count:1,accepted_count:1,duplicate_count:0,rejected_count:0})};});
  await h.sync.configure(config);await h.sync.capture(run('first'));
  const flushing=h.sync.flush();await start;await h.sync.capture(run('updated'));release();await flushing;
  assert.equal((await h.sync.summary()).pendingSync,1);
  assert.equal(h.data.linkedinOutbox.items['123'].job.description,'updated');
});
test('invalid device authorization stops retrying until a new connection is configured',async()=>{
  let calls=0;const h=setup({},async()=>{calls++;return {ok:false,status:401};});
  await h.sync.configure(config);await h.sync.capture(run());await h.sync.flush();await h.sync.flush();
  assert.equal(calls,1);assert.equal((await h.sync.summary()).needsSetup,true);
  assert.ok(!JSON.stringify(await h.sync.summary()).includes(config.deviceToken));
});
