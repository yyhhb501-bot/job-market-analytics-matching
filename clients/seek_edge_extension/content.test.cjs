const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const C = require('./core.js');

test('lists all homepage recommendations without a nurse title filter', () => {
  const links = [
    {href:'https://au.seek.com/job/94758895', getAttribute: () => 'Registered Nurse'},
    {href:'https://au.seek.com/job/94816938', getAttribute: () => 'Casual Cleaner'},
    {href:'https://au.seek.com/job/94758895', getAttribute: () => 'Registered Nurse'},
    {href:'https://evil.example/job/12345678', getAttribute: () => 'Registered Nurse'}
  ];
  let listener;
  const context = {
    globalThis: {SeekCollector: C},
    location: {pathname:'/', href:'https://au.seek.com/'},
    document: {
      title:'SEEK', body:{innerText:'Recommended'},
      querySelectorAll: selector => selector === 'a[data-automation^="recommendedJobLink_"]' ? links : []
    },
    chrome: {runtime:{onMessage:{addListener: fn => {listener = fn;}}}}
  };
  vm.runInNewContext(fs.readFileSync(require.resolve('./content.js'), 'utf8'), context);
  let response;
  listener({type:'listRecommendedSeekJobs'}, null, value => {response = value;});
  assert.equal(response.ok, true);
  assert.equal(response.jobs.length, 2);
  assert.equal(response.jobs[0].url, 'https://au.seek.com/job/94758895');
});

test('reads real title links after empty overlay links and queues every search card', () => {
  const card = (id, title) => ({querySelector: selector => ({
    href:`https://au.seek.com/job/${id}`,
    innerText:selector === 'a[data-automation="jobTitle"]' ? title : ''
  })});
  const next = {href:'https://au.seek.com/Registered-Nurse-jobs?page=2',
    getAttribute: name => name === 'aria-label' ? 'Next' : null};
  let listener;
  const context = {
    globalThis: {SeekCollector:C},
    location: {pathname:'/Registered-Nurse-jobs', href:'https://au.seek.com/Registered-Nurse-jobs'},
    document: {title:'SEEK', body:{innerText:'Search results'},
      querySelectorAll: selector => selector === 'article[data-automation="normalJob"]'
        ? [card('12345678', 'Registered Nurse'), card('87654321', 'Casual Cleaner')]
        : selector === 'a[href]' ? [next] : []},
    chrome: {runtime:{onMessage:{addListener: fn => {listener = fn;}}}}
  };
  vm.runInNewContext(fs.readFileSync(require.resolve('./content.js'), 'utf8'), context);
  let response;
  listener({type:'listSearchSeekJobs'}, null, value => {response = value;});
  assert.equal(response.ok, true);
  assert.equal(response.jobs.length, 2);
  assert.equal(response.jobs[0].id, '12345678');
  assert.equal(response.jobs[0].title, 'Registered Nurse');
  assert.equal(response.jobs[1].title, 'Casual Cleaner');
  assert.equal(response.readableCardCount, 2);
  assert.equal(response.nextPageUrl, next.href);
});

test('reports search cards whose titles have not loaded yet', () => {
  let listener;
  const context = {globalThis:{SeekCollector:C},
    location:{pathname:'/Registered-Nurse-jobs',href:'https://au.seek.com/Registered-Nurse-jobs'},
    document:{title:'SEEK',body:{innerText:'Search results'},
      querySelectorAll: selector => selector === 'article[data-automation="normalJob"]'
        ? [{querySelector:()=>null}] : []},
    chrome:{runtime:{onMessage:{addListener:fn=>{listener=fn;}}}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('./content.js'), 'utf8'), context);
  let response;
  listener({type:'listSearchSeekJobs'}, null, value => {response=value;});
  assert.equal(response.cardCount, 1);
  assert.equal(response.readableCardCount, 0);
  assert.equal(response.jobs.length, 0);
});

test('pauses on a visible challenge before listing jobs', () => {
  let listener;
  const context = {globalThis:{SeekCollector:C},
    location:{pathname:'/Registered-Nurse-jobs',href:'https://au.seek.com/Registered-Nurse-jobs'},
    document:{title:'Security check',body:{innerText:'Verify you are human with CAPTCHA'}},
    chrome:{runtime:{onMessage:{addListener:fn=>{listener=fn;}}}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('./content.js'), 'utf8'), context);
  let response;
  listener({type:'listSearchSeekJobs'}, null, value => {response=value;});
  assert.equal(response.ok, false);
  assert.match(response.error, /暂停/);
});

