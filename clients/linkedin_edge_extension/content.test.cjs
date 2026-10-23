const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const C=require('./core.js');
const P=require('./pacing.js');

async function page({empty=false,closed=false,missingDate=false,stopDuringWait=false,detail=false,modern=false,delay=60,loadDelay=0,
 componentOnly=false,partialCard=false,missingDescription=false,timerStep=5000,roleOnly=false,searchDetail=false,cardsInMain=false,scopedHeader=false}={}) {
 const started=Date.now();let now=started,finish;
 const result=new Promise(resolve=>finish=resolve);
 const events=[];
 class Clock extends Date {constructor(...args){super(...(args.length?args:[now]));}static now(){return now;}}
 const run={id:'run',tabId:7,status:'running',mode:'paced',page:0,query:0,jobs:{},config:C.config({keywords:'Data Analyst',location:'usa',days:7,delay,pageDwell:120})};
 if(detail)run.visit={source_job_id:'101',title:'Data Analyst',company:'Example Company',location:'USA',canonical_url:'https://www.linkedin.com/jobs/view/101/'};
 const content={innerText:'A detailed role with responsibilities and requirements. '.repeat(4)};
 const metadata={innerText:missingDate?'USA · 10 applicants':'USA · 2 hours ago · 10 applicants',querySelector:()=>null};
 if(scopedHeader) content.parentElement={innerText:metadata.innerText+'\n'+content.innerText.trim(),querySelector:selector=>selector.startsWith('a[href')?{}:null};
 const top={innerText:closed?'No longer accepting applications':'Data Analyst',querySelector:()=>metadata};
 const link={querySelector:()=>({innerText:'Data Analyst'}),click:()=>{throw Error('Must not click title links');}};
 const card={getAttribute:()=> '101',scrollIntoView(){},querySelector:selector=> selector==='a.job-card-list__title--link'?link:
  {innerText:selector==='.artdeco-entity-lockup__subtitle'?'Example Company':'USA'}};
 const badCard={getAttribute:key=>key==='data-occludable-job-id'?'202':null,scrollIntoView(){},querySelector:()=>null};
 const document={title:'Jobs',body:{innerText:empty?'No results found':'Jobs'},
  getElementById:id=>modern && !componentOnly && !missingDescription && now-started>=loadDelay && id==='JobDetails_AboutTheJob_101'?content:null,
  querySelector:selector=>{
   if(selector.startsWith('li[data-occludable-job-id]'))return empty?null:card;
   if(selector==='[componentkey="JobDetails_AboutTheJob_101"]')return componentOnly && !missingDescription?content:null;
   if((selector==='main' && !roleOnly) || (selector==='[role="main"]' && roleOnly))return {innerText:(cardsInMain?'Other job: 5 days ago\n':'')+(closed?'No longer accepting applications ':'')+metadata.innerText+'\n'+content.innerText.trim(),querySelector:()=>cardsInMain?card:null};
   if(selector==='#job-details') return modern || missingDescription?null:content;
   if(selector==='.job-details-jobs-unified-top-card__container' || selector==='.jobs-search__job-details--container')return modern?null:top;
   return null;
  },querySelectorAll:selector=>selector.startsWith('li[data-occludable-job-id]')?(empty?[]:partialCard?[badCard,card]:[card]):[]};
 const chrome={runtime:{sendMessage:async message=>{
  if(message.type==='state')return {ok:true,value:structuredClone(run)};
  if(message.type==='preflight')return {ok:true,value:{skip:false}};
  events.push({...message,time:now});
  if(message.type==='job') {run.jobs[message.job.source_job_id]=message.job;return {ok:true,value:structuredClone(run)};}
  if(['pageBatch','detailDone','pause'].includes(message.type))finish({events,elapsed:now-started});
  return {ok:true,value:run};
 }}};
 const detailSearch=new URL(C.searchUrl(run));detailSearch.pathname='/jobs/search-results/';detailSearch.searchParams.set('currentJobId','101');
 const context=vm.createContext({document,location:{href:searchDetail?detailSearch.href:detail?'https://www.linkedin.com/jobs/view/101/':C.searchUrl(run)},chrome,LinkedInCollector:C,Date:Clock,URL,
  setTimeout:fn=>{now+=timerStep;if(stopDuringWait)run.status='paused';queueMicrotask(fn);}});
 vm.runInContext(fs.readFileSync(__dirname+'/pacing.js','utf8'),context);
 vm.runInContext(fs.readFileSync(__dirname+'/content.js','utf8'),context);
 return result;
}
test('new-layout detail captures publication evidence, dwells, and continues automatically',async()=>{
 const result=await page({detail:true,modern:true});const job=result.events.find(e=>e.type==='job').job;
 assert.equal(P.valid(job,7,Date.parse(job.collected_at)),true);
 assert.match(job.posted_at_evidence,/2 hours ago/);
 assert.ok(result.elapsed>=60000);
 assert.equal(result.events.at(-1).type,'detailDone');
});

