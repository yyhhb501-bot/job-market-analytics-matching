/* Shared pure helpers; no credentials, network calls or site internals. */
(() => {
  const catalog = typeof require === 'function'
    ? require('./catalog.js')
    : (globalThis.LINKEDIN_CATALOG || {occupations:[], countries:[], regions:[], legacyLocations:{}});
  const locations = {
    ...(catalog.legacyLocations || {}),
    melbourne: {id:'au-vic-melbourne', name: 'Melbourne', country:'AU', state:'VIC', geoId: '100992797'},
    sydney: {id:'au-nsw-sydney', name: 'Sydney', country:'AU', state:'NSW', geoId: '104769905'},
    austin: {id:'us-tx-austin', name: 'Austin', country:'US', state:'TX', geoId: '104472865'},
    australia: {id:'au', name: 'Australia', country:'AU', geoId: '101452733'},
    usa: {id:'us', name: 'United States', country:'US', geoId: '103644278'}
  };
  const terms = v => String(v || '').split(/[,，\n]/).map(x => x.trim()).filter(Boolean);
  const integer = (value, fallback, min, max, label) => {
    const n = value === undefined || value === '' ? fallback : Number(value);
    if (!Number.isInteger(n) || n < min || n > max) throw Error(`${label} 必须为 ${min}–${max} 的整数。`);
    return n;
  };
  function config(raw = {}) {
    const c = {...raw};
    c.plan = c.plan || 'custom';
    if (!['custom','all-occupations'].includes(c.plan)) throw Error('无效采集方案。');
    c.keywords = terms(raw.keywords);
    c.excludes = terms(raw.excludes);
    c.occupationGroups = Array.isArray(raw.occupationGroups) ? [...new Set(raw.occupationGroups.map(String))] : [];
    if (c.plan === 'custom' && !c.keywords.length && !c.occupationGroups.length) throw Error('请输入 1–20 个关键词，或选择职业覆盖方案。');
    if (c.keywords.length > 20) throw Error('请输入 1–20 个关键词。');
    c.location = c.location || 'usa';
    if (!locations[c.location] && c.plan === 'custom') throw Error('请选择地点。');
    c.workplace = c.workplace || 'any';
    if (!['any','remote','hybrid','onsite'].includes(c.workplace)) throw Error('无效办公方式。');
    c.workplaceModes = Array.isArray(raw.workplaceModes) && raw.workplaceModes.length
      ? [...new Set(raw.workplaceModes)] : [c.workplace];
    if (c.workplaceModes.some(x => !['any','remote','hybrid','onsite'].includes(x))) throw Error('无效办公方式。');
    c.days = integer(raw.days, c.plan === 'all-occupations' ? 30 : 7, 1, 30, 'days');
    if (![1,7,30].includes(c.days)) throw Error('无效发布时间。');
    c.maxJobs = integer(raw.maxJobs, 1000, 1, 2000, 'maxJobs');
    c.maxPages = integer(raw.maxPages, 40, 1, 40, 'maxPages');
    c.delay = integer(raw.delay, 5, 3, 60, 'delay');
    c.pageDwell = integer(raw.pageDwell, 120, 0, 600, 'pageDwell');
    c.resultsPerPage = integer(raw.resultsPerPage, 25, 1, 100, 'resultsPerPage');
    c.splitThreshold = integer(raw.splitThreshold, 800, 100, 1000, 'splitThreshold');
    c.maxSplitDepth = integer(raw.maxSplitDepth, 2, 0, 4, 'maxSplitDepth');
    c.maxQueries = integer(raw.maxQueries, 10000, 1, 10000, 'maxQueries');
    c.cooldownMinutes = integer(raw.cooldownMinutes, 30, 0, 1440, 'cooldownMinutes');
    c.maxRetries = integer(raw.maxRetries, 2, 0, 5, 'maxRetries');
    c.includeRegions = raw.includeRegions === undefined ? c.plan === 'all-occupations' : !!raw.includeRegions;
    c.strictTitle = !!raw.strictTitle;
    return c;
  }
  function catalogLocations(c) {
    if (c.plan !== 'all-occupations') return [{id:c.location, ...locations[c.location], country: locations[c.location].country}];
    const out = (catalog.countries || []).filter(x => /^\d+$/.test(String(x.geoId || ''))).map(x => ({...x}));
    if (c.includeRegions) {
      for (const region of catalog.regions || []) {
        if (/^\d+$/.test(String(region.geoId || ''))) out.push({...region});
      }
    }
    return out;
  }
  function selectedOccupations(c) {
    if (c.plan === 'all-occupations') {
      const wanted = new Set(c.occupationGroups);
      return (catalog.occupations || []).filter(x => !wanted.size || wanted.has(x.id));
    }
    return c.occupationGroups.length
      ? (catalog.occupations || []).filter(x => c.occupationGroups.includes(x.id))
      : [{id:'custom', name:'自定义', keywords:c.keywords}];
  }
  function queryId(q) {
    return [q.country, q.locationId, q.occupationId, q.keyword, q.workplace, q.days].map(x => String(x || '').replace(/[^\w-]+/g, '_')).join('|');
  }
  function buildQueue(c) {
    const queue = [];
    for (const area of catalogLocations(c)) {
      const occupations = area.country === 'AU'
        ? [{id:'au-registered-nurse', name:'Registered Nurse', keywords:['Registered Nurse'], anzscoMajor:'2'}]
        : selectedOccupations(c);
      for (const occupation of occupations) {
        const keywords = occupation.keywords || c.keywords;
        for (const keyword of keywords) {
          for (const workplace of c.workplaceModes) {
            const q = {
              id:'', status:'pending', attempts:0, resultCount:null, savedCount:0,
              country:area.country, state:area.state || null, locationId:area.id || c.location,
              locationName:area.name, geoId:String(area.geoId),
              occupationId:occupation.id, occupationName:occupation.name,
              socMajor:occupation.socMajor || null, anzscoMajor:occupation.anzscoMajor || null,
              keyword, workplace, days:c.days, page:0, splitDepth:0, parentId:null,
              lastError:null, startedAt:null, finishedAt:null
            };
            q.id = queryId(q);
            queue.push(q);
          }
        }
      }
    }
    return [...new Map(queue.map(q => [q.id, q])).values()].slice(0, c.maxQueries);
  }
  function currentQuery(run) {
    if (run?.queue?.length) return run.queue[run.queueIndex ?? run.query ?? 0] || null;
    const c = run?.config || {};
    return {keyword:c.keywords?.[run?.query || 0], geoId:locations[c.location]?.geoId, locationId:c.location,
      locationName:locations[c.location]?.name, country:locations[c.location]?.country, workplace:c.workplace,
      days:c.days, page:run?.page || 0, occupationId:'custom', occupationName:'自定义'};
  }
  function searchUrl(run) {
    const q = currentQuery(run);
    const c = run.config;
    const days = q.days || c.days;
    const p = new URLSearchParams({keywords:q.keyword || '', geoId:q.geoId, start:String((run.page || 0) * (c.resultsPerPage || 25)), sortBy:'DD', f_TPR:`r${days * 86400}`, distance:'25'});
    const workplace = {onsite:'1',remote:'2',hybrid:'3'}[q.workplace || c.workplace];
    if (workplace) p.set('f_WT', workplace);
    return `https://www.linkedin.com/jobs/search/?${p}`;
  }
  function matchesUrl(url, run) {
    const actual = new URL(url), expected = new URL(searchUrl(run));
    const modern = actual.pathname.replace(/\/$/,'') === '/jobs/search-results';
    // LinkedIn redirects the old results page to its new layout and can remove
    // sortBy. Preserve every scope filter; an explicit different sort is rejected.
    return actual.origin === expected.origin && (modern || actual.pathname === expected.pathname) &&
      (!modern || !actual.searchParams.has('sortBy') || actual.searchParams.get('sortBy') === expected.searchParams.get('sortBy')) &&
      ['keywords','geoId','f_TPR','f_WT',...(modern ? [] : ['sortBy']),'distance','start'].every(k =>
        (actual.searchParams.get(k) || (k === 'start' ? '0' : '')) === (expected.searchParams.get(k) || ''));
  }
  function matchesDetailUrl(url, run) {
    try {
      const actual=new URL(url);
      if(actual.origin!=='https://www.linkedin.com' || !run.visit) return false;
      if(actual.pathname.replace(/\/$/,'')===`/jobs/view/${run.visit.source_job_id}`) return true;
      return actual.searchParams.get('currentJobId')===String(run.visit.source_job_id) && matchesUrl(url,run);
    } catch {return false;}
  }
  function registeredNurseTitle(title) {
    return /\bregistered[\s-]+nurses?\b|\bRNs?\b/i.test(String(title || ''));
  }
  function accepts(title, c, query) {
    if ((query?.country || locations[c.location]?.country) === 'AU' && !registeredNurseTitle(title)) return false;
    const t = String(title || '').toLowerCase();
    const keywords = c.keywords?.length ? c.keywords : (catalog.occupations || []).find(x => c.occupationGroups?.includes(x.id))?.keywords || [];
    return !c.excludes.some(x => t.includes(x.toLowerCase())) && (!c.strictTitle || keywords.some(x => t.includes(x.toLowerCase())));
  }
  function splitQuery(query, c) {
    if (!query || query.splitDepth >= c.maxSplitDepth) return [];
    const areas = (catalog.regions || []).filter(x => x.country === query.country && /^\d+$/.test(String(x.geoId || '')));
    if (areas.length && (query.locationId === query.country.toLowerCase() || query.locationId === query.country)) {
      return areas.map(area => ({...query, id:'', status:'pending', attempts:0, resultCount:null, savedCount:0,
        locationId:area.id, locationName:area.name, state:area.state, geoId:String(area.geoId), page:0,
        splitDepth:query.splitDepth + 1, parentId:query.id, startedAt:null, finishedAt:null, lastError:null})).map(q => ({...q, id:queryId(q)}));
    }
    if (query.workplace === 'any') {
      return ['onsite','hybrid','remote'].map(workplace => ({...query, id:queryId({...query, workplace}), status:'pending', attempts:0,
        resultCount:null, savedCount:0, workplace, page:0, splitDepth:query.splitDepth + 1, parentId:query.id,
        startedAt:null, finishedAt:null, lastError:null}));
    }
    return [];
  }
  function coverage(run) {
    const queue = run?.queue || [];
    const counts = queue.reduce((out, q) => { out[q.status || 'pending'] = (out[q.status || 'pending'] || 0) + 1; return out; }, {});
    return {total:queue.length, counts, current:run?.queueIndex ?? run?.query ?? 0,
      jobs:Object.keys(run?.jobs || {}).length, complete:Object.values(run?.jobs || {}).filter(j => j.detail_status === 'complete').length,
      pending:counts.pending || 0, limited:counts.limited || 0, failed:counts.failed || 0, paused:counts.paused || 0};
  }
  const api = {locations, catalog, config, buildQueue, currentQuery, searchUrl, matchesUrl, matchesDetailUrl, accepts, splitQuery, coverage, registeredNurseTitle};
  if (typeof module !== 'undefined') module.exports = api;
  else globalThis.LinkedInCollector = api;
})();