test('continuous collection keeps a complete job detail open for at least ten seconds', async () => {
  let clock = 0;
  let listener;
  const location = {pathname:'/Registered-Nurse-jobs',
    href:'https://au.seek.com/Registered-Nurse-jobs?page=2'};
  const link = {href:'https://au.seek.com/job/94821179', innerText:'Registered Nurse',
    click:() => {location.href += '&jobId=94821179';}};
  const card = {getAttribute:() => '94821179', querySelector:() => link, scrollIntoView() {}};
  const fakeCollector = {...C, parseDetail:() => ({source_job_id:'94821179',
    title:'Registered Nurse', description:'x'.repeat(150)})};
  const context = {globalThis:{SeekCollector:fakeCollector}, location,
    document:{title:'SEEK', body:{innerText:'Search results'},
      querySelectorAll:selector => selector === 'article[data-automation="normalJob"]' ? [card] : []},
    Date:{now:() => clock},
    setTimeout:(fn, ms) => {clock += ms; setImmediate(fn);},
    chrome:{runtime:{onMessage:{addListener:fn=>{listener=fn;}}}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('./content.js'), 'utf8'), context);
  const response = await new Promise(resolve => listener({type:'collectOneSeekJob', id:'94821179'}, null, resolve));
  assert.equal(response.ok, true);
  assert.ok(clock >= 10500, `detail was visible for only ${clock - 500} ms`);
});

test('a delayed background timer still reads the now-ready correct job and retains the dwell',async()=>{
 let clock=0,listener;const location={pathname:'/Registered-Nurse-jobs',href:'https://au.seek.com/Registered-Nurse-jobs'};
 const link={href:'https://au.seek.com/job/94821179',innerText:'Registered Nurse',click:()=>{location.href+='?jobId=94821179';}};
 const card={querySelector:()=>link,scrollIntoView(){}};
 const context={globalThis:{SeekCollector:{...C,parseDetail:()=>({source_job_id:'94821179',title:'Registered Nurse',description:'x'.repeat(150)})}},
  location,Date:{now:()=>clock},setTimeout:(fn)=>{clock+=60000;setImmediate(fn);},
  document:{title:'SEEK',body:{innerText:'Search results'},querySelectorAll:s=>s==='article[data-automation="normalJob"]'?[card]:[]},
  chrome:{runtime:{onMessage:{addListener:fn=>{listener=fn;}}}}};
 vm.runInNewContext(fs.readFileSync(require.resolve('./content.js'),'utf8'),context);
 const result=await new Promise(resolve=>listener({type:'collectOneSeekJob',id:'94821179'},null,resolve));
 assert.equal(result.ok,true);assert.ok(clock>=70000);
});

test('missing extension runtime neither throws nor blocks a later valid reinjection',()=>{
 const source=fs.readFileSync(require.resolve('./content.js'),'utf8');
 for(const chromeValue of [undefined,{}, {runtime:{}}]) {
  let registered=0;
  const context=vm.createContext({globalThis:{SeekCollector:C},chrome:chromeValue});
  assert.doesNotThrow(()=>vm.runInContext(source,context));
  assert.equal(context.globalThis.__seekCurrentPageCollector,undefined);
  context.chrome={runtime:{onMessage:{addListener:()=>{registered++;}}}};
  vm.runInContext(source,context);vm.runInContext(source,context);
  assert.equal(registered,1);assert.equal(context.globalThis.__seekCurrentPageCollector,true);
 }
});

test('an incomplete core does not set the injection guard or register a broken collector',()=>{
 let registered=0;const context=vm.createContext({globalThis:{},chrome:{runtime:{onMessage:{addListener:()=>{registered++;}}}}});
 vm.runInContext(fs.readFileSync(require.resolve('./content.js'),'utf8'),context);
 assert.equal(registered,0);assert.equal(context.globalThis.__seekCurrentPageCollector,undefined);
});