test('job-specific componentkey can supply the description without an element ID',async()=>{
 const result=await page({detail:true,modern:true,componentOnly:true});
 const saved=result.events.find(e=>e.type==='job');assert.ok(saved);assert.equal(saved.job.detail_status,'complete');
 assert.equal(result.events.at(-1).type,'detailDone');
});

test('one unreadable card is reported while the rest of the page continues',async()=>{
 const result=await page({partialCard:true});
 const batch=result.events.find(e=>e.type==='pageBatch');assert.equal(batch.jobs.length,1);
 assert.equal(batch.unreadableCards.length,1);assert.equal(batch.unreadableCards[0].jobId,'202');
 assert.equal(result.events.some(e=>e.type==='pause'),false);
});

test('a missing description reports its exact stage and does not invent a job',async()=>{
 const result=await page({detail:true,modern:true,missingDescription:true});
 const failure=result.events.at(-1);assert.equal(failure.type,'pause');
 assert.equal(failure.recoverable,true);assert.equal(failure.stage,'detail-description:101');
 assert.equal(result.events.some(e=>e.type==='job'),false);
});

test('ten second dwell begins after a slow detail finishes loading and before it is saved',async()=>{
 const result=await page({detail:true,modern:true,delay:10,loadDelay:30000});
 assert.ok(result.elapsed>=40000);
 assert.equal(result.events.at(-1).type,'detailDone');
 const saved=result.events.find(e=>e.type==='job');
 assert.ok(result.events.at(-1).time-saved.time<1000);
});

test('a throttled background timer inspects ready details on wake instead of reporting a false timeout',async()=>{
 const result=await page({detail:true,modern:true,delay:10,loadDelay:30000,timerStep:60000});
 const saved=result.events.find(e=>e.type==='job');assert.ok(saved);
 assert.equal(P.valid(saved.job,7,Date.parse(saved.job.collected_at)),true);
 assert.equal(result.events.at(-1).type,'detailDone');assert.ok(result.elapsed>=70000);
});

test('a delayed timer still honors a manual stop before reading ready details',async()=>{
 const result=await page({detail:true,modern:true,loadDelay:30000,timerStep:60000,stopDuringWait:true});
 assert.equal(result.events.some(e=>e.type==='job'),false);
 assert.equal(result.events.at(-1).type,'pause');
});
test('empty pages also dwell instead of cycling searches rapidly',async()=>{
 const result=await page({empty:true});assert.ok(result.elapsed>=120000);
 assert.equal(result.events.some(e=>e.type==='job'),false);
});
test('closed and undated listings cannot qualify',async()=>{
 for(const options of [{closed:true},{missingDate:true}]) {
  const result=await page({...options,detail:true,modern:true});const job=result.events.find(e=>e.type==='job').job;
  assert.equal(P.valid(job,7,Date.parse(job.collected_at)),false);
 }
});
test('manual stop during dwell prevents next-page navigation',async()=>{
 const result=await page({stopDuringWait:true});
 assert.equal(result.events.some(e=>e.type==='pageBatch'),false);
 assert.equal(result.events.at(-1).type,'pause');
});

test('search snapshots the whole page before leaving and never clicks a title',async()=>{
 const result=await page();
 assert.ok(result.elapsed>=120000);
 const batch=result.events.find(e=>e.type==='pageBatch');
 assert.equal(batch.jobs.length,1);assert.equal(batch.jobs[0].source_job_id,'101');
 assert.equal(result.events.some(e=>e.type==='job'),false);
});

test('role main search detail reads reserved description, publication and closure evidence',async()=>{
 for(const closed of [false,true]) {
  const result=await page({detail:true,modern:true,roleOnly:true,searchDetail:true,closed,delay:10});
  const saved=result.events.find(e=>e.type==='job');assert.ok(saved);
  assert.equal(P.valid(saved.job,7,Date.parse(saved.job.collected_at)),!closed);
  assert.match(saved.job.posted_at_evidence,/2 hours ago/);assert.equal(result.events.at(-1).type,'detailDone');
 }
});

test('other search cards cannot supply publication evidence for the reserved detail',async()=>{
 const scoped=await page({detail:true,modern:true,searchDetail:true,roleOnly:true,cardsInMain:true,scopedHeader:true,delay:10});
 const job=scoped.events.find(event=>event.type==='job').job;
 assert.match(job.posted_at_evidence,/2 hours ago/);assert.doesNotMatch(job.posted_at_evidence,/5 days ago/);
 const unscoped=await page({detail:true,modern:true,searchDetail:true,roleOnly:true,cardsInMain:true,delay:10});
 assert.equal(P.valid(unscoped.events.find(event=>event.type==='job').job,7),false);
});
