importScripts('catalog.js', 'core.js', 'presets.js', 'pacing.js', 'lifecycle.js', 'controller.js', 'sync.js');
const C = LinkedInCollector;
const P = LinkedInPacing;
const load = async () => (await chrome.storage.local.get('run')).run;
const save = async run => { run.updatedAt = new Date().toISOString(); await chrome.storage.local.set({run}); return run; };
let queue = Promise.resolve();
const DAILY_ALARM = 'linkedin-daily-collector';
const PACED_ALARM = 'linkedin-paced-collector';
const RETRY_ALARM = 'linkedin-page-retry';
const WAKE_ALARM = 'linkedin-next-detail';
const WATCHDOG_ALARM = 'linkedin-page-watchdog';
const SYNC_ALARM = 'linkedin-database-sync';

async function reviewLinkedIn(run) {
  if (!globalThis.JobLifecycle || run.mode!=='paced' || run.status==='paused' || !P.window().active) return false;
  return globalThis.JobLifecycle.run({source:'linkedin_user_import',
    candidates:async()=>Object.entries((await chrome.storage.local.get('acceptedJobs')).acceptedJobs || {})
      .map(([id,seen])=>({id,seen})),
    reserve:()=>reserveDetail(run),
    pause:reason=>handle({type:'pause',runId:run.id,reason},{tab:{id:run.tabId}}),
    deliver:async observation=>{
      if (globalThis.LinkedInSync && await LinkedInSync.configured()) return LinkedInSync.observe(observation);
      const url='data:application/json;charset=utf-8,'+encodeURIComponent(JSON.stringify({jobs:[],observations:[observation]}));
      const id=await chrome.downloads.download({url,filename:`linkedin-review-${Date.now()}.json`,saveAs:false});
      for(let attempt=0;attempt<20;attempt++) {
        const [item]=await chrome.downloads.search({id});
        if(item?.state==='complete') return;
        if(item?.state==='interrupted') break;
        await new Promise(resolve=>setTimeout(resolve,500));
      }
      throw Error('职位复查记录导出失败，将自动重试。');
    }});
}

async function scheduleSync(run) {
  if (globalThis.LinkedInSync && await LinkedInSync.configured()) {
    await LinkedInSync.capture(run);
    run.syncPending = false;
    await chrome.alarms.clear(SYNC_ALARM);
    return save(run);
  }
  run.dataRevision = (run.dataRevision || 0) + 1;
  await save(run);
  if (!run.syncPending) {
    run.syncPending = true;
    await save(run);
    await chrome.alarms.create(SYNC_ALARM, {delayInMinutes:2, periodInMinutes:2});
  }
  return run;
}

async function syncCheckpoint() {
  if (globalThis.LinkedInSync && await LinkedInSync.configured()) {
    await LinkedInSync.capture(await load());
    return LinkedInSync.flush();
  }
  const run = await load();
  if (!run?.syncPending) return;
  if (run.syncExport) {
    const [item] = await chrome.downloads.search({id:run.syncExport.id});
    if (item?.state === 'in_progress') return;
    if (item?.state === 'complete') {
      run.syncedJobs = {...run.syncedJobs, ...run.syncExport.stamps};
      run.lastSyncExportAt = new Date().toISOString();
    }
    run.syncExport = null;
  }
  const jobs = Object.fromEntries(Object.entries(run.jobs).filter(([id, job]) =>
    !run.syncedJobs || run.syncedJobs[id] !== (job.collected_at || String(run.dataRevision))));
  if (Object.keys(jobs).length) {
    const id = await download({...run, jobs});
    run.syncExport = {id, stamps:Object.fromEntries(Object.entries(jobs).map(([key, job]) =>
      [key, job.collected_at || String(run.dataRevision)]))};
  } else {
    run.syncPending = false;
    await chrome.alarms.clear(SYNC_ALARM);
  }
  run.syncError = null;
  await save(run);
}

async function navigate(run, url) {
  run.lastNavigationAt=Date.now();
  await save(run);
  await chrome.alarms.create(WATCHDOG_ALARM,{delayInMinutes:1,periodInMinutes:1});
  // Updating to the same URL can leave an already-finished content script in place.
  const tab=await chrome.tabs.get(run.tabId).catch(()=>null);
  if(!tab) {const fresh=await chrome.tabs.create({url,active:false});run.tabId=fresh.id;await save(run);}
  else if(tab.url===url) await chrome.tabs.reload(run.tabId);
  else await chrome.tabs.update(run.tabId,{url});
}
async function waitPaced(run, until, message) {
  run.status='waiting';run.pacing.notBefore=until;run.message=message;
  await save(run);await chrome.alarms.create(WAKE_ALARM,{when:until});return run;
}
async function reserveDetail(run) {
  const now=Date.now(), w=P.window(now);
  const rate=(await chrome.storage.local.get('pacedRate')).pacedRate || {};
  if(rate.hour!==w.hour) {rate.hour=w.hour;rate.count=0;}
  const until=!w.active?w.nextStart:rate.count>=50?w.nextHour:rate.nextAt || 0;
  if(until>now) {
    await waitPaced(run,until,!w.active?'工作时段外，下一次 09:00 自动继续。':
      rate.count>=50?'本小时 50 次详情访问额度已用完，下一小时继续。':
      `正常间隔等待，约 ${Math.ceil((until-now)/1000)} 秒后读取下一条；本小时已访问 ${rate.count}/50 次。`);
    return false;
  }
  rate.count++;rate.nextAt=now+72000;
  await chrome.storage.local.set({pacedRate:rate});return true;
}

