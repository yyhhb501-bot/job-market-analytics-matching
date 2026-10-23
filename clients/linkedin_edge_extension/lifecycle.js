/* Original-link reviews. Copied identically into both standalone extensions. */
(function(root) {
  const DAY = 86400000;
  function due(candidates, reviews, now = Date.now()) {
    return candidates.filter(item => /^\d+$/.test(String(item.id))).map(item => {
      const last = reviews[item.id];
      const time = Date.parse(last?.checked_at || item.seen) || 0;
      return {...item, time, due:time + (last?.status === 'unknown' ? 2*3600000 : DAY)};
    }).filter(item => item.due <= now).sort((a,b) => a.due-b.due)[0];
  }

  // Runs inside the source tab, without extension state or credentials.
  async function inspectPage(source, id) {
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
    await sleep(10000);
    const expected = source === 'linkedin_user_import' ? `/jobs/view/${id}` : `/job/${id}`;
    const hosts = source === 'linkedin_user_import' ? ['www.linkedin.com'] : ['au.seek.com','www.seek.com.au','seek.com.au'];
    if (!hosts.includes(location.hostname)) return {status:'unknown', evidence:'redirected outside source host'};
    const sample = `${document.title}\n${document.body?.innerText || ''}`.slice(0,6000);
    if (/captcha|verify (?:you are|you're) human|security check|just a moment|cloudflare|安全验证|验证码|429|too many requests|rate limit/i.test(sample)
      || /\/(?:login|checkpoint|authwall|challenge|signin)/i.test(location.pathname)) {
      return {blocked:true, error:'复查遇到登录、安全验证或访问限制，请处理后继续。'};
    }
    if (location.pathname.replace(/\/$/,'') !== expected) return {status:'unknown', evidence:'original URL redirected'};
    const main = document.querySelector('main') || document.querySelector('[role="main"]');
    if (!main) return {status:'unknown', evidence:'detail not loaded'};
    const header = main.querySelector('.job-details-jobs-unified-top-card__container, .jobs-unified-top-card, [data-automation="jobDetailsPage"]');
    const description = document.querySelector(`[id="JobDetails_AboutTheJob_${id}"], #job-details, [data-automation="jobAdDetails"]`);
    let text = (header || main).innerText || '';
    // Exclude the job description and recommendations from closure evidence.
    const cut = description?.innerText && text.indexOf(description.innerText);
    if (typeof cut === 'number' && cut >= 0) text = text.slice(0,cut);
    text = text.split(/similar jobs|recommended jobs|相似职位|推荐职位/i)[0].slice(0,2000);
    const closed = text.match(/no longer accepting applications|job is no longer available|job has expired|job has closed|position has been filled|this job is no longer advertised|不再接受.{0,5}申请|停止招聘|职位已关闭/i);
    if (closed) return {status:'closed', evidence:closed[0]};
    const apply = main.querySelector('.jobs-apply-button, [data-automation="job-detail-apply"], [data-automation="jobApply"]');
    const title = main.querySelector('h1, [data-automation="job-detail-title"]')?.innerText?.trim();
    if (title && (description?.innerText || '').trim().length > 120 && apply
      && !apply.disabled && apply.getAttribute('aria-disabled') !== 'true') {
      return {status:'active', evidence:`detail-and-apply:${title}`.slice(0,2000)};
    }
    return {status:'unknown', evidence:'no conclusive status on the original detail page'};
  }

  async function deliverPending(options, state) {
    try {
      await options.deliver(state.pending);
      state.reviews[state.pending.source_job_id]=state.pending;
      state.pending=null;state.syncRetryAt=0;state.lastSyncError=null;
      await chrome.storage.local.set({lifecycleReview:state});return true;
    } catch (_) {
      state.syncRetryAt=Date.now()+120000;
      state.lastSyncError='复查状态已保存，等待入库服务恢复后自动同步。';
      await chrome.storage.local.set({lifecycleReview:state});return false;
    }
  }
  async function run(options) {
    const stored = await chrome.storage.local.get('lifecycleReview');
    const state = stored.lifecycleReview || {reviews:{}};
    if(state.pending) {
      if(state.syncRetryAt>Date.now() || !await deliverPending(options,state)) return false;
    }
    if(options.allowNew===false) return false;
    if (state.nextAt > Date.now()) return false;
    if (state.tabId) {
      const abandoned = await chrome.tabs.get(state.tabId).catch(()=>null);
      if (abandoned?.url === state.tabUrl) await chrome.tabs.remove(state.tabId).catch(()=>{});
      state.tabId = null;
      await chrome.storage.local.set({lifecycleReview:state});
    }
    const candidate = due(await options.candidates(), state.reviews);
    if (!candidate || !await options.reserve()) return false;
    state.nextAt = Date.now()+(options.intervalMs || 10*60000);
    await chrome.storage.local.set({lifecycleReview:state});
    const url = options.source === 'linkedin_user_import'
      ? `https://www.linkedin.com/jobs/view/${candidate.id}/` : `https://au.seek.com/job/${candidate.id}`;
    let tab;
    let result = {status:'unknown', evidence:'page load failed'};
    try {
      tab = await chrome.tabs.create({url, active:false});
      state.tabId=tab.id;state.tabUrl=url;
      await chrome.storage.local.set({lifecycleReview:state});
      const deadline = Date.now()+20000;
      while (Date.now()<deadline) {
        const current = await chrome.tabs.get(tab.id);
        if (current.status === 'complete') break;
        await new Promise(resolve => setTimeout(resolve,500));
      }
      let timer,inspected;
      try {inspected=await Promise.race([
        chrome.scripting.executeScript({target:{tabId:tab.id},func:inspectPage,args:[options.source,String(candidate.id)]}),
        new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('review timed out')),90000);})]);}
      finally {clearTimeout(timer);}
      const [{result:observed}] = inspected;
      if (observed?.blocked) {
        await options.pause(observed.error);
        // Keep the challenge visible for the user; do not refresh it.
        tab = null;
        result = {status:'unknown', evidence:'verification or access restriction'};
      } else if (observed) {
        result = observed;
      }
    } catch (_) { /* Record uncertainty, never infer closure from a failure. */ }
    finally {
      if (tab) await chrome.tabs.remove(tab.id).catch(()=>{});
      state.tabId=null;
    }
    state.pending = {source:options.source, source_job_id:String(candidate.id), url,
      status:result.status, evidence:result.evidence, checked_at:new Date().toISOString()};
    await chrome.storage.local.set({lifecycleReview:state});
    await deliverPending(options,state);
    return true;
  }
  const api = {due, inspectPage, run};
  if (typeof module !== 'undefined') module.exports = api;
  else root.JobLifecycle = api;
})(globalThis);
