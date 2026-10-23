// Disposable browser/profile, fixture pages and a fake upload response only.
const {chromium}=require('@playwright/test');
const {mkdtemp,rm}=require('node:fs/promises');
const {tmpdir}=require('node:os');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
  const profile=await mkdtemp(path.join(tmpdir(),'jobagg-seek-detail-test-'));
  const extension=path.resolve(__dirname,'../../../clients/seek_edge_extension');
  let context;
  try {
    context=await chromium.launchPersistentContext(profile,{channel:'chromium',headless:true,
      args:['--disable-extensions-except='+extension,'--load-extension='+extension,'--host-resolver-rules=MAP au.seek.com ~NOTFOUND']});
    const search='https://au.seek.com/Registered-Nurse-jobs?page=9';
    await context.route('https://au.seek.com/**',route=>route.fulfill({contentType:'text/html',body:
      route.request().url().includes('/job/')?`<!doctype html><title>Registered Nurse</title>
        <main data-automation="job-detail"><h1 data-automation="job-detail-title">Registered Nurse</h1>
        <div data-automation="advertiser-name">Fixture Hospital</div>
        <div data-automation="job-detail-location">Sydney NSW</div>
        <div data-automation="job-detail-work-type">Full time</div><span>Posted 1 hour ago</span>
        <div data-automation="jobAdDetails">${'Provide patient care and clinical assessment, registration and nursing experience required. '.repeat(6)}</div></main>`:
        `<!doctype html><title>Registered Nurse jobs</title><main>
        <article data-automation="normalJob"><a data-automation="jobTitle" href="/job/12345678">Registered Nurse</a></article>
        <article data-automation="normalJob"><a data-automation="jobTitle" href="/job/12345679">Registered Nurse</a></article></main>`}));
    const source=await context.newPage();await source.goto(search);
    // Native extension-created navigations cannot reliably be intercepted before
    // their first request. Supply an already-routed detail tab as the creation
    // fixture; all parsing, dwell, persistence, cleanup and upload logic is real.
    const detail=await context.newPage();await detail.goto('https://au.seek.com/job/12345678');
    const worker=context.serviceWorkers()[0] || await context.waitForEvent('serviceworker');
    await worker.evaluate(async search=>{
      globalThis.__fixtureUploads=[];
      globalThis.__fixtureCreated=[];
      const [detail]=await chrome.tabs.query({url:'https://au.seek.com/job/12345678'});
      chrome.tabs.create=async options=>{
        if(options.url!==detail.url) throw Error('Unexpected fixture detail');
        globalThis.__fixtureCreated.push(options);return detail;
      };
      globalThis.fetch=async(url,options)=>{
        if(url!=='http://localhost:18010/api/v1/import/jobs') throw Error('Unexpected fixture request');
        globalThis.__fixtureUploads.push(JSON.parse(options.body));
        return {ok:true,status:200,json:async()=>({received_count:1,accepted_count:1,duplicate_count:0,rejected_count:0})};
      };
      const original=SeekSchedule.window;
      SeekSchedule.window=(now=Date.now())=>({...original(now),active:true});
      const [tab]=await chrome.tabs.query({url:search});
      await chrome.storage.local.set({apiUrl:'http://localhost:18010',deviceToken:'fixture-only',
        continuousRun:{id:'fixture-detail',status:'running',tabId:tab.id,page:9,pageUrl:search,
          attemptedIds:[],accepted:141,duplicates:0,rejected:0,failed:0}});
    },search);
    const deadline=Date.now()+30000;
    let observed;
    while(Date.now()<deadline) {
      await worker.evaluate(()=>continuousTick());
      observed=await worker.evaluate(async()=>({...await chrome.storage.local.get(['continuousRun','seekRate']),uploads:globalThis.__fixtureUploads}));
      assert.notEqual(observed.continuousRun.status,'paused',observed.continuousRun.message);
      if(observed.continuousRun.accepted===142) break;
      if(observed.continuousRun.pendingDetail?.readyAt) assert.equal(observed.uploads.length,0);
      await new Promise(resolve=>setTimeout(resolve,250));
    }
    assert.equal(observed.continuousRun.accepted,142,JSON.stringify(observed.continuousRun));
    assert.equal(observed.uploads.length,1);assert.equal(observed.seekRate.count,1);
    const job=observed.uploads[0].jobs[0];
    assert.equal(job.source_job_id,'12345678');assert.equal(job.company,'Fixture Hospital');
    assert.ok(job.description.length>120);assert.ok(job.posted_at);assert.equal(source.url(),search);
    assert.equal(observed.continuousRun.page,9);assert.equal(observed.continuousRun.pendingDetail,null);
    console.log('SEEK full detail: real content parsing, persisted dwell, one reserved access and one fixture upload passed');
  } finally {
    if(context) await context.close();
    assert.equal(path.dirname(path.resolve(profile)),path.resolve(tmpdir()));
    assert.ok(path.basename(profile).startsWith('jobagg-seek-detail-test-'));
    await rm(profile,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