function markCurrent(run, status) {
  const q = C.currentQuery(run);
  if (q) q.status = status;
  return q;
}
function ensureQueue(run) {
  if (!run.queue?.length) {
    run.queue = C.buildQueue(run.config);
    run.queueIndex = Math.min(run.query || 0, Math.max(run.queue.length - 1, 0));
    run.query = run.queueIndex;
    for (const item of run.queue) item.status = 'pending';
    markCurrent(run, run.status === 'running' ? 'running' : 'paused');
  }
  return run;
}
function dailyConfigs(mode, phase='backfill') {
  if (mode === 'coverage') {
    const name = phase === 'daily' ? 'all-occupations-daily' : 'all-occupations-backfill';
    return [C.config(LINKEDIN_PRESETS[name])];
  }
  return ['us-data','au-nursing'].map(name => C.config(LINKEDIN_PRESETS[name]));
}
function nextAt(hour, minute) {
  const next=new Date(); next.setHours(hour,minute,0,0); if(next<=new Date())next.setDate(next.getDate()+1); return next.getTime();
}
async function configureAlarm(schedule) {
  if(!Number.isInteger(schedule.hour)||schedule.hour<0||schedule.hour>23||!Number.isInteger(schedule.minute)||schedule.minute<0||schedule.minute>59)throw Error('请输入有效时间。');
  await chrome.storage.local.set({schedule});
  await chrome.alarms.clear(DAILY_ALARM);
  if(schedule.enabled) await chrome.alarms.create(DAILY_ALARM,{when:nextAt(schedule.hour,schedule.minute),periodInMinutes:1440});
  return schedule;
}
async function findLinkedInTab() {
  const tabs=await chrome.tabs.query({url:['https://www.linkedin.com/*']});
  return tabs[0] || chrome.tabs.create({url:'https://www.linkedin.com/feed/',active:false});
}
async function begin(config, tab, origin='manual', mode='legacy', continuation=null) {
  const checked=C.config(config);
  const queueItems=continuation?.queue?.length ? continuation.queue : C.buildQueue(checked);
  if (!queueItems.length) throw Error('没有可执行的查询：请先配置有效的国家/州/领地 geoId。');
  const startIndex=Math.min(Number(continuation?.queueIndex || 0), queueItems.length - 1);
  const old=await load(); if(old)await chrome.storage.local.set({previousRun:old});
  if(old?.cooldownUntil && Date.now()<Date.parse(old.cooldownUntil)) throw Error('访问限制冷却尚未结束，不能启动新任务。');
  const run={id:crypto.randomUUID(),config:checked,tabId:tab.id,status:'running',query:startIndex,queueIndex:startIndex,
    page:Number(continuation?.page || 0),jobs:{},queue:queueItems,origin,mode,startedAt:new Date().toISOString(),
    message:`已建立 ${queueItems.length} 个查询分区，正在打开第 ${startIndex + 1} 个…`};
  markCurrent(run, 'running');
  await save(run);
  try {await navigate(run,C.searchUrl(run));}
  catch(e){return handle({type:'pause',runId:run.id,recoverable:true,reason:`打开搜索失败：${e.message}`},{tab:{id:run.tabId}});}
  return run;
}
async function download(run) {
  const payload={schema_version:2,started_at:run.startedAt,exported_at:new Date().toISOString(),config:run.config,
    status:run.status,message:run.message,coverage:C.coverage(run),queries:run.queue || [],jobs:Object.values(run.jobs),
    pacing:run.pacing ? {...run.pacing,validCount:P.count(run),rejected:run.rejected || 0}:undefined,
    failures:run.failures || {},cardFailures:run.cardFailures || []};
  const url='data:application/json;charset=utf-8,'+encodeURIComponent(JSON.stringify(payload,null,2));
  const location=['coverage','paced'].includes(run.mode) ? 'us-au' : run.config.location || 'custom';
  return chrome.downloads.download({url,filename:`linkedin-${location}-${Date.now()}.json`,saveAs:false});
}
async function startDaily(mode, force=false) {
  if ((await chrome.storage.local.get('pacedEnabled')).pacedEnabled) return load();
  const current=await load(); if(['running','paused','waiting','retrying'].includes(current?.status))return current;
  const tab=await findLinkedInTab();
  const stored=await chrome.storage.local.get(['backfillCompletedAt','coverageContinuation','coverageMode','lastDailyFinish']);
  const activeMode=mode || stored.coverageMode || 'legacy';
  if (!force && stored.lastDailyFinish) {
    const finished=Date.parse(stored.lastDailyFinish);
    const cooldown=Number(current?.config?.cooldownMinutes || 30) * 60000;
    if (Number.isFinite(finished) && Date.now() < finished + cooldown) return current;
  }
  if (activeMode === 'coverage' && stored.coverageContinuation?.queue?.length) {
    await chrome.storage.local.set({coverageContinuation:null,lastDailyStart:new Date().toISOString(),coverageMode:activeMode});
    return begin(stored.coverageContinuation.config,tab,'daily','coverage',stored.coverageContinuation);
  }
  const configs=dailyConfigs(activeMode, stored.backfillCompletedAt ? 'daily' : 'backfill');
  await chrome.storage.local.set({dailyQueue:configs.slice(1),lastDailyStart:new Date().toISOString(),coverageMode:activeMode});
  return begin(configs[0],tab,'daily',activeMode);
}
chrome.alarms.onAlarm.addListener(alarm=>{
  if(alarm.name===SYNC_ALARM) queue=queue.catch(()=>{}).then(syncCheckpoint).catch(async error=>{
    const run=await load();
    if(run) {run.syncError=error.message;await save(run);}
  });
  if(alarm.name===RETRY_ALARM) queue=queue.catch(()=>{}).then(retryPage).catch(pacedError);
  if(alarm.name===PACED_ALARM || alarm.name===WAKE_ALARM) queue=queue.catch(()=>{}).then(pacedTick).catch(pacedError);
  if(alarm.name===WATCHDOG_ALARM) queue=queue.catch(()=>{}).then(watchdogTick).catch(pacedError);
  if(alarm.name===DAILY_ALARM)queue=queue.catch(()=>{}).then(async()=>{const s=await chrome.storage.local.get('coverageMode');return startDaily(s.coverageMode);});
});
chrome.runtime.onInstalled.addListener(async details=>{
  await migratePaced();
  await migrateStalledRetry();
  const active=await load();
  if (globalThis.LinkedInSync && await LinkedInSync.configured()) await LinkedInSync.capture(active);
  if(active?.syncPending) await chrome.alarms.create(SYNC_ALARM,{delayInMinutes:1,periodInMinutes:2});
  if(active?.status==='running') await chrome.alarms.create(WATCHDOG_ALARM,{delayInMinutes:1,periodInMinutes:1});
  if(active?.status==='retrying') await chrome.alarms.create(RETRY_ALARM,{when:Math.max(Date.now()+1000,active.retryAt || 0)});
  const {schedule,coverageMode}=await chrome.storage.local.get(['schedule','coverageMode']);
  if (!coverageMode) await chrome.storage.local.set({coverageMode:'coverage'});
  if(details.reason==='install' && !schedule) {
    await chrome.storage.local.set({coverageMode:'coverage'});
    await configureAlarm({enabled:false,hour:9,minute:0});
  } else if ((await chrome.storage.local.get('pacedEnabled')).pacedEnabled) {await armPaced();await pacedTick();}
  else if(schedule?.enabled) await configureAlarm(schedule);
});
chrome.runtime.onStartup.addListener(()=>{
  queue=queue.catch(()=>{}).then(async()=>{
    await migratePaced();
    await migrateStalledRetry();
    const run=await load();
    if (globalThis.LinkedInSync && await LinkedInSync.configured()) await LinkedInSync.capture(run);
    if(run?.syncPending) await chrome.alarms.create(SYNC_ALARM,{delayInMinutes:1,periodInMinutes:2});
    if(run?.status==='retrying') {await chrome.alarms.create(RETRY_ALARM,{when:Math.max(Date.now()+60000,run.retryAt)});return;}
    if ((await chrome.storage.local.get('pacedEnabled')).pacedEnabled) {
      if(run?.mode==='paced' && run.status==='running') {
        run.status='waiting'; run.pacing.notBefore=Date.now();
        run.message='浏览器已重启，按每日时间表恢复进度。'; await save(run);
      }
      await armPaced(); await pacedTick(); return;
    }
    if(run?.status==='running'){
      run.status='retrying';run.retryAt=Date.now()+60000;
      run.message='Edge 已重启，1 分钟后自动恢复保存的进度。';await save(run);
      await chrome.alarms.create(RETRY_ALARM,{when:run.retryAt});return;
    }
    const {schedule,lastDailyStart,coverageMode}=await chrome.storage.local.get(['schedule','lastDailyStart','coverageMode']);
    if(!schedule?.enabled)return;
    await configureAlarm(schedule);
    const now=new Date(), last=lastDailyStart?new Date(lastDailyStart):null;
    if(now.getHours()*60+now.getMinutes()>=schedule.hour*60+schedule.minute && (!last||last.toDateString()!==now.toDateString()))await startDaily(coverageMode || 'legacy');
  });
});
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  // Original-link reviews may take 30 seconds. Status is read-only and must not
  // wait behind that source navigation or the dashboard falsely reports offline.
  if(message.type==='collectorControl' && message.action==='status') {
    handle(message,sender).then(value=>reply({ok:true,value}),error=>reply({ok:false,error:error.message}));
    return true;
  }
  queue = queue.catch(() => {}).then(() => handle(message, sender));
  queue.then(value => reply({ok:true, value}), error => reply({ok:false, error:error.message}));
  return true;
});
async function handle(m, sender) {
  if (m.type === 'collectorControl' && globalThis.JobaggControl) {
    return JobaggControl.handle(m,sender,'linkedin',{
      status:collectorStatus,
      configure:async config=>{await LinkedInSync.configure(config);await chrome.alarms.clear(SYNC_ALARM);await LinkedInSync.capture(await load());},
      start:async()=>{const current=await load();
        if(JobaggControl.requiresHuman(current)) throw Error('请先打开领英处理验证，再点击“验证后继续”。');
        await startPaced(true);},
      pause:()=>handle({type:'stop'},{url:chrome.runtime.getURL('popup.html')}),
      resume:()=>handle({type:'resume',defer:true},{url:chrome.runtime.getURL('popup.html')}),
      sync:async()=>{await LinkedInSync.capture(await load());
        await chrome.alarms.create('linkedin-direct-sync',{when:Date.now()+1000,periodInMinutes:1});}
    });
  }
  let run = await load();
  if (sender.tab) {
    if (!run || sender.tab.id !== run.tabId) return null;
    ensureQueue(run);
    if (m.type === 'state') {
      if(run.mode==='paced' && run.status==='running') await pacedHold(run);
      if(run.status==='running' && Date.now()-(run.lastActivityAt || 0)>=5000) {
        run.lastActivityAt=Date.now();await save(run);
      }
      return run;
    }
    if (m.runId !== run.id || run.status !== 'running') return null;
    if (m.type === 'pageBatch') {
      if(!C.matchesUrl(sender.url || '',run)) throw Error('职位队列必须来自当前搜索页。');
      if(!Array.isArray(m.jobs) || m.jobs.length>100 || m.jobs.some(j=>!/^\d+$/.test(String(j.source_job_id)) || j.canonical_url!==`https://www.linkedin.com/jobs/view/${j.source_job_id}/`)) throw Error('无效页面职位队列');
      run.pageBatch={jobs:[...new Map(m.jobs.filter(j=>C.accepts(j.title,run.config,C.currentQuery(run))).map(j=>[j.source_job_id,j])).values()],index:0,last:!!m.last,resultCount:m.resultCount};
      if(Array.isArray(m.unreadableCards)) run.cardFailures=[...(run.cardFailures || []),
        ...m.unreadableCards.slice(0,100).map(item=>({jobId:String(item.jobId || '').slice(0,40),stage:'card-fields',
          reason:String(item.reason || '').slice(0,200),page:run.page,queryId:C.currentQuery(run)?.id,at:new Date().toISOString()}))].slice(-2000);
      run.retryAttempts=0;
      await save(run);return nextDetail(run);
    }
    if(m.type==='detailDone') {
      if(!run.pageBatch || !C.matchesDetailUrl(sender.url || '',run) || String(m.jobId)!==String(run.visit?.source_job_id)) throw Error('详情与当前职位不匹配');
      run.pageBatch.index++;run.visit=null;run.retryAttempts=0;await save(run);return nextDetail(run);
    }
    if (run.mode === 'paced' && m.type === 'preflight') {
      if (await pacedHold(run)) return {wait:true};
      const ledger=(await chrome.storage.local.get('acceptedJobs')).acceptedJobs || {};
      return {skip:P.fresh(ledger[String(m.jobId)]) || P.fresh(run.jobs[String(m.jobId)]?.collected_at)};
    }
    if (m.type === 'job') {
      if(!m.job||!/^[0-9]+$/.test(String(m.job.source_job_id))||!['complete','failed','pending'].includes(m.job.detail_status))throw Error('无效职位数据');
      if(C.currentQuery(run)?.country==='AU' && !C.registeredNurseTitle(m.job.title)) {
        run.rejected=(run.rejected || 0)+1;return save(run);
      }
      if (run.mode === 'paced') {
        if (await pacedHold(run)) return null;
        const ledger=(await chrome.storage.local.get('acceptedJobs')).acceptedJobs || {};
        if (!P.valid(m.job,run.config.days) || !C.accepts(m.job.title,run.config,C.currentQuery(run)) || P.fresh(ledger[m.job.source_job_id])) {
          run.rejected=(run.rejected || 0)+1; return save(run);
        }
        ledger[m.job.source_job_id]=new Date().toISOString();
        run.pacing.slotCount++;
        const q=C.currentQuery(run);
        if(q) q.savedCount=(q.savedCount || 0)+1;
        run.jobs[m.job.source_job_id]={...m.job,query_id:q?.id,occupation_group:q?.occupationId,search_country:q?.country,search_location:q?.locationName};
        run.message=`今日有效去重 ${P.countDaily(ledger)}/${P.DAILY_TARGET} 条；本小时 ${run.pacing.slotCount}/${P.allowance(run.pacing,run.pacing.slot)} 条`;
        run.updatedAt=new Date().toISOString();
        await chrome.storage.local.set({run,acceptedJobs:ledger});
        return scheduleSync(run);
      }
      const q=C.currentQuery(run);
      if(q) q.savedCount = (q.savedCount || 0) + (run.jobs[m.job.source_job_id] ? 0 : 1);
      run.jobs[m.job.source_job_id] = {...m.job, query_id:q?.id, occupation_group:q?.occupationId, search_country:q?.country, search_location:q?.locationName};
      run.message = `已保存 ${Object.keys(run.jobs).length} 条职位；分区 ${run.queueIndex + 1}/${run.queue.length}`;
      return scheduleSync(run);
    }
    if (m.type === 'pause') {
      const q=markCurrent(run,'paused');
      const reason=String(m.reason || '');
      const rateLimit=/(?:HTTP\s*)?429|too many requests|rate limit|请求过多|访问频率|请求频率/i.test(reason);
      const security=/验证码|安全验证|安全检查|登录|challenge|checkpoint|authwall|human/i.test(reason);
      if(m.recoverable && !security && !rateLimit) {
        run.retryAttempts=(run.retryAttempts || 0)+1;
        run.lastFailure={reason:reason.slice(0,1000),stage:String(m.stage || (run.visit?'detail':'search')).slice(0,80),
          url:String(sender.url || '').slice(0,2000),at:new Date().toISOString()};
        if(run.retryAttempts>run.config.maxRetries) return exhaustRetry(run);
        const minutes=Math.min(30,2*2**Math.min(run.retryAttempts-1,4));
        run.status='retrying';run.retryAt=Date.now()+minutes*60000;
        run.message=`${run.lastFailure.stage} 暂未恢复，${minutes} 分钟后重试（${run.retryAttempts}/${run.config.maxRetries}）。`;
        await save(run);await chrome.alarms.create(RETRY_ALARM,{when:run.retryAt});return run;
      }
      if(rateLimit) {
        const minutes=Math.max(360,Number(run.config.cooldownMinutes || 0));
        run.cooldownUntil=new Date(Date.now()+minutes*60000).toISOString();
      }
      if(q && !security && !rateLimit) {
        q.attempts=(q.attempts || 0) + 1; q.lastError=m.reason;
        if(q.attempts > run.config.maxRetries) q.status='failed';
      }
      run.status='paused'; run.message=rateLimit ? `检测到 HTTP 429，已暂停至 ${new Date(run.cooldownUntil).toLocaleString()}，请勿提前重试。` :
        (q?.status==='failed' ? '该分区连续失败，进度已保存；点击继续将自动细分或转到其他待处理分区。' : m.reason);
      // Restrictions and verification always require a deliberate manual resume.
      return save(run);
    }
    if (m.type === 'advance') {
      if (run.mode === 'paced') return pacedAdvance(run,m);
      const q=C.currentQuery(run);
      if (!q) {run.status='done';run.message='没有可执行的查询分区。';return save(run);}
      const budgetDone = run.mode === 'legacy' && Object.keys(run.jobs).length >= run.config.maxJobs;
      const pageDone = !!m.last || run.page + 1 >= run.config.maxPages || budgetDone;
      q.resultCount = Number.isFinite(Number(m.resultCount)) ? Number(m.resultCount) : q.resultCount;
      q.page = run.page;
      const nearLimit = q.resultCount !== null && q.resultCount >= run.config.splitThreshold;
      const children = pageDone && nearLimit ? C.splitQuery(q, run.config) : [];
      if (children.length) {
        q.status='split'; q.finishedAt=new Date().toISOString();
        run.queue.splice(run.queueIndex + 1, 0, ...children);
        run.message=`分区接近 ${run.config.splitThreshold} 条，已细分为 ${children.length} 个子分区。`;
      } else if (pageDone) {
        q.status=nearLimit ? 'limited' : 'done'; q.finishedAt=new Date().toISOString();
        if (nearLimit) q.lastError='达到结果上限或未找到可用的更细 geoId；已记录为受限分区。';
      }
      if (Object.keys(run.jobs).length >= run.config.maxJobs && run.mode === 'legacy') {
        run.queueIndex = run.queue.length - 1;
      } else if (Object.keys(run.jobs).length >= run.config.maxJobs) {
        if (run.mode === 'coverage') {
          if (!pageDone) markCurrent(run,'paused');
          const nextIndex=pageDone ? run.queueIndex + 1 : run.queueIndex;
          await chrome.storage.local.set({coverageContinuation:{config:run.config,queue:run.queue,queueIndex:nextIndex,page:pageDone ? 0 : run.page}});
          run.status='done'; run.message=`已达到本次访问预算 ${run.config.maxJobs} 条，剩余 ${Math.max(run.queue.length-nextIndex,0)} 个分区将在下一次定时任务继续。`;
          await save(run);
          if(run.origin==='daily') await download(run);
          return run;
        }
        run.status='paused'; markCurrent(run,'paused'); run.message=`已达到本次访问预算 ${run.config.maxJobs} 条，进度已保存。`;
        return save(run);
      }
      if (!pageDone) {
        run.page++;
        q.page=run.page;
      } else {
        run.queueIndex++;
        run.query=run.queueIndex;
        run.page=0;
      }
      if (run.queueIndex >= run.queue.length) {
        run.status='done'; run.message=nearLimit && !children.length ? '采集完成，但存在受结果上限影响的分区；请查看覆盖报告。' : '本次覆盖队列采集结束，可导出结果。';
        await save(run);
        if(run.origin==='daily') {
          await download(run);
          const stored=await chrome.storage.local.get('dailyQueue'); const pending=stored.dailyQueue||[];
          if(pending.length) {
            await chrome.storage.local.set({dailyQueue:pending.slice(1)});
            return begin(pending[0],{id:run.tabId},'daily',run.mode);
          }
          if(run.mode === 'coverage' && run.config.days > 1) await chrome.storage.local.set({backfillCompletedAt:new Date().toISOString()});
          await chrome.storage.local.set({lastDailyFinish:new Date().toISOString()});
        }
        return run;
      }
      markCurrent(run,'running');
      run.message=`正在处理分区 ${run.queueIndex + 1}/${run.queue.length}：${C.currentQuery(run).keyword} @ ${C.currentQuery(run).locationName}`;
      await save(run);
      await chrome.tabs.update(run.tabId, {url:C.searchUrl(run)});
      return run;
    }
    return null;
  }
  // Only the extension popup may start, stop, resume or export.
  if (!sender.url?.startsWith(chrome.runtime.getURL(''))) throw Error('无效调用来源');
  if (m.type === 'startPaced') return startPaced();
  if (m.type === 'pacedState') {
    const {pacedEnabled}=await chrome.storage.local.get('pacedEnabled');
    return {enabled:!!pacedEnabled,count:run?.mode==='paced'?await todayCount():0};
  }
  if (m.type === 'state') return run ? ensureQueue(run) : null;
  if (m.type === 'scheduleState') return (await chrome.storage.local.get(['schedule','lastDailyStart','lastDailyFinish','coverageMode','backfillCompletedAt']));
  if (m.type === 'setSchedule') {
    if ((await chrome.storage.local.get('pacedEnabled')).pacedEnabled) throw Error('全天计划已开启；请先停止，避免两个定时计划重叠。');
    return configureAlarm({enabled:!!m.schedule.enabled,hour:Number(m.schedule.hour),minute:Number(m.schedule.minute)});
  }
  if (m.type === 'runDailyNow') {
    if(run?.status==='running' && (!m.coverage || run.config?.plan==='all-occupations'))throw Error('已有全职业任务在运行，无需重复启动。');
    if(run?.status==='paused' && (!m.coverage || run.config?.plan==='all-occupations'))throw Error('存在暂停任务，请先继续；或通过开始新任务明确替换。');
    if(m.coverage && run && ['running','paused'].includes(run.status) && run.config?.plan!=='all-occupations') {
      const tab=await findLinkedInTab();
      await chrome.storage.local.set({coverageContinuation:null,coverageMode:'coverage'});
      return begin(LINKEDIN_PRESETS['all-occupations-backfill'],tab,'manual','coverage');
    }
    return startDaily(m.coverage ? 'coverage' : undefined, true);
  }
  if (m.type === 'stop') {
    await chrome.alarms.clear(WAKE_ALARM);
    await chrome.alarms.clear(RETRY_ALARM);
    await chrome.alarms.clear(WATCHDOG_ALARM);
    await chrome.storage.local.set({pacedEnabled:false}); await chrome.alarms.clear(PACED_ALARM);
    if (run) {run.status='paused';markCurrent(run,'paused'); run.message='已停止，进度已保存。'; await save(run);}
    return run;
  }
  if (m.type === 'start' || m.type === 'resume') {
    const [activeTab] = await chrome.tabs.query({active:true, currentWindow:true});
    const tab = m.type==='resume' && !activeTab?.url?.startsWith('https://www.linkedin.com/')
      ? await findLinkedInTab() : activeTab;
    if (!tab?.url?.startsWith('https://www.linkedin.com/')) throw Error('请先切换到已登录的领英标签页。');
    if (m.type === 'start') {
      if ((await chrome.storage.local.get('pacedEnabled')).pacedEnabled) throw Error('全天计划已开启，请先停止。');
      if (run?.cooldownUntil && Date.now()<Date.parse(run.cooldownUntil)) throw Error('访问限制冷却尚未结束，不能通过新任务跳过。');
      if (run?.status === 'running' && m.config?.plan !== 'all-occupations') throw Error('已有任务在运行，请先停止。');
      if (run?.status === 'running' && run.config?.plan === 'all-occupations') throw Error('已有全职业任务在运行，无需重复启动。');
      if (run) await chrome.storage.local.set({previousRun:run});
      return begin(m.config,tab,'manual',m.config.plan === 'all-occupations' ? 'coverage' : 'legacy');
    } else {
      if (!run || run.status !== 'paused') throw Error('没有可继续的暂停任务。');
      ensureQueue(run);
      if (run.cooldownUntil && Date.now() < Date.parse(run.cooldownUntil)) throw Error(`访问频率冷却中，请在 ${new Date(run.cooldownUntil).toLocaleString()} 后再继续。`);
      recoverLayoutCheckpoint(run);
      recoverFailedCheckpoint(run);
      if (run.mode === 'paced') {
        await chrome.storage.local.set({pacedEnabled:true}); await armPaced();
        run.status='waiting'; run.tabId=tab.id; run.pacing.notBefore=Date.now();
        await save(run);
        if(m.defer) {await chrome.alarms.create(WAKE_ALARM,{when:Date.now()+1000});return run;}
        return pacedTick();
      }
      run.tabId=tab.id; run.status='running'; run.message='正在继续…'; markCurrent(run,'running');
    }
    await save(run);
    if(run.pageBatch) return nextDetail(run);
    await navigate(run,C.searchUrl(run));
    return run;
  }
  if (m.type === 'export') {
    if (!run) throw Error('还没有采集结果。');
    return download(run);
  }
  throw Error('未知操作');
}

