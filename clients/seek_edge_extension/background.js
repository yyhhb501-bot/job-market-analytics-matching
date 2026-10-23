importScripts('core.js', 'schedule.js', 'lifecycle.js', 'controller.js');
const C = globalThis.SeekCollector;
const S = globalThis.SeekSchedule;
const CONTINUOUS_ALARM = 'seek-continuous-run';
const SEARCH_URL = 'https://au.seek.com/Registered-Nurse-jobs?daterange=7&sortmode=ListedDate';
const CONTINUOUS_INTERVAL_MINUTES = 1.2;
const RECOVERY_BASE_MS = 2 * 60000;
const RECOVERY_MAX_MS = 30 * 60000;
let tickBusy = false;
let progressFlight = null;

async function liveProgress() {
  const cached=(await chrome.storage.local.get('seekLiveProgress')).seekLiveProgress;
  if(cached?.attemptedAt && Date.now()-cached.attemptedAt<60000) return progressView(cached);
  if(progressFlight) return progressFlight;
  progressFlight=(async()=>{
    const state={...cached,attemptedAt:Date.now()};
    try {
      const {apiUrl,token}=await loadSettings();
      const response=await fetch(`${apiUrl}/api/v1/import/seek/progress`,{
        headers:{Authorization:`Bearer ${token}`},signal:AbortSignal.timeout(15000)});
      if(!response.ok) throw Error([401,403].includes(response.status)?'设备连接已失效，请重新连接。':'进度服务暂不可用。');
      const value=await response.json();
      if(!Number.isInteger(value.today_valid) || value.today_valid<0 || !Number.isInteger(value.today_target)
          || value.today_target<=0 || !Number.isInteger(value.hour_valid) || !Number.isInteger(value.hour_limit)) throw Error('进度响应不完整。');
      state.value=value;state.checkedAt=Date.now();state.error=null;
    } catch(error) {state.error=/设备连接已失效/.test(error.message)?error.message:'今日进度暂时无法核对，历史回执不代表今日采集。';}
    await chrome.storage.local.set({seekLiveProgress:state});return progressView(state);
  })().finally(()=>{progressFlight=null;});
  return progressFlight;
}
function progressView(state) {
  const day=value=>Math.floor((value+8*3600000)/86400000);
  const checkedAt=state?.checkedAt;
  const age=Date.now()-checkedAt;
  const fresh=!!state?.value && !state.error && age>=0 && age<60000 && day(checkedAt)===day(Date.now());
  return {value:state?.value || null,checkedAt:checkedAt || null,fresh,error:state?.error || null};
}

async function reviewSeek(run, allowNew=true) {
  if (!globalThis.JobLifecycle) return false;
  return globalThis.JobLifecycle.run({source:'seek_user_import',allowNew,intervalMs:3600000,
    candidates:async()=>Object.entries((await chrome.storage.local.get('seenJobIds')).seenJobIds || {})
      .map(([id,seen])=>({id,seen})),
    reserve:async()=>{
      const w=S.window(), rate=(await chrome.storage.local.get('seekRate')).seekRate || {};
      if(rate.hour!==w.hour) {rate.hour=w.hour;rate.count=0;}
      if(!w.active || rate.count>=50 || Date.now()<(rate.nextAt || 0)) return false;
      rate.count++;rate.nextAt=Date.now()+S.interval;
      await chrome.storage.local.set({seekRate:rate});return true;
    },
    pause:pauseRun,
    deliver:async observation=>{
      const {apiUrl,token}=await loadSettings();
      const response=await fetch(`${apiUrl}/api/v1/import/observations`,{method:'POST',
        headers:{'Content-Type':'application/json','Authorization':`Bearer ${token}`},
        body:JSON.stringify({observations:[observation]}),signal:AbortSignal.timeout(15000)});
      if(!response.ok) throw Error(`复查状态同步失败：HTTP ${response.status}`);
    }});
}

// De-duplicate recent reads, but revisit listings on later daily passes.
function recentlySeen(value) {
  const checked = Date.parse(value);
  return Number.isFinite(checked) && Date.now() - checked < 86400000;
}

function needsHuman(reason) {
  return /验证|captcha|cloudflare|安全检查|challenge|登录|sign in|429|rate limit|访问频率|请求过多|离开搜索结果页|搜索条件或页面已改变/i.test(String(reason || ''));
}

async function recoverRun(run, reason) {
  if (needsHuman(reason)) return pauseRun(reason);
  const current = await runState();
  if (!current || current.id !== run.id || current.status === 'paused') return current;
  run.recoveryAttempts = (run.recoveryAttempts || 0) + 1;
  const delay = Math.min(RECOVERY_MAX_MS, RECOVERY_BASE_MS * 2 ** Math.min(run.recoveryAttempts - 1, 4));
  run.status = 'waiting';
  run.waitUntil = Date.now() + delay;
  run.recoveryPending = true;
  run.message = `${reason}；${Math.round(delay / 60000)} 分钟后自动刷新并继续。`;
  return saveRun(run);
}

