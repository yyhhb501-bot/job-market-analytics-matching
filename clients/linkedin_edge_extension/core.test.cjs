const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require('./core.js');
test('country scope keeps US occupations and only Registered Nurse queries in Australia',()=>{
 const c=C.config(require('./presets.js').PRESETS['all-occupations-backfill']);
 const queue=C.buildQueue(c),au=queue.filter(q=>q.country==='AU'),us=queue.filter(q=>q.country==='US');
 assert.ok(au.length>0);assert.ok(us.length>20);
 assert.ok(au.every(q=>q.keyword==='Registered Nurse'));
 assert.ok(new Set(us.map(q=>q.occupationId)).size>10);
 for(const title of ['Registered Nurse - ICU','RN / Enrolled Nurse','Registered Nurses']) {
   assert.equal(C.accepts(title,c,au[0]),true);
 }
 for(const title of ['Enrolled Nurse','Assistant in Nursing','Clinical Nurse','Data Engineer']) {
   assert.equal(C.accepts(title,c,au[0]),false);
 }
 assert.equal(C.accepts('Data Engineer',c,us[0]),true);
});
const raw={keywords:'Data Analyst,BI Analyst',excludes:'Financial Analyst',location:'melbourne',workplace:'remote',days:7,maxJobs:25,maxPages:3,delay:5,strictTitle:true};
test('query binds keyword, location, recency, workplace and pagination',()=>{
 const run={config:C.config(raw),query:1,page:2};const u=new URL(C.searchUrl(run));
 assert.equal(u.searchParams.get('keywords'),'BI Analyst');assert.equal(u.searchParams.get('geoId'),'100992797');
 assert.equal(u.searchParams.get('f_WT'),'2');assert.equal(u.searchParams.get('f_TPR'),'r604800');assert.equal(u.searchParams.get('start'),'50');
 assert.equal(C.matchesUrl(u.href+'&currentJobId=123',run),true);
 u.searchParams.set('geoId','104769905');assert.equal(C.matchesUrl(u.href,run),false);
});
test('missing first-page start accepted but changed search rejected',()=>{
 const run={config:C.config(raw),query:0,page:0};const u=new URL(C.searchUrl(run));u.searchParams.delete('start');
 assert.equal(C.matchesUrl(u.href,run),true);u.searchParams.set('keywords','Developer');assert.equal(C.matchesUrl(u.href,run),false);
});
test('new search-results redirect preserves scope and permits only removed sort',()=>{
 const run={config:C.config(raw),query:0,page:2};const u=new URL(C.searchUrl(run));
 u.pathname='/jobs/search-results/';u.searchParams.delete('sortBy');
 assert.equal(C.matchesUrl(u.href,run),true);
 for(const [key,value] of [['geoId','other'],['keywords','other'],['f_TPR','r86400'],['f_WT','1'],['start','0'],['distance','50'],['sortBy','R']]) {
   const changed=new URL(u);changed.searchParams.set(key,value);assert.equal(C.matchesUrl(changed.href,run),false,key);
 }
 u.pathname='/jobs/collections/';assert.equal(C.matchesUrl(u.href,run),false);
});
test('title inclusion and exclusion both apply',()=>{
 const c=C.config({...raw,location:'usa'});assert.equal(C.accepts('Senior Data Analyst',c),true);assert.equal(C.accepts('Financial Analyst / BI Analyst',c),false);assert.equal(C.accepts('Data Scientist',c),false);
 assert.equal(C.accepts('Data Scientist',{...c,strictTitle:false}),true);
});
test('reject invalid or excessive runs',()=>{
 for(const extra of [{keywords:''},{maxJobs:2001},{delay:0},{maxPages:41},{maxPages:0},{location:'unknown'},{workplace:'other'}])assert.throws(()=>C.config({...raw,...extra}));
});
test('nationwide presets can start with their configured limits',()=>{
 const {PRESETS}=require('./presets.js');
 for(const [name,preset] of Object.entries(PRESETS)){
  const c=C.config(preset);assert.equal(c.maxJobs,name.startsWith('all-occupations')?300:1000);
  assert.equal(C.config({...preset,maxJobs:1000,maxPages:40}).maxPages,40);
 }
});

test('search detail redirect requires the reserved ID and unchanged scope',()=>{
 const run={config:C.config(raw),query:0,page:2,visit:{source_job_id:'101'}};
 const url=new URL(C.searchUrl(run));url.pathname='/jobs/search-results/';url.searchParams.delete('sortBy');url.searchParams.set('currentJobId','101');
 assert.equal(C.matchesDetailUrl(url.href,run),true);
 for(const [key,value] of [['currentJobId','102'],['keywords','other'],['geoId','other'],['f_WT','1'],['f_TPR','r86400'],['start','0'],['distance','50']]) {
  const bad=new URL(url);bad.searchParams.set(key,value);assert.equal(C.matchesDetailUrl(bad.href,run),false,key);
 }
 const wrongHost=new URL(url);wrongHost.hostname='example.org';assert.equal(C.matchesDetailUrl(wrongHost.href,run),false);
 assert.equal(C.matchesDetailUrl(url.href,{...run,visit:null}),false);
 assert.equal(C.matchesDetailUrl('https://www.linkedin.com/jobs/view/101/',run),true);
});