async function armPaced() {
  await chrome.alarms.create(PACED_ALARM,{delayInMinutes:1,periodInMinutes:1});
}
async function migratePaced() {
  const run=await load();
  if(run?.mode!=='paced') return;
  let dirty=false;
  if(run.scheduleVersion!==3 || run.scopeVersion!==1) {
    if(run.scopeVersion!==1) {
      const current=C.currentQuery(run);
      const oldQueries=new Map((run.queue || []).map(q=>[q.id,q]));
      run.queue=P.interleave(C.buildQueue(run.config)).map(q=>oldQueries.get(q.id) || q);
      const index=run.queue.findIndex(q=>q.id===current?.id);
      run.queueIndex=Math.max(0,index);run.query=run.queueIndex;
      if(index<0) {run.page=0;run.pageBatch=null;run.visit=null;}
      run.scopeVersion=1;
      dirty=true;
    }
    if(run.scheduleVersion!==3) {run.scheduleVersion=3;dirty=true;}
  }
  if(run.config.delay!==10 || run.config.pageDwell!==10) dirty=true;
  run.config.delay=10;run.config.pageDwell=10;
  // 老任务无损迁移：保留已采职位、分区队列与进度，仅把日目标/预算统一到 600。
  if(run.pacing.target!==P.DAILY_TARGET) {run.pacing.target=P.DAILY_TARGET;dirty=true;}
  if(run.config.maxJobs!==P.DAILY_TARGET) {run.config.maxJobs=P.DAILY_TARGET;dirty=true;}
  if(run.pacing.windowStart!==P.window().dayStart) dirty=true;
  run.pacing.windowStart=P.window().dayStart;
  const oldRate=(await chrome.storage.local.get('pacedRate')).pacedRate;
  if(!oldRate) await chrome.storage.local.set({pacedRate:{hour:P.window().hour,count:run.pacing.slotCount || 0,nextAt:Date.now()+72000}});
  if(run.pacing.slot!==P.slot(run.pacing)) {run.pacing.slot=P.slot(run.pacing);run.pacing.slotCount=0;dirty=true;}
  if(dirty && run.status==='running') {run.status='waiting';run.pacing.notBefore=Date.now();}
  if(dirty && run.status==='waiting' && /^今日有效职位已达到 200 条/.test(run.message || '')
      && await todayCount()<P.DAILY_TARGET) {
    run.pacing.notBefore=Date.now();run.pacing.nextPhase=null;
    run.message='每日目标已提升至 600 条，将保留当前队列继续采集。';
  }
  if(dirty) await save(run);
  if(run.status==='retrying') await chrome.alarms.create(RETRY_ALARM,{when:Math.max(Date.now()+1000,run.retryAt || 0)});
}
async function pacedError(error) {
  const run=await load();
  if(run?.mode==='paced' && run.status!=='paused') {
    return handle({type:'pause',runId:run.id,recoverable:true,reason:error.message},{tab:{id:run.tabId}});
  }
}
async function startPaced(defer = false) {
  const run=await load();
  if(run) {recoverLayoutCheckpoint(run);recoverFailedCheckpoint(run);}
  if(run?.mode==='paced') {
    if(run.status==='paused') {
      if(run.cooldownUntil && Date.now()<Date.parse(run.cooldownUntil)) throw Error(`访问频率冷却中，请在 ${new Date(run.cooldownUntil).toLocaleString()} 后再继续。`);
      if(/验证码|安全验证|安全检查|登录|challenge|checkpoint|authwall|human/i.test(String(run.message || ''))) throw Error('需要先在领英页面完成登录或安全验证，然后点击继续。');
      if(/(?:HTTP\s*)?429|too many requests|rate limit|请求过多|访问频率|请求频率/i.test(String(run.message || ''))) throw Error('访问限制任务只能在冷却结束后通过“继续暂停任务”恢复。');
      const tab=await findLinkedInTab();
      await chrome.storage.local.set({pacedEnabled:true});await armPaced();
      run.tabId=tab.id;run.status='waiting';run.pacing.notBefore=Date.now();
      run.message='已从暂停位置恢复，正在继续采集。';await save(run);
      if(defer) {await chrome.alarms.create(WAKE_ALARM,{when:Date.now()+1000});return run;}
      return pacedTick();
    }
    if(['running','waiting'].includes(run.status) && run.message==='搜索条件或页面已改变，采集已暂停。') {
      run.message=run.status==='waiting'?'已保存进度，等待下一次采集时刻。':'正在从保存的位置继续采集。';
      await save(run);
    }
    await chrome.storage.local.set({pacedEnabled:true}); await armPaced(); return run;
  }
  if(run && (['running','waiting','retrying'].includes(run.status) || (run.status==='paused' && !['已停止，进度已保存。','搜索条件或页面已改变，采集已暂停。'].includes(run.message)))) throw Error('已有任务，请先停止；验证或访问限制暂停必须先处理。');
  if(run?.cooldownUntil && Date.now()<Date.parse(run.cooldownUntil)) throw Error('访问限制冷却尚未结束。');
  if(run && Object.keys(run.jobs || {}).length) await download(run);
  await chrome.alarms.clear(DAILY_ALARM);
  const stored=await chrome.storage.local.get('schedule');
  if(stored.schedule) await chrome.storage.local.set({schedule:{...stored.schedule,enabled:false}});
  await chrome.storage.local.set({pacedEnabled:true}); await armPaced();
  return newPacedRun('backfill');
}
// One migration for checkpoints incorrectly failed by the old URL guard.
// Other failures, security gates, quotas and manual pauses remain unchanged.
function recoverLayoutCheckpoint(run) {
  const q=C.currentQuery(run);
  if(q?.status!=='failed' || q.layoutRecoveryVersion || q.lastError!=='搜索条件或页面已改变，采集已暂停。') return false;
  q.layoutRecoveryVersion=1;q.previousLayoutError={message:q.lastError,attempts:q.attempts};
  q.status='paused';q.attempts=0;
  return true;
}
function recoverFailedCheckpoint(run) {
  const q=C.currentQuery(run);
  if(q?.status!=='failed') return false;
  if(globalThis.JobaggControl?.requiresHuman({status:'paused',message:q.lastError})) {
    throw Error('该分区遇到登录、验证或访问限制，请先处理；错误与进度已保留。');
  }
  if(run.cooldownUntil && Date.now()<Date.parse(run.cooldownUntil)) throw Error('访问频率冷却尚未结束。');
  const existing=new Set(run.queue.map(item=>item.id));
  const children=C.splitQuery(q,run.config).filter(item=>!existing.has(item.id));
  const capacity=Math.max(0,run.config.maxQueries-run.queue.length);
  if(children.length && children.length<=capacity) {
    q.status='split';q.finishedAt=new Date().toISOString();
    run.queue.splice(run.queueIndex+1,0,...children);
    run.queueIndex++;
  } else {
    let next=-1;
    for(let offset=1;offset<run.queue.length;offset++) {
      const index=(run.queueIndex+offset)%run.queue.length;
      if(run.queue[index].status==='pending') {next=index;break;}
    }
    if(next<0) throw Error('可用分区均已处理，失败记录与职位已保留，请查看覆盖报告。');
    run.queueIndex=next;
  }
  run.query=run.queueIndex;run.page=0;run.pageBatch=null;run.visit=null;run.retryAttempts=0;
  return true;
}
async function newPacedRun(phase) {
  const old=await load();
  const checked=C.config({...LINKEDIN_PRESETS[phase==='backfill'?'all-occupations-backfill':'all-occupations-daily'],
    maxJobs:P.DAILY_TARGET,delay:10,pageDwell:10,cooldownMinutes:360});
  const now=Date.now();
  const run={id:crypto.randomUUID(),config:checked,tabId:null,status:'running',scheduleVersion:3,scopeVersion:1,query:0,queueIndex:0,page:0,
    jobs:{},queue:P.interleave(C.buildQueue(checked)),origin:'paced',mode:'paced',startedAt:new Date(now).toISOString(),
    pacing:{phase,target:checked.maxJobs,windowStart:P.window(now).dayStart,slot:P.slot({},now),slotCount:0,notBefore:now},
    message:'每日目标 600 条；北京时间 09:00–23:00，每小时最多 50 次详情，停留至少 10 秒。'};
  if(!run.queue.length) throw Error('没有可执行的查询分区。');
  // Rotate the starting occupation on each cycle, rather than always filling
  // the quota from the first few management searches in the catalog.
  if(old?.mode==='paced') {run.queueIndex=((old.queueIndex || 0)+1)%run.queue.length;run.query=run.queueIndex;}
  if(old) await chrome.storage.local.set({previousRun:old});
  markCurrent(run,'running'); await save(run);
  if(await pacedHold(run)) return run;
  const tab=await findLinkedInTab();run.tabId=tab.id;
  try {await navigate(run,C.searchUrl(run));}
  catch(error) {return handle({type:'pause',runId:run.id,recoverable:true,reason:`打开搜索失败：${error.message}`},{tab:{id:run.tabId}});}
  return run;
}
async function pacedCheckpoint(run) {
  if (globalThis.LinkedInSync && await LinkedInSync.configured()) {
    await LinkedInSync.capture(run);
    return;
  }
  // Download before allowing another cycle to replace these results.
  if(Object.keys(run.jobs).length && run.exportedCount!==Object.keys(run.jobs).length) {
    await download(run); run.exportedCount=Object.keys(run.jobs).length; await save(run);
  }
}