function searchPageUrl(value) {
  const url = new URL(value);
  url.searchParams.delete('jobId');
  url.searchParams.delete('type');
  url.hash = '';
  return url.href;
}

async function runState() {
  return (await chrome.storage.local.get('continuousRun')).continuousRun || null;
}

async function saveRun(run) {
  const current = await runState();
  if (current?.id !== run.id || current.status === 'paused') return current;
  const rate = (await chrome.storage.local.get('seekRate')).seekRate;
  if (run.status === 'running') run.nextTickAt = Math.max(Date.now() + 1000,
    run.pendingDetail?.nextCheckAt || rate?.nextAt || Date.now() + S.interval);
  run.updatedAt=new Date().toISOString();
  await chrome.storage.local.set({continuousRun: run});
  if (['running', 'waiting'].includes(run.status)) {
    await chrome.alarms.create('seek-next-detail', {when: Math.max(Date.now() + 1000, run.status === 'waiting' ? run.waitUntil : run.nextTickAt)});
  }
  return run;
}

async function pauseRun(reason) {
  const run = await runState();
  if (!run) return null;
  run.status = 'paused';
  run.message = reason;
  run.updatedAt = new Date().toISOString();
  run.nextTickAt = null;
  await chrome.storage.local.set({continuousRun: run});
  await chrome.alarms.clear(CONTINUOUS_ALARM);
  return run;
}

async function loadSettings() {
  const stored = await chrome.storage.local.get(['apiUrl', 'deviceToken']);
  const apiUrl = stored.apiUrl === 'http://localhost:8000' ? 'http://localhost:8010' : stored.apiUrl;
  if (apiUrl !== stored.apiUrl) await chrome.storage.local.set({apiUrl});
  return C.config({apiUrl, token: stored.deviceToken});
}

