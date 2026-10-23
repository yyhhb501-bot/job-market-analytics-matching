(() => {
  // Reloaded extensions can leave a document without a usable runtime bridge.
  // Do not poison the injection guard before a listener was actually registered.
  const runtime=typeof chrome!=='undefined'?chrome.runtime:null;
  if(typeof runtime?.onMessage?.addListener!=='function' || !globalThis.SeekCollector) return;
  if (globalThis.__seekCurrentPageCollector) return;
  const C = globalThis.SeekCollector;

  function blocked() {
    const sample = `${document.title}\n${document.body?.innerText || ''}`.slice(0, 6000);
    if (/429|too many requests|rate limit|请求过多|访问频率/i.test(sample)) return 'SEEK 返回了访问频率限制，请停止并稍后再试。';
    if (/captcha|verify (?:you are|you're) human|security check|just a moment|checking your browser|cloudflare|验证码|安全验证/i.test(sample)
      || /\/(?:captcha|challenge|verify)(?:\/|\?|$)/i.test(location.href)) return '页面要求人工验证；扩展已暂停，请自行完成后再点击“继续连续采集”。';
    if (/sign in|log in|登录/i.test(sample) && /account|password|密码/i.test(sample)) return '页面要求登录；请自行处理后再手动采集。';
    return null;
  }

  function roots() {
    const selectors = [
      'article[data-automation="normalJob"]',
      '[data-testid="job-card"]',
      '[data-automation="job-card"]',
      'article:has(a[href*="/job/"])'
    ];
    const found = [];
    for (const selector of selectors) {
      try { found.push(...document.querySelectorAll(selector)); } catch (_) { /* :has fallback */ }
      if (found.length) break;
    }
    if (!found.length && /\/job\/\d+/i.test(location.pathname)) found.push(document);
    return found;
  }

  function selectedJobUrl() {
    const selectors = [
      'a[href*="/job/"][aria-current="page"]',
      'a[href*="/job/"][aria-selected="true"]',
      '[aria-selected="true"] a[href*="/job/"]',
      '[data-selected="true"] a[href*="/job/"]',
      '[data-automation="job-detail"] a[href*="/job/"]',
      '[data-testid="job-details"] a[href*="/job/"]'
    ];
    for (const selector of selectors) {
      const href = document.querySelector(selector)?.href;
      if (C.isSeekJobUrl(href)) return href;
    }
    return null;
  }

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const CONTINUOUS_DETAIL_DWELL_MS = 10000;

  function titleLink(root) {
    // Selector lists use DOM order, not selector priority. SEEK inserts an empty
    // overlay anchor before the real title, so query each priority separately.
    for (const selector of ['a[data-automation="jobTitle"]', 'h3 a[href*="/job/"]', 'a[href*="/job/"]']) {
      const link = root?.querySelector?.(selector);
      if (C.clean(link?.innerText || link?.textContent)) return link;
    }
    return null;
  }

  function recommendedJobs() {
    if (location.pathname !== '/') return [];
    const links = [...document.querySelectorAll('a[data-automation^="recommendedJobLink_"]')];
    const jobs = links.map(link => ({
      url: C.seekUrl(link.href), title: C.clean(link.getAttribute('aria-label'))
    })).filter(job => C.isSeekJobUrl(job.url) && job.title);
    return [...new Map(jobs.map(job => [C.jobId(job.url), job])).values()].slice(0, 10);
  }

  function searchJobs() {
    const reason = blocked();
    if (reason) return {ok: false, error: reason};
    const cards = roots();
    const jobs = cards.map(root => {
      const link = titleLink(root);
      const url = C.seekUrl(link?.href || link?.getAttribute?.('href'));
      const title = C.clean(link?.innerText || link?.textContent);
      return {url, title, id: C.jobId(url)};
    }).filter(job => job.id && job.title);
    const next = [...document.querySelectorAll('a[href]')].find(link =>
      /^(?:next|下一页)$/i.test(C.clean(link.getAttribute('aria-label') || link.innerText || link.textContent))
      && C.seekUrl(link.href));
    const readableCardCount = cards.filter(root => titleLink(root)).length;
    return {ok: true, jobs: [...new Map(jobs.map(job => [job.id, job])).values()],
      cardCount: cards.length, readableCardCount, nextPageUrl: C.seekUrl(next?.href), pageUrl: location.href};
  }

  async function collectOne(id) {
    const reason = blocked();
    if (reason) throw Error(reason);
    const root = roots().find(item => C.jobId(titleLink(item)?.href) === id);
    const link = titleLink(root);
    if (!link) throw Error(`职位 ${id} 已不在当前搜索结果页。`);
    const expectedTitle = C.clean(link.innerText || link.textContent);
    const startPath = location.pathname;
    root.scrollIntoView?.({block: 'center'});
    link.click();
    const deadline = Date.now() + 15000;
    while (true) {
      await sleep(500);
      const blockedReason = blocked();
      if (blockedReason) throw Error(blockedReason);
      if (location.pathname !== startPath) throw Error('SEEK 已离开搜索结果页，任务已暂停。');
      if (C.jobId(location.href) !== id) continue;
      const job = C.parseDetail(document, location.href);
      if (job?.source_job_id === id && C.clean(job.title).toLowerCase() === expectedTitle.toLowerCase()
        && job.description?.length >= 120) {
        const dwellUntil = Date.now() + CONTINUOUS_DETAIL_DWELL_MS;
        while (Date.now() < dwellUntil) {
          await sleep(Math.min(500, dwellUntil - Date.now()));
          const dwellBlockedReason = blocked();
          if (dwellBlockedReason) throw Error(dwellBlockedReason);
          if (location.pathname !== startPath || C.jobId(location.href) !== id) {
            throw Error('职位详情停留期间页面发生变化，任务已暂停。');
          }
        }
        return {ok: true, job, pageUrl: location.href};
      }
      if(Date.now()>=deadline) break;
    }
    return {ok: false, error: `职位 ${id} 的详情未在 15 秒内完整加载。`};
  }

  async function collectVisibleJobs() {
    const cards = roots().map(root => {
      const link = titleLink(root);
      const url = C.seekUrl(link?.href || link?.getAttribute?.('href'));
      return {root, link, id: C.jobId(url), title: C.clean(link?.innerText || link?.textContent)};
    }).filter(card => card.id && card.link && card.title);
    const unique = [...new Map(cards.map(card => [card.id, card])).values()].slice(0, 10);
    if (!unique.length) throw Error('当前页未读到有效职位标题，请等待搜索结果加载完成。');
    const jobs = [];
    const failures = [];
    const searchUrl = location.href;
    for (const card of unique) {
      const reason = blocked();
      if (reason) throw Error(reason);
      if (location.pathname !== new URL(searchUrl).pathname) throw Error('搜索页面已离开，已停止本页采集。');
      const current = roots().map(root => ({root, link: titleLink(root)}))
        .find(item => C.jobId(item.link?.href || item.link?.getAttribute?.('href')) === card.id);
      if (!current) { failures.push(`${card.id}：职位卡片已从页面移除`); continue; }
      current.root.scrollIntoView?.({block: 'center'});
      const clickedAt = Date.now();
      current.link.click();
      const deadline = Date.now() + 12000;
      let job = null;
      while (Date.now() < deadline) {
        await sleep(500);
        const blockedReason = blocked();
        if (blockedReason) throw Error(blockedReason);
        if (location.pathname !== new URL(searchUrl).pathname) throw Error('点击职位后打开了独立页面，请回到搜索页；当前布局不支持本页连续点击。');
        const parsed = C.parseDetail(document, `https://au.seek.com/job/${card.id}`);
        const selectedId = C.jobId(selectedJobUrl());
        const sameTitle = C.clean(parsed?.title).toLowerCase() === card.title.toLowerCase();
        if (parsed?.source_job_id === card.id && parsed.description?.length >= 120
          && sameTitle && (!selectedId || selectedId === card.id)) {
          job = parsed;
          break;
        }
      }
      const remainingDwell = clickedAt + CONTINUOUS_DETAIL_DWELL_MS - Date.now();
      if (remainingDwell > 0) await sleep(remainingDwell);
      const dwellBlockedReason = blocked();
      if (dwellBlockedReason) throw Error(dwellBlockedReason);
      if (job) jobs.push(job);
      else failures.push(`${card.id}：详情未加载或字段缺失`);
    }
    return {ok: true, jobs, pageUrl: searchUrl, failures, attempted: unique.length};
  }

  runtime.onMessage.addListener((message, _sender, reply) => {
    if (message?.type === 'checkSeekPage') {
      const reason = blocked();
      reply(reason ? {ok: false, error: reason} : {ok: true});
      return false;
    }
    if (message?.type === 'listSearchSeekJobs') {
      reply(searchJobs());
      return false;
    }
    if (message?.type === 'collectOneSeekJob') {
      collectOne(String(message.id || '')).then(reply, error => reply({ok: false, error: error.message}));
      return true;
    }
    if (message?.type === 'listRecommendedSeekJobs') {
      const reason = blocked();
      reply(reason ? {ok: false, error: reason} : {ok: true, jobs: recommendedJobs(), pageUrl: location.href});
      return false;
    }
    if (message?.type === 'collectVisibleSeekJobs') {
      collectVisibleJobs().then(reply, error => reply({ok: false, error: error.message}));
      return true;
    }
    if (message?.type !== 'collectCurrentSeekPage') return false;
    const reason = blocked();
    if (reason) { reply({ok: false, error: reason}); return false; }
    const detailUrl = C.jobId(location.href) ? location.href : selectedJobUrl() || location.href;
    const requestedJobId = C.jobId(detailUrl);
    const detailJob = C.parseDetail(document, detailUrl);
    if (requestedJobId && !detailJob) {
      const data = C.detailData(document, detailUrl);
      const missing = [['id', '职位 ID'], ['title', '标题'], ['company', '公司'],
        ['locationText', '地点'], ['detailText', '描述']].filter(([key]) => !data[key]).map(([, label]) => label);
      reply({ok: false, error: `详情读取不完整：缺少 ${missing.join('、') || '可用字段'}。请等页面加载完成；若字段已显示，请提供该职位链接。`});
      return false;
    }
    const unique = new Map();
    if (detailJob) {
      unique.set(detailJob.source_job_id, detailJob);
    } else {
      for (const root of roots().slice(0, 30)) {
        const job = C.parseCard(root, location.href);
        if (job) unique.set(job.source_job_id, job);
      }
    }
    const jobs = [...unique.values()];
    const hasDetail = !!document.querySelector('[data-automation="jobAdDetails"], [data-automation="job-detail-title"], [data-testid="job-details"]');
    const data = hasDetail ? C.detailData(document, detailUrl) : null;
    const missing = data ? [['id', '职位 ID'], ['title', '标题'], ['company', '公司'],
      ['locationText', '地点'], ['detailText', '描述']].filter(([key]) => !data[key]).map(([, label]) => label) : [];
    reply(jobs.length ? {ok: true, jobs, pageUrl: location.href} :
      {ok: false, error: hasDetail
        ? `检测到职位详情，但缺少 ${missing.join('、') || '可用字段'}。请提供该职位链接以更新选择器。`
        : '当前是搜索结果摘要页。请先点开一条职位，等待右侧完整详情出现后再采集。'});
    return false;
  });
  globalThis.__seekCurrentPageCollector = true;
})();