async function collectorStatus() {
  const run=await load();
  const sync=await LinkedInSync.summary();
  const human=JobaggControl.requiresHuman(run);
  return {platform:'linkedin',status:run?.status || 'idle',
    message:sync.syncError || run?.message || '点击一键开始，将自动创建采集页面。',
    collected:Object.keys(run?.jobs || {}).length,...sync,dailyTarget:P.DAILY_TARGET,todayCollected:await todayCount(),
    nextRunAt:run?.status==='retrying'?run.retryAt || null:run?.status==='waiting'?run.pacing?.notBefore || null:null,
    canResume:run?.status==='paused',requiresHuman:human,
    updatedAt:run?.updatedAt || null,page:(run?.page || 0)+1};
}
async function todayCount() {
  return P.countDaily((await chrome.storage.local.get('acceptedJobs')).acceptedJobs);
}
async function pacedHold(run) {
  const p=run.pacing, now=Date.now(), index=P.slot(p,now);
  if(!P.window(now).active) {
    await waitPaced(run,P.window(now).nextStart,'已保存当前进度，下一次北京时间 09:00 自动继续。');return true;
  }
  if(index!==p.slot) {p.slot=index;p.slotCount=0;}
  const dailyCount=await todayCount();
  const complete=dailyCount>=P.DAILY_TARGET;
  if(complete || p.slotCount>=P.allowance(p,index)) {
    run.status='waiting';
    p.nextPhase=null;
    p.notBefore=complete ? P.window(now).nextStart : P.window(now).nextHour;
    run.message=complete ? `今日有效职位已达到 ${P.DAILY_TARGET} 条，明天 09:00 自动继续。`
      : '本小时额度已用完，保留当前页，下一小时继续。';
    await waitPaced(run,p.notBefore,run.message); await pacedCheckpoint(run); return true;
  }
  return false;
}
async function pacedTick() {
  if(!(await chrome.storage.local.get('pacedEnabled')).pacedEnabled) return;
  const run=await load(); if(!run || run.mode!=='paced') return run;
  if(run.status==='waiting' && await reviewLinkedIn(run)) return load();
  if(run.status==='running') {
    if(await pacedHold(run)) return run;
    if(run.lastNavigationAt && Date.now()-Math.max(run.lastNavigationAt,run.lastActivityAt || 0)>120000) {
      return handle({type:'pause',runId:run.id,recoverable:true,reason:'页面脚本未完成，加载超时'}, {tab:{id:run.tabId}});
    }
    return run;
  }
  if(run.status!=='waiting') return run;
  if(Date.now()<run.pacing.notBefore) return run;
  if(!P.window().active) {await pacedHold(run);return run;}
  if(run.pacing.retryPending) {
    run.pacing.retryPending=false;run.status='retrying';await save(run);return retryPage();
  }
  await pacedCheckpoint(run);
  // 目标达成或跨午夜后，次日继续同一未完成队列：不重建、不重置各分区的下一页。
  // 只有全部分区真正耗尽（resetQueue）才进入新一轮，失败/受限不算成功。
  const startingNewRound = !!run.pacing.resetQueue;
  if(startingNewRound) {
    const history=(await chrome.storage.local.get('coverageHistory')).coverageHistory || [];
    history.push({startedAt:run.coverageRoundStartedAt || run.startedAt,finishedAt:new Date().toISOString(),
      queries:run.queue,failures:run.failures || {},cardFailures:run.cardFailures || []});
    await chrome.storage.local.set({coverageHistory:history.slice(-30)});
    run.queue=P.interleave(C.buildQueue(run.config));run.queueIndex=0;run.query=0;run.page=0;
    run.pageBatch=null;run.visit=null;run.pacing.resetQueue=false;
    run.coverageRoundStartedAt=new Date().toISOString();
  }
  run.pacing.nextPhase=null;
  run.pacing.windowStart=P.window(Date.now()).dayStart;
  if(await pacedHold(run)) return run;
  run.status='running';markCurrent(run,'running');
  const tab=await findLinkedInTab();run.tabId=tab.id;
  run.message=startingNewRound
    ? `上一轮分区报告已保留，开始新一轮采集（日目标 ${P.DAILY_TARGET} 条）；受限或失败不代表全量完成。`
    : '继续保留的查询队列，读取未完成分区的下一页。';
  await save(run);
  if(run.pageBatch) return nextDetail(run);
  await navigate(run,C.searchUrl(run));return run;
}