async function upload(jobs, pageUrl, stableKey) {
  const {apiUrl, token} = await loadSettings();
  const candidates = jobs.slice(0, 10).map(job => ({...job,
    raw_payload: {...job.raw_payload, collection_scope: 'registered_nurse'}}));
  const valid = candidates.filter(job => C.valid(job));
  const locallyRejected = candidates.length - valid.length;
  const fresh = [];
  const seen = (await chrome.storage.local.get('seenJobIds')).seenJobIds || {};
  for (const job of valid) if (!recentlySeen(seen[job.source_job_id])) fresh.push(job);
  if (!fresh.length) return {skipped: candidates.length, rejected_local: locallyRejected, message: locallyRejected ? `本页没有符合规则的完整职位（本地跳过 ${locallyRejected} 条）。` : '这些职位此前已经上传。'};
  const key = stableKey || `seek-${crypto.randomUUID()}`;
  const response = await fetch(`${apiUrl}/api/v1/import/jobs`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`, 'Idempotency-Key': key},
    body: JSON.stringify({source: 'seek_user_import', query: String(pageUrl || '').slice(0, 300), jobs: fresh}),
    signal: AbortSignal.timeout(15000)
  });
  if ([401, 403, 429].includes(response.status)) {
    throw Error(response.status === 429 ? '导入 API 请求过多，请稍后重试。' : '设备令牌无效、已撤销或没有权限。');
  }
  if (!response.ok) throw Error(`导入失败：HTTP ${response.status}`);
  const result = await response.json();
  if(result.received_count!==fresh.length ||
    result.accepted_count+result.duplicate_count+result.rejected_count!==fresh.length) {
    throw Error('入库服务未确认完整接收，详情已保留等待重试。');
  }
  const rejectedIndexes = new Set((result.errors || []).map(error => error.index));
  // Only acknowledge accepted items; an incomplete error list must not hide failures.
  if (!result.rejected_count || rejectedIndexes.size === result.rejected_count) {
    fresh.forEach((job, index) => {
      if (!rejectedIndexes.has(index)) seen[job.source_job_id] = new Date().toISOString();
    });
  }
  const entries = Object.entries(seen).sort((a, b) => String(b[1]).localeCompare(String(a[1]))).slice(0, 10000);
  await chrome.storage.local.set({seenJobIds: Object.fromEntries(entries), lastResult: result});
  return {...result, uploaded: fresh.length, skipped: candidates.length - fresh.length, rejected_local: locallyRejected};
}

async function collectFromTab(tabId, type = 'collectCurrentSeekPage', extra = {}, timeoutMs = 180000) {
  try {
    return await sourceReply(chrome.tabs.sendMessage(tabId, {type, ...extra}),timeoutMs);
  } catch (error) {
    if(!/Receiving end does not exist|Could not establish connection|Extension context invalidated/i.test(error.message || '')) throw error;
    // A tab that was already open when the extension was reloaded may not yet
    // have a content script. Inject it once on the user's explicit click.
    await sourceReply(chrome.scripting.executeScript({target: {tabId}, files: ['core.js', 'content.js']}),timeoutMs);
    return sourceReply(chrome.tabs.sendMessage(tabId, {type, ...extra}),timeoutMs);
  }
}
async function sourceReply(operation, timeoutMs = 180000) {
  let timer;
  try {return await Promise.race([operation,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('SEEK 页面响应超时，进度已保留。')),timeoutMs);})]);}
  finally {clearTimeout(timer);}
}

function waitForTab(tabId, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { chrome.tabs.onUpdated.removeListener(onUpdated); reject(Error('职位页面加载超时。')); }, timeoutMs);
    function onUpdated(updatedId, changeInfo) {
      if (updatedId !== tabId || changeInfo.status !== 'complete') return;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      resolve();
    }
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.get(tabId).then(tab => {
      if (tab.status === 'complete') {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(onUpdated);
        resolve();
      }
    }).catch(error => { clearTimeout(timer); chrome.tabs.onUpdated.removeListener(onUpdated); reject(error); });
  });
}

async function collectRecommendations(tabId) {
  const listing = await collectFromTab(tabId, 'listRecommendedSeekJobs');
  if (!listing?.ok) throw Error(listing?.error || '无法读取首页推荐职位。');
  if (!listing.jobs?.length) throw Error('首页推荐区没有读到有效职位链接。');
  const jobs = [];
  const failures = [];
  for (const candidate of listing.jobs) {
    let detailTab;
    try {
      detailTab = await chrome.tabs.create({url: candidate.url, active: false});
      await waitForTab(detailTab.id);
      const result = await collectFromTab(detailTab.id);
      await new Promise(resolve => setTimeout(resolve, 10000));
      if (!result?.ok) {
        if (/验证|429|访问频率|登录/.test(result?.error || '')) throw Error(result.error);
        failures.push(`${C.jobId(candidate.url)}：${result?.error || '详情不可用'}`);
      } else {
        const job = result.jobs.find(item => item.source_job_id === C.jobId(candidate.url));
        if (job) jobs.push(job);
        else failures.push(`${C.jobId(candidate.url)}：详情职位 ID 不匹配`);
      }
    } catch (error) {
      if (/验证|429|访问频率|登录/.test(error.message)) throw error;
      failures.push(`${C.jobId(candidate.url)}：${error.message}`);
    } finally {
      if (detailTab?.id) await chrome.tabs.remove(detailTab.id).catch(() => {});
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  if (!jobs.length) throw Error(`推荐职位详情均未能提取：${failures.slice(0, 2).join('；')}`);
  const uploaded = await upload(jobs, listing.pageUrl);
  return {...uploaded, attempted: listing.jobs.length, failures};
}

async function waitForSearchResults(tabId) {
  const deadline = Date.now() + 15000;
  let listing;
  while (Date.now() < deadline) {
    listing = await collectFromTab(tabId, 'listSearchSeekJobs',{},8000);
    if (!listing?.ok || (listing.cardCount > 0 && listing.readableCardCount === listing.cardCount)) return listing;
    await new Promise(resolve => setTimeout(resolve, 750));
  }
  return {ok: false, error: '搜索结果标题未完整加载，已停止翻页；请稍后继续。'};
}

async function advanceSearchPage(run, listing, seen) {
  run.recoveryAttempts = 0;
  if (!S.window().active) {
    run.status = 'waiting';
    run.waitUntil = S.window().nextStart;
    run.message = '已到 23:00，明天 09:00 从当前进度继续。';
    return saveRun(run);
  }
  const matchedCount = listing.jobs.length;
  const handledCount = listing.jobs.filter(job => run.attemptedIds.includes(job.id) || recentlySeen(seen[job.id])).length;
  const next = listing.nextPageUrl;
  if (!next || !C.seekUrl(next)) {
    run.status = 'waiting';
    const nextCheck = Date.now() + 30 * 60000;
    run.waitUntil = S.window(nextCheck).active ? nextCheck : S.window(nextCheck).nextStart;
    run.page = 1;
    const first = new URL(run.pageUrl);
    first.searchParams.delete('page');
    run.pageUrl = first.href;
    run.attemptedIds = [];
    run.pageMatched = 0;
    run.pageProcessed = 0;
    run.message = `本页 ${handledCount}/${matchedCount} 条已处理；本轮搜索结束，将于 ${new Date(run.waitUntil).toLocaleString()} 重新检查新增职位。`;
  } else {
    run.page += 1;
    run.pageUrl = searchPageUrl(next);
    await chrome.tabs.update(run.tabId, {url: run.pageUrl});
    await waitForTab(run.tabId);
    run.pageMatched = 0;
    run.pageProcessed = 0;
    run.message = `本页 ${handledCount}/${matchedCount} 条已处理，已自动翻到第 ${run.page} 页；下一次自动采集。`;
  }
  run.updatedAt = new Date().toISOString();
  return saveRun(run);
}

function sameDetailUrl(value, id) {
  try {const url=new URL(value);return !!C.seekUrl(value) && url.pathname.replace(/\/$/,'')===`/job/${id}`;}
  catch {return false;}
}
async function closeOwnedDetail(item) {
  if(!item?.tabId) return;
  const tab=await chrome.tabs.get(item.tabId).catch(()=>null);
  if(tab && sameDetailUrl(tab.url,item.id)) await chrome.tabs.remove(item.tabId).catch(()=>{});
}
async function detailFailure(run, reason) {
  const item=run.pendingDetail;
  if(needsHuman(reason)) return pauseRun(reason);
  const failures=(await chrome.storage.local.get('seekDetailFailures')).seekDetailFailures || {};
  const previous=failures[item.id];
  failures[item.id]={id:item.id,title:item.title,url:item.url,pageUrl:item.pageUrl,
    attempts:(previous?.attempts || 0)+1,error:reason,failedAt:new Date().toISOString()};
  await chrome.storage.local.set({seekDetailFailures:failures});
  await closeOwnedDetail(item);
  run.pendingDetail=null;run.failed=(run.failed || 0)+1;
  if(failures[item.id].attempts>=2) {
    if(!run.attemptedIds.includes(item.id)) run.attemptedIds.push(item.id);
    run.status='running';run.waitUntil=null;run.recoveryPending=false;
    run.message=`职位 ${item.id} 两次未能读取完整详情，已保留失败报告，继续本页其他职位。`;
    return saveRun(run);
  }
  return recoverRun(run,reason);
}
async function readPendingDetail(run) {
  const item=run.pendingDetail;
  if(item.nextCheckAt && Date.now()<item.nextCheckAt) return saveRun(run);
  let tab=item.tabId?await chrome.tabs.get(item.tabId).catch(()=>null):null;
  if(!tab) {
    // A closed detail is not silently reopened under the same access reservation.
    if(item.tabId) return detailFailure(run,'采集详情页已关闭，保存进度后重试。');
    tab=await chrome.tabs.create({url:item.url,active:false});item.tabId=tab.id;
    run.message=`正在打开职位 ${item.id} 的完整详情。`;await saveRun(run);
  }
  // tabs.create can resolve before Chrome assigns url (only pendingUrl exists).
  // Wait for this owned navigation without mistaking it for a user page change.
  if(!tab.url || tab.url==='about:blank' || (tab.status==='loading' && sameDetailUrl(tab.pendingUrl,item.id))) {
    if(Date.now()>=item.deadline) return detailFailure(run,'职位详情页导航超时。');
    item.nextCheckAt=Date.now()+5000;run.message=`正在加载职位 ${item.id} 的详情页。`;
    return saveRun(run);
  }
  if(!sameDetailUrl(tab.url,item.id)) {
    const check=await collectFromTab(tab.id,'checkSeekPage',{},8000).catch(()=>null);
    return pauseRun(check && !check.ok?check.error:'采集详情页已改变，请检查后继续；当前进度已保留。');
  }
  let result;
  try {result=await collectFromTab(tab.id,'collectCurrentSeekPage',{},8000);}
  catch(error) {result={ok:false,error:error.message};}
  const current=await runState();
  if(current?.id!==run.id || current.status==='paused') return current;
  if(needsHuman(result?.error)) return pauseRun(result.error);
  const job=result?.ok && sameDetailUrl(result.pageUrl,item.id)
    ? result.jobs?.find(job=>String(job.source_job_id)===item.id):null;
  const complete=job && String(job.title || '').trim().toLowerCase()===item.title.trim().toLowerCase()
    && job.company && (job.city || job.state) && String(job.description || '').trim().length>=120;
  if(!complete) {
    if(Date.now()>=item.deadline) return detailFailure(run,result?.error || '详情字段或职位 ID / 标题未能核对完整。');
    item.readyAt=null;item.nextCheckAt=Date.now()+5000;
    run.message=`正在等待职位 ${item.id} 的完整详情；已保留第 ${run.page} 页进度。`;
    return saveRun(run);
  }
  if(!item.readyAt) {
    item.readyAt=Date.now();item.nextCheckAt=Date.now()+10000;
    run.message=`职位 ${item.id} 详情已完整读取，正在停留核验。`;
    return saveRun(run);
  }
  if(Date.now()-item.readyAt<10000) {item.nextCheckAt=item.readyAt+10000;return saveRun(run);}
  // Persist the upload outbox before disposing of the extension-owned detail tab.
  run.lastDetailAt=new Date().toISOString();
  run.pendingUpload={job,pageUrl:item.pageUrl,id:item.id,title:item.title,key:`seek-${crypto.randomUUID()}`};
  run.pendingDetail=null;await saveRun(run);await closeOwnedDetail(item);
  const saved=await flushPendingUpload(run);
  if(!saved || saved.pendingUpload || saved.status==='paused') return saved;
  const listing=item.listing,seen=(await chrome.storage.local.get('seenJobIds')).seenJobIds || {};
  run=saved;
  if(listing && run.pageUrl===item.pageUrl) {
    run.pageProcessed=listing.jobs.filter(job=>run.attemptedIds.includes(job.id) || recentlySeen(seen[job.id])).length;
    if(run.status==='running' && run.pageProcessed===run.pageMatched && S.window().active) {
      const check=await collectFromTab(run.tabId,'checkSeekPage',{},8000);
      if(!check?.ok) return recoverRun(run,check?.error || 'SEEK 搜索页尚未恢复。');
      return advanceSearchPage(run,listing,seen);
    }
  }
  return saveRun(run);
}

async function continuousTick() {
  if (tickBusy) return runState();
  tickBusy = true;
  try {
    let run = await runState();
    if (!run || run.status === 'paused') return run;
    if(run.pendingUpload) {
      if(run.uploadRetryAt && Date.now()<run.uploadRetryAt) return run;
      return await flushPendingUpload(run);
    }
    const window = S.window();
    if (!window.active) {
      run.status = 'waiting';
      run.waitUntil = Math.max(run.waitUntil || 0, window.nextStart);
      run.message = '每日北京时间 09:00–23:00 自动采集，已保存当前页进度。';
      return saveRun(run);
    }
    // Finish an already reserved detail before considering a new access or review.
    if(run.pendingDetail) {
      if(run.status==='waiting' && Date.now()<(run.waitUntil || 0)) return run;
      run.status='running';run.waitUntil=null;return await readPendingDetail(run);
    }
    // Deliver saved observations even while pacing, without opening more review pages.
    await reviewSeek(run,false);
    if (run.status === 'waiting') {
      if (Date.now() < run.waitUntil) return run;
      run.status = 'running';
      run.waitUntil = null;
    }
    const rate = (await chrome.storage.local.get('seekRate')).seekRate || {};
    if (rate.hour !== window.hour) { rate.hour = window.hour; rate.count = 0; }
    if (rate.count >= 50 || Date.now() < (rate.nextAt || 0)) {
      run.status = 'waiting';
      run.waitUntil = rate.count >= 50 ? window.nextHour : rate.nextAt;
      run.message = `本小时已读取 ${rate.count}/50 条，等待下一采集时刻。`;
      return saveRun(run);
    }
    const dayStart=Math.floor((Date.now()+8*3600000)/86400000)*86400000-8*3600000;
    const mainProgress=Date.parse(run.lastDetailAt || run.lastSyncAt || '')>=dayStart;
    if(mainProgress && await reviewSeek(run)) return runState();
    let tab = run.tabId ? await chrome.tabs.get(run.tabId).catch(() => null) : null;
    if (!tab) {
      tab = await chrome.tabs.create({url: run.pageUrl, active: false});
      run.tabId = tab.id;
      run.recoveryPending = false;
      await saveRun(run);
      await waitForTab(tab.id);
    }
    if (run.recoveryPending) {
      if (C.seekUrl(tab.url)) {
        const preflight = await collectFromTab(run.tabId, 'checkSeekPage',{},8000).catch(() => null);
        if (preflight && !preflight.ok && needsHuman(preflight.error)) return pauseRun(preflight.error);
        await chrome.tabs.reload(run.tabId);
      } else if (/^(?:chrome-error:|about:blank|about:newtab)/i.test(tab.url || '')) {
        await chrome.tabs.update(run.tabId, {url: run.pageUrl});
      } else {
        // Never replace a page the user is using for something else.
        const fresh = await chrome.tabs.create({url:run.pageUrl,active:false});
        run.tabId = fresh.id;
      }
      await waitForTab(run.tabId);
      tab = await chrome.tabs.get(run.tabId);
      run.recoveryPending = false;
      await saveRun(run);
    }
    if (!C.seekUrl(tab.url)) {
      const fresh=await chrome.tabs.create({url:run.pageUrl,active:false});
      run.tabId=fresh.id;
      await saveRun(run);await waitForTab(fresh.id);tab=await chrome.tabs.get(fresh.id);
    }
    const check = await collectFromTab(run.tabId, 'checkSeekPage',{},8000);
    if (!check?.ok) return recoverRun(run, check?.error || 'SEEK 页面尚未恢复。');
    if (searchPageUrl(tab.url) !== run.pageUrl) {
      await chrome.tabs.update(run.tabId, {url: run.pageUrl});
      await waitForTab(run.tabId);
    }
    const listing = await waitForSearchResults(run.tabId);
    if (!listing?.ok) return recoverRun(run, listing?.error || 'SEEK 搜索页尚未加载。');
    if (!listing.jobs?.length && !listing.nextPageUrl) {
      return recoverRun(run, '当前页面没有读到搜索结果，可能暂时白屏');
    }
    listing.jobs = listing.jobs.filter(job => C.registeredNurseTitle(job.title));
    const seen = (await chrome.storage.local.get('seenJobIds')).seenJobIds || {};
    run.pageMatched = listing.jobs.length;
    run.pageProcessed = listing.jobs.filter(job => run.attemptedIds.includes(job.id) || recentlySeen(seen[job.id])).length;
    const candidate = listing.jobs.find(job => !run.attemptedIds.includes(job.id) && !recentlySeen(seen[job.id]));
    if (!candidate) {
      return await advanceSearchPage(run, listing, seen);
    }
    // Persist the reservation and detail checkpoint together before opening a page.
    const latest=await runState();
    if(latest?.id!==run.id || latest.status==='paused') return latest;
    rate.count += 1;
    rate.nextAt = Date.now() + S.interval;
    run.pendingDetail={id:String(candidate.id),title:candidate.title,url:`https://au.seek.com/job/${candidate.id}`,
      pageUrl:run.pageUrl,listing,deadline:Date.now()+90000,reservedAt:Date.now(),tabId:null,nextCheckAt:Date.now()};
    run.message=`已保存第 ${run.page} 页进度，准备读取职位 ${candidate.id}。`;
    await chrome.storage.local.set({seekRate:rate,continuousRun:run});
    return await readPendingDetail(run);
  } catch (error) {
    const run = await runState();
    return run ? recoverRun(run, error.message || '页面加载失败') : null;
  } finally {
    tickBusy = false;
  }
}

