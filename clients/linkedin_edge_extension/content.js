(() => {
  if (globalThis.__linkedinCollectorActive) return;
  globalThis.__linkedinCollectorActive = true;
  const C = LinkedInCollector;
  const P = LinkedInPacing;
  let run;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const text = el => (el?.innerText || el?.textContent || '').trim();
  const cardSelector = 'li[data-occludable-job-id], [role="button"][componentkey^="job-card-component-ref-"]';
  async function send(type, extra={}) {
    const r=await chrome.runtime.sendMessage({type,runId:run?.id,...extra});
    if (!r.ok) throw Error(r.error);
    return r.value;
  }
  function challenge() {
    return /\/(login|checkpoint|authwall|challenge)(\/|\?|$)/i.test(location.href) ||
      /quick security check|verify you're a human|安全验证|安全检查/.test((document.body?.innerText || '').slice(0,5000));
  }
  function rateLimited() {
    const sample=`${document.title}\n${document.body?.innerText || ''}`.slice(0,5000);
    return /(?:HTTP\s*)?429|too many requests|rate limit(?:ed)?|请求过多|访问频率|请求频率/i.test(sample);
  }
  async function check() {
    const state=await send('state');
    if (!state || state.id!==run.id || state.status!=='running') throw Error('任务已停止');
    if (rateLimited()) throw Error('HTTP 429：LinkedIn 已限制访问频率。任务已暂停，请等待冷却结束，不要反复刷新。');
    if (challenge()) throw Error('需要在当前标签页手动登录或完成安全验证，完成后点击继续。');
    if (!C.matchesUrl(location.href,run) && !C.matchesDetailUrl(location.href,run)) throw Error('搜索条件或页面已改变，采集已暂停。');
  }
  async function waitFor(fn, timeout=20000, stage='page-load') {
    const end=Date.now()+timeout;
    // Background-tab timers may fire after the deadline. Inspect the now-rendered
    // DOM once on wake before deciding it timed out, while retaining all guards.
    while (true) {
      await check();const value=fn();if(value) return value;
      if(Date.now()>=end) break;
      await sleep(Math.min(600,end-Date.now()));
    }
    const error=Error(`${stage} 加载超时，正在按重试策略处理。`);error.code='LOAD_TIMEOUT';error.stage=stage;throw error;
  }
  async function dwell(milliseconds) {
    const end=Date.now()+milliseconds;
    while(Date.now()<end) {await sleep(Math.min(5000,end-Date.now()));await check();}
  }
  function card(el) {
    const a=el.querySelector('a.job-card-list__title--link');
    const modernId=el.getAttribute('componentkey')?.match(/^job-card-component-ref-(\d+)$/)?.[1];
    const paragraphs=modernId ? [...el.querySelectorAll('p')] : [];
    if(!a && !modernId) return null;
    const id=modernId || el.getAttribute('data-occludable-job-id');
    const title=modernId ? text(paragraphs[0]?.querySelector('span[aria-hidden="true"]') || paragraphs[0])
      : text(a.querySelector('strong')) || a.getAttribute('aria-label')?.replace(/ with verification$/,'');
    const company=modernId ? text(paragraphs[1]) : text(el.querySelector('.artdeco-entity-lockup__subtitle'));
    const loc=modernId ? text(paragraphs[2]) : text(el.querySelector('.artdeco-entity-lockup__caption'));
    if(!/^\d+$/.test(id || '') || !title || !company || !loc) return null;
    const q=C.currentQuery(run);
    return {source:'linkedin_user_import',source_job_id:id,
      title, company, location:loc,
      canonical_url:`https://www.linkedin.com/jobs/view/${id}/`, description:null,
      remote_type:/远程|Remote/i.test(loc)?'remote':/混合|Hybrid/i.test(loc)?'hybrid':/现场|On.site/i.test(loc)?'onsite':'unknown',
      collected_at:new Date().toISOString(), detail_status:'pending',
      raw_payload:{search_keyword:q?.keyword,linkedin_geo_id:q?.geoId,
        search_location:loc,search_page:run.page+1,search_layout:modernId?'search-results':'legacy',
        search_sort:new URL(location.href).searchParams.get('sortBy') || 'site-default',query_id:q?.id,occupation_group:q?.occupationId,
        occupation_name:q?.occupationName,search_country:q?.country,search_state:q?.state,workplace:q?.workplace}};
  }
  function resultCount() {
    const body=document.body?.innerText || '';
    const patterns=[/(\d[\d,]*)\+?\s+(?:results?|jobs?)/i,/(?:of|共)\s+(\d[\d,]*)\+?\s+(?:results?|jobs?|个职位|条)/i,/(\d[\d,]*)\+?\s*(?:个职位|份工作)/i];
    for(const pattern of patterns){const match=body.match(pattern);if(match){const n=Number(match[1].replace(/,/g,''));if(Number.isFinite(n))return n;}}
    return null;
  }
  async function collectDetail() {
    const job={...run.visit};
    const id=String(job.source_job_id);
    if(run.jobs[id]?.detail_status==='complete' && P.fresh(run.jobs[id].collected_at)) {
      await dwell(run.config.delay*1000);
      return send('detailDone',{jobId:id});
    }
    await waitFor(()=>{
      const modern=document.getElementById(`JobDetails_AboutTheJob_${id}`)
        || document.querySelector(`[componentkey="JobDetails_AboutTheJob_${id}"]`);
      const legacy=document.querySelector('#job-details');
      const description=text(modern || legacy);
      if(description.length<=80) return false;
      job.description=description.replace(/^(?:职位简介|关于职位|About the job)\s*/i,'');
      const top=document.querySelector('.job-details-jobs-unified-top-card__container')
        || document.querySelector('.jobs-unified-top-card');
      const metadata=top?.querySelector('.job-details-jobs-unified-top-card__primary-description-container') || top;
      // The new layout has stable, job-ID-specific sections and hashed CSS.
      // Only read the header before this job's description, excluding similar jobs.
      const main=document.querySelector('main') || document.querySelector('[role="main"]');
      let detailScope=null;
      for(let parent=modern?.parentElement,depth=0;parent && depth<7;parent=parent.parentElement,depth++) {
        if(parent.querySelector?.(`a[href*="/jobs/view/${id}/"]`) && !parent.querySelector?.(cardSelector)) {detailScope=parent;break;}
      }
      const mainText=text(detailScope || (!main?.querySelector?.(cardSelector)?main:null)), detailText=text(modern);
      const position=modern ? mainText.indexOf(detailText) : -1;
      const header=metadata ? text(metadata) : position>=0 ? mainText.slice(0,position) : '';
      const time=metadata?.querySelector('time[datetime]')?.getAttribute('datetime');
      job.posted_at=P.postedAt(time || header);
      job.posted_at_evidence=(time || header).slice(0,2000);
      job.closed=header ? /no longer accepting applications|job is no longer available|不再接受.{0,5}申请|停止招聘|职位已关闭/i.test(text(top) || header) : null;
      job.detail_status='complete';job.collected_at=new Date().toISOString();
      return true;
    },45000,`detail-description:${id}`);
    // Dwell after the full description appears, not from navigation start.
    await dwell(Math.max(10000,run.config.delay*1000));
    const saved=await send('job',{job});
    if(!saved || saved.status!=='running') return;
    run=saved;
    await send('detailDone',{jobId:id});
  }
  async function collect() {
    run=await send('state');
    if (!run || run.status!=='running') return;
    await check();
    if(C.matchesDetailUrl(location.href,run)) return collectDetail();
    const pageStarted=Date.now();
    await waitFor(() => document.querySelector(cardSelector) ||
      /没有找到符合|未找到.*职位|No matching jobs|No results found/i.test(document.body?.innerText || ''),45000,'search-results');
    const cards=[...document.querySelectorAll(cardSelector)];
    const jobs=[],unreadableCards=[];
    let readable=0;
    // Persist the whole page BEFORE navigating. New documents can resume the
    // same batch without clicking title links or reloading search per job.
    for (const el of cards) {
      await check();
      el.scrollIntoView({block:'center'});
      let job;
      try {job=await waitFor(()=>card(el),5000,'card-fields');}
      catch(error) {
        if(error.code!=='LOAD_TIMEOUT') throw error;
        unreadableCards.push({jobId:el.getAttribute('data-occludable-job-id') || el.getAttribute('componentkey')?.match(/(\d+)$/)?.[1],reason:error.message});
        continue;
      }
      readable++;
      if(C.accepts(job.title,run.config,C.currentQuery(run))) jobs.push(job);
    }
    if(cards.length && !readable) {
      const error=Error('search-card-fields：本页卡片均未能完整读取');error.code='LOAD_TIMEOUT';error.stage='search-card-fields';throw error;
    }
    await dwell(Math.max(0,(run.config.pageDwell || 0)*1000-(Date.now()-pageStarted)));
    await check();
    const next=document.querySelector('[data-testid="pagination-controls-next-button-visible"]') ||
      [...document.querySelectorAll('button')].find(b=>/查看下一页|View next page/i.test(b.getAttribute('aria-label')||''));
    await send('pageBatch',{jobs,unreadableCards,last:cards.length===0 || !next || next.disabled,resultCount:resultCount()});
  }
  collect().catch(async error => {
    if(run) await send('pause',{reason:error.message,stage:error.stage,recoverable:error.code==='LOAD_TIMEOUT'}).catch(()=>{});
  });
})();