async function nextDetail(run) {
  if(await reviewLinkedIn(run)) {
    if((await load())?.status==='paused') return load();
  }
  if(run.mode==='paced' && await pacedHold(run)) return run;
  const batch=run.pageBatch;
  if(!batch) return run;
  const ledger=run.mode==='paced' ? (await chrome.storage.local.get('acceptedJobs')).acceptedJobs || {} : {};
  while(batch.index<batch.jobs.length && (P.fresh(run.jobs[batch.jobs[batch.index].source_job_id]?.collected_at) || P.fresh(ledger[batch.jobs[batch.index].source_job_id]))) batch.index++;
  if(batch.index>=batch.jobs.length || (run.mode!=='paced' && Object.keys(run.jobs).length>=run.config.maxJobs)) {
    run.pageBatch=null;run.visit=null;await save(run);
    return handle({type:'advance',runId:run.id,last:batch.last,resultCount:batch.resultCount},{tab:{id:run.tabId}});
  }
  run.visit=batch.jobs[batch.index];
  if(run.mode==='paced' && !await reserveDetail(run)) return run;
  run.message=`自动读取本页第 ${batch.index+1}/${batch.jobs.length} 个职位：${run.visit.title}`;
  await save(run);
  try {await navigate(run,run.visit.canonical_url);}
  catch(error) {return handle({type:'pause',runId:run.id,recoverable:true,reason:`打开详情失败：${error.message}`},{tab:{id:run.tabId}});}
  return run;
}