async function flushPendingUpload(run) {
  const item=run.pendingUpload;
  if(!item) return run;
  try {
    const uploaded=await upload([item.job],item.pageUrl,item.key);
    const latest=await runState();
    if(latest?.id!==run.id) return latest;
    // A pause during an HTTP request must survive its eventual response.
    const paused=latest.status==='paused';
    Object.assign(run,latest);
    if((uploaded.errors || []).some(error=>/quota reached|hourly_limit_reached|daily_target_reached/i.test(error.reason))) {
      // A quota refusal is a known negative receipt, so retry next window with a new key.
      run.pendingUpload.key=`seek-${crypto.randomUUID()}`;
      run.uploadRetryAt=uploaded.progress?.next_run_at?Date.parse(uploaded.progress.next_run_at):S.window().nextHour;
      if(uploaded.progress?.status==='done') run.uploadRetryAt=S.window().nextStart;
      run.waitUntil=run.uploadRetryAt;
      if(!paused) {run.status='waiting';run.message='入库额度已满，详情已保留，下一时段自动同步。';}
      await chrome.storage.local.set({continuousRun:run});
      if(!paused) await saveRun(run);
      return run;
    }
    if(!run.attemptedIds.includes(item.id)) run.attemptedIds.push(item.id);
    run.accepted=(run.accepted || 0)+(uploaded.accepted_count || 0);
    run.duplicates=(run.duplicates || 0)+(uploaded.duplicate_count || 0);
    run.rejected=(run.rejected || 0)+(uploaded.rejected_count || 0)+(uploaded.rejected_local || 0);
    run.lastResult=uploaded;run.recoveryAttempts=0;run.uploadAttempts=0;run.uploadRetryAt=null;
    run.pendingUpload=null;
    if((uploaded.accepted_count || 0)+(uploaded.duplicate_count || 0)>0) run.lastSyncAt=new Date().toISOString();
    if(uploaded.rejected_count || uploaded.rejected_local) {
      const {seekRejectedJobs={}}=await chrome.storage.local.get('seekRejectedJobs');
      seekRejectedJobs[item.id]={...item,errors:uploaded.errors || [],rejectedAt:new Date().toISOString()};
      await chrome.storage.local.set({seekRejectedJobs});
    }
    if(!paused) {
      run.status='running';run.waitUntil=null;
      run.message=`${item.title}：已入库 ${uploaded.accepted_count || 0}，重复 ${uploaded.duplicate_count || 0}，不合格 ${(uploaded.rejected_count || 0)+(uploaded.rejected_local || 0)}。`;
      if(uploaded.progress?.status==='waiting' || uploaded.progress?.status==='done') {
        run.status='waiting';run.waitUntil=uploaded.progress.status==='done'?S.window().nextStart:
          Date.parse(uploaded.progress.next_run_at) || Date.now()+3600000;
      }
    }
    // Save even while paused; only acknowledged upload state advances.
    run.updatedAt=new Date().toISOString();
    await chrome.storage.local.set({continuousRun:run});
    if(!paused) await saveRun(run);
    return run;
  } catch(error) {
    const latest=await runState();
    if(latest?.id!==run.id || latest.status==='paused') return latest;
    Object.assign(run,latest);
    run.uploadAttempts=(run.uploadAttempts || 0)+1;
    run.uploadRetryAt=Date.now()+Math.min(1800000,30000*2**Math.min(run.uploadAttempts,6));
    run.status='waiting';run.waitUntil=run.uploadRetryAt;
    run.message='详情已保存，入库服务暂不可用；稍后自动重试，无需重新读取职位。';
    if(/令牌|权限/.test(error.message)) {
      run.status='paused';run.message='设备连接已失效，请在控制台重新连接。';
    }
    await chrome.storage.local.set({continuousRun:run});
    if(run.status!=='paused') await saveRun(run);
    return run;
  }
}

chrome.alarms.onAlarm.addListener(alarm => {
  if ([CONTINUOUS_ALARM, 'seek-daily-start', 'seek-next-detail'].includes(alarm.name)) {
    continuousTick();
    if (alarm.name === 'seek-daily-start') chrome.alarms.create('seek-daily-start', {when:S.window().nextStart});
  }
});

async function restoreContinuousAlarm() {
  const run = await runState();
  if (!run || !['running', 'waiting'].includes(run.status)) return;
  await chrome.alarms.create('seek-daily-start', {when:S.window().nextStart});
  await chrome.alarms.create(CONTINUOUS_ALARM, {
    delayInMinutes: CONTINUOUS_INTERVAL_MINUTES,
    periodInMinutes: CONTINUOUS_INTERVAL_MINUTES
  });
}

async function collectManual(type) {
  const [activeTab] = await chrome.tabs.query({active: true, currentWindow: true});
  const run = type === 'collectVisibleAndUpload' ? await runState() : null;
  const runTab = run && ['running', 'waiting'].includes(run.status)
    ? await chrome.tabs.get(run.tabId).catch(() => null) : null;
  const useRunTab = !!runTab && C.seekUrl(runTab.url)
    && /-jobs(?:\/|$)/i.test(new URL(runTab.url).pathname);
  const tab = useRunTab ? runTab : activeTab;
  if (!tab?.id || !C.seekUrl(tab.url)) throw Error('请先打开 seek.com.au 的搜索结果页或职位详情页。');
  if (useRunTab && tickBusy) throw Error('连续任务正在处理职位，请稍后再点“逐条采集本页”。');
  if (useRunTab) tickBusy = true;
  try {
    if (type === 'collectVisibleAndUpload' && new URL(tab.url).pathname === '/') {
      return collectRecommendations(tab.id);
    }
    const contentType = type === 'collectVisibleAndUpload' ? 'collectVisibleSeekJobs' : 'collectCurrentSeekPage';
    if (contentType === 'collectVisibleSeekJobs') {
      const listing = await waitForSearchResults(tab.id);
      if (!listing?.ok) throw Error(listing?.error || 'SEEK 搜索页无法读取。');
    }
    const result = await collectFromTab(tab.id, contentType);
    if (!result?.ok) throw Error(result?.error || '无法读取当前页面。');
    const uploaded = await upload(result.jobs, result.pageUrl);
    if (useRunTab) {
      const latest = await runState();
      if (latest?.id === run.id && latest.status !== 'paused') {
        latest.attemptedIds = [...new Set([...latest.attemptedIds,
          ...result.jobs.map(job => job.source_job_id)])];
        latest.accepted += uploaded.accepted_count || 0;
        latest.duplicates += uploaded.duplicate_count || 0;
        latest.rejected += (uploaded.rejected_count || 0) + (uploaded.rejected_local || 0);
        latest.failed += result.failures?.length || 0;
        latest.message = `本页批量采集：新增 ${uploaded.accepted_count || 0}，详情失败 ${result.failures?.length || 0}。`;
        latest.updatedAt = new Date().toISOString();
        await saveRun(latest);
      }
    }
    return {...uploaded, attempted: result.attempted, failures: result.failures};
  } finally {
    if (useRunTab) tickBusy = false;
  }
}