async function watchdogTick() {
  const run=await load();
  if(!run || run.mode==='paced' || run.status!=='running' || !run.lastNavigationAt) return run;
  if(Date.now()-Math.max(run.lastNavigationAt,run.lastActivityAt || 0)<=120000) return run;
  return handle({type:'pause',runId:run.id,recoverable:true,reason:'页面长时间没有响应，可能白屏'}, {tab:{id:run.tabId}});
}

async function retryPage() {
  const run=await load();
  if(!run || run.status!=='retrying' || Date.now()<run.retryAt) return run;
  if(run.cooldownUntil && Date.now()<Date.parse(run.cooldownUntil)) return run;
  if(run.mode==='paced') {
    run.pacing.retryPending=true;
    if(await pacedHold(run) || (run.visit && !await reserveDetail(run))) return run;
    run.pacing.retryPending=false;
  }
  run.status='running';markCurrent(run,'running');
  if(run.retryAction==='nextDetail') {
    delete run.retryAction;run.message='已保留失败职位，正在继续本页剩余队列。';await save(run);return nextDetail(run);
  }
  delete run.retryAction;
  run.message='正在自动重试当前页面…';await save(run);
  try {await navigate(run,run.visit?.canonical_url || C.searchUrl(run));}
  catch(error) {return handle({type:'pause',runId:run.id,recoverable:true,reason:`采集标签页暂时不可用：${error.message}`},{tab:{id:run.tabId}});}
  return run;
}
async function exhaustRetry(run) {
  const failure={...(run.lastFailure || {reason:'旧版页面加载反复超时',stage:run.visit?'detail':'search'}),
    attempts:run.retryAttempts,at:new Date().toISOString(),page:run.page,queryId:C.currentQuery(run)?.id};
  const q=C.currentQuery(run);
  try {
    if(run.visit && run.pageBatch) {
      const expected=run.pageBatch.jobs[run.pageBatch.index];
      if(!expected || String(expected.source_job_id)!==String(run.visit.source_job_id)) throw Error('保存的详情队列不一致，已暂停并保留所有记录。');
      run.failures ||= {};
      run.failures[String(run.visit.source_job_id)]={...failure,job:{...run.visit}};
      run.pageBatch.index++;run.visit=null;run.retryAction='nextDetail';
    } else {
      if(!q) throw Error('没有可继续的查询分区，已保留全部记录。');
      q.status='failed';q.attempts=failure.attempts;q.lastError=failure.reason;q.lastFailure=failure;
      recoverFailedCheckpoint(run);run.retryAction='query';
    }
    run.retryAttempts=0;run.status='retrying';run.retryAt=Date.now()+120000;
    run.message='当前项已达到重试上限，失败记录已保留；2 分钟后继续其他待处理项。';
    await save(run);await chrome.alarms.create(RETRY_ALARM,{when:run.retryAt});
  } catch(error) {
    run.status='paused';run.message=error.message;await save(run);
    await chrome.alarms.clear(RETRY_ALARM);
  }
  return run;
}
async function migrateStalledRetry() {
  const run=await load();
  if(run?.status==='retrying' && (run.retryAttempts || 0)>run.config.maxRetries) {
    if((run.cooldownUntil && Date.now()<Date.parse(run.cooldownUntil))
        || JobaggControl.requiresHuman({status:'paused',message:run.lastFailure?.reason || run.message})) {
      run.status='paused';run.message=run.lastFailure?.reason || run.message;
      await save(run);await chrome.alarms.clear(RETRY_ALARM);return run;
    }
    return exhaustRetry(run);
  }
  return run;
}
async function pacedAdvance(run,m) {
  if(await pacedHold(run)) return run;
  const q=C.currentQuery(run);
  q.page=run.page;
  q.resultCount=m.resultCount===null ? null : Number(m.resultCount);
  // Rotate after a complete page; each pending partition retains its next page.
  if(m.last || run.page+1>=run.config.maxPages) {
    q.status=run.page+1>=run.config.maxPages?'limited':'done';q.finishedAt=new Date().toISOString();
  } else {
    q.status='pending';q.page=run.page+1;
  }
  let next=-1;
  for(let offset=1;offset<=run.queue.length;offset++) {
    const index=(run.queueIndex+offset)%run.queue.length;
    if(run.queue[index].status==='pending') {next=index;break;}
  }
  if(next<0) {
    // An exhausted search is a shortfall, never a successful 1000-job backfill.
    run.pacing.resetQueue=true;
    run.status='waiting';run.pacing.notBefore=Date.now()+6*P.HOUR;
    run.message=`本轮查询耗尽，有效 ${P.count(run)}/${run.pacing.target} 条，6 小时后再检查新增职位。`;
    await save(run);await pacedCheckpoint(run);return run;
  }
  run.queueIndex=next;run.query=next;run.page=run.queue[next].page || 0;
  run.message=`轮流推进分区 ${next+1}/${run.queue.length}，第 ${run.page+1} 页；保留其他分区页码。`;
  markCurrent(run,'running');await save(run);
  await navigate(run,C.searchUrl(run));return run;
}