chrome.runtime.onInstalled.addListener(async () => {
  const run = await runState();
  if (run && run.collectionScope !== 'registered_nurse') {
    run.collectionScope = 'registered_nurse';
    run.page = 1;
    run.pageUrl = SEARCH_URL;
    run.attemptedIds = [];
    run.message = '已更新为澳洲 Registered Nurse，保留已入库数据，从第一页继续筛选。';
    await chrome.storage.local.set({continuousRun: run});
  }
  await restoreContinuousAlarm();
});
chrome.runtime.onStartup.addListener(async () => { await restoreContinuousAlarm(); await continuousTick(); });

async function seekControl(message, sender) {
  return JobaggControl.handle(message,sender,'seek',{
    status:collectorStatus,
    configure:async config=>{await chrome.storage.local.set(config);await chrome.storage.local.remove('seekLiveProgress');},
    start:async()=>{const run=await runState();
      if(JobaggControl.requiresHuman(run)) throw Error('请先打开 SEEK 处理验证，再点击“验证后继续”。');
      return popupCommand(run?.status==='paused'?'resumeContinuous':'startContinuous',true);},
    pause:()=>popupCommand('pauseContinuous'),resume:()=>popupCommand('resumeContinuous',true),
    sync:async()=>{await loadSettings();const run=await runState();
      if(run?.pendingUpload) {run.uploadRetryAt=0;await chrome.storage.local.set({continuousRun:run});
        await chrome.alarms.create('seek-next-detail',{when:Date.now()+1000});}}
  });
}
async function collectorStatus() {
  const run=await runState();
  const stored=await chrome.storage.local.get(['apiUrl','deviceToken','lastResult','seekLiveProgress']);
  const progress=progressView(stored.seekLiveProgress);
  const accepted=run?.accepted || 0;
  return {platform:'seek',status:run?.status || 'idle',message:run?.message || '点击一键开始，将自动创建 SEEK 页面。',
    collected:accepted+(run?.duplicates || 0)+(run?.pendingUpload?1:0),pendingSync:run?.pendingUpload?1:0,synced:accepted+(run?.duplicates || 0),
    lastSyncAt:run?.lastSyncAt || null,nextRunAt:run?.waitUntil || run?.nextTickAt || null,
    needsSetup:!stored.deviceToken || /设备连接已失效/.test(run?.message || ''),canResume:run?.status==='paused',requiresHuman:JobaggControl.requiresHuman(run),
    updatedAt:run?.updatedAt || null,page:run?.page || 1,
    dailyTarget:progress.fresh?progress.value.today_target:undefined,
    todayCollected:progress.fresh?progress.value.today_valid:undefined,progress};
}
async function popupCommand(type, defer=false) {
  return handlePopup({type,defer});
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if(message.type==='collectorControl' && globalThis.JobaggControl) {
    seekControl(message,sender).then(value=>reply({ok:true,value}),error=>reply({ok:false,error:error.message}));
    return true;
  }
  if (!sender.url?.startsWith(chrome.runtime.getURL(''))) return false;
  handlePopup(message).then(value => reply({ok: true, value}), error => reply({ok: false, error: error.message}));
  return true;
});
async function handlePopup(message) {
    if (message.type === 'seekProgress') return liveProgress();
    if (message.type === 'continuousState') return runState();
    if (message.type === 'startContinuous') {
      await loadSettings();
      const existing = await runState();
      if (existing && ['running', 'waiting'].includes(existing.status)) {
        await restoreContinuousAlarm();
        if(message.defer) return existing;
        return existing.status === 'running' ? continuousTick() : existing;
      }
      const [activeTab] = await chrome.tabs.query({active: true, currentWindow: true});
      const useActive = activeTab?.id && C.seekUrl(activeTab.url)
        && /^\/Registered-Nurse-jobs\/?$/i.test(new URL(activeTab.url).pathname);
      const tab = useActive ? activeTab : {id:null, url:SEARCH_URL};
      const run = {id: crypto.randomUUID(), status: 'running', tabId: tab.id,
        page: Number(new URL(tab.url).searchParams.get('page')) || 1,
        pageUrl: searchPageUrl(tab.url), collectionScope:'registered_nurse', attemptedIds: [], accepted: 0, duplicates: 0,
        rejected: 0, failed: 0, message: '正在逐条采集澳洲 Registered Nurse 职位。',
        startedAt: new Date().toISOString(), updatedAt: new Date().toISOString(), waitUntil: null};
      await chrome.storage.local.set({continuousRun: run});
      await restoreContinuousAlarm();
      if(message.defer) {await chrome.alarms.create('seek-next-detail',{when:Date.now()+1000});return run;}
      return continuousTick();
    }
    if (message.type === 'pauseContinuous') return pauseRun('已手动暂停，当前进度已保存。');
    if (message.type === 'resumeContinuous') {
      await loadSettings();
      const run = await runState();
      if (!run) throw Error('还没有连续采集任务，请先点击“开始连续采集”。');
      if (run.page > 1 && !run.attemptedIds.length && !run.accepted && !run.failed) {
        run.page = 1;
        run.pageUrl = SEARCH_URL;
      }
      run.status = 'running';
      run.waitUntil = null;
      run.message = '正在从保存的位置继续采集。';
      await chrome.storage.local.set({continuousRun: run});
      await restoreContinuousAlarm();
      if(message.defer) {await chrome.alarms.create('seek-next-detail',{when:Date.now()+1000});return run;}
      return continuousTick();
    }
    if (message.type === 'saveSettings') {
      const checked = C.config({apiUrl: message.apiUrl, token: message.deviceToken});
      await chrome.storage.local.set({apiUrl: checked.apiUrl, deviceToken: checked.token});
      await chrome.storage.local.remove('seekLiveProgress');
      return {saved: true};
    }
    if (message.type === 'collectAndUpload' || message.type === 'collectVisibleAndUpload') {
      return collectManual(message.type);
    }
    if (message.type === 'clearSeen') {
      await chrome.storage.local.remove(['seenJobIds', 'lastResult']);
      return {cleared: true};
    }
    throw Error('未知操作。');
}
