/* Pure SEEK parsing and validation helpers. No network access or credentials. */
(() => {
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();

  function seekUrl(value) {
    try {
      if (typeof value !== 'string' || !value.trim()) return null;
      const url = new URL(value, 'https://au.seek.com/');
      if (url.hostname.toLowerCase() !== 'au.seek.com' && !/(^|\.)seek\.com\.au$/i.test(url.hostname)) return null;
      url.hash = '';
      return url.href;
    } catch (_) {
      return null;
    }
  }

  function jobId(value) {
    const text = String(value || '');
    const path = text.match(/\/job\/(\d+)/i);
    if (path) return path[1];
    const query = text.match(/[?&](?:jobId|id)=(\d+)/i);
    return query ? query[1] : null;
  }

  function canonicalJobUrl(id) {
    const value = clean(id);
    return /^\d+$/.test(value) ? `https://au.seek.com/job/${value}` : null;
  }

  function isSeekJobUrl(value) {
    const url = seekUrl(value);
    return !!url && !!jobId(url);
  }

  function salary(value) {
    const text = clean(value);
    if (!text || !/(?:\$|AUD|per\s+(?:hour|day|week|month|year)|p\.?a\.?)/i.test(text)) return {};
    const values = [...text.matchAll(/(?:AUD\s*)?\$?\s*(\d[\d,.]*)(\s*[kK])?/g)]
      .map(match => Number(match[1].replace(/,/g, '')) * (match[2] ? 1000 : 1))
      .filter(Number.isFinite);
    if (!values.length) return {};
    const lower = text.toLowerCase();
    const period = /per\s*hour|hourly|\/hr|p\.?\s*h\.?/i.test(lower) ? 'hour' :
      /per\s*day|\/day/i.test(lower) ? 'day' :
      /per\s*week|\/week/i.test(lower) ? 'week' :
      /per\s*month|\/month/i.test(lower) ? 'month' : 'year';
    return {salary_min: values[0], salary_max: values[1] || values[0], salary_currency: 'AUD', salary_period: period};
  }

  function location(value) {
    const raw = clean(value).replace(/\((?:Remote|Hybrid|On-site)\)/ig, '').trim();
    const stateMatch = raw.match(/\b(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\b/i);
    const state = stateMatch ? stateMatch[1].toUpperCase() : null;
    let city = raw;
    if (stateMatch) city = raw.slice(0, stateMatch.index).replace(/[,\s]+$/, '');
    city = city.replace(/^All\s+/i, '').trim() || null;
    return {city, state};
  }

  function remoteType(...values) {
    const text = values.map(clean).join(' ');
    if (/\bremote\b|work\s+from\s+home|\bWFH\b/i.test(text)) return 'remote';
    if (/\bhybrid\b/i.test(text)) return 'hybrid';
    if (/on[ -]?site|in[ -]?person/i.test(text)) return 'onsite';
    return null;
  }

  function postedAt(value, now = Date.now()) {
    const text = clean(value).replace(/^Listed\s+/i, 'Posted ');
    if (!text) return null;
    if (/just now|today|刚刚|今天/i.test(text)) return new Date(now).toISOString();
    const relative = text.match(/(?:posted\s+)?(\d+)\s*(minute|hour|day|week)s?\s+ago/i)
      || text.match(/(?:发布于?|发表于?)\s*(\d+)\s*(分钟|小时|天|周)前/);
    if (relative) {
      const unit = {minute:60000, hour:3600000, day:86400000, week:604800000,
        '分钟':60000, '小时':3600000, '天':86400000, '周':604800000};
      return new Date(now - Number(relative[1]) * unit[String(relative[2]).toLowerCase()]).toISOString();
    }
    const shorthand = text.match(/(?:posted\s+)?(\d+)\s*([mhdw])\s+ago/i);
    if (shorthand) {
      const unit = {m:60000, h:3600000, d:86400000, w:604800000};
      return new Date(now - Number(shorthand[1]) * unit[shorthand[2].toLowerCase()]).toISOString();
    }
    const parsed = Date.parse(text.replace(/^posted\s+/i, ''));
    if (Number.isFinite(parsed) && parsed <= now + 300000) return new Date(parsed).toISOString();
    const dmy = text.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/);
    if (dmy) {
      const parsedDmy = Date.parse(`${dmy[3]}-${dmy[2]}-${dmy[1]}T00:00:00Z`);
      if (Number.isFinite(parsedDmy)) return new Date(parsedDmy).toISOString();
    }
    return null;
  }

  const TITLE_INCLUDE = [/\bregistered\s+nurse\b/i, /\bRN\b/i, /\bclinical\s+nurse\b/i,
    /\bpractice\s+nurse\b/i, /\bcommunity\s+nurse\b/i, /\baged\s+care\s+(?:registered\s+)?nurse\b/i,
    /\bmental\s+health\s+nurse\b/i, /\btheatre\s+nurse\b/i, /\bemergency\s+nurse\b/i,
    /\bICU\s+nurse\b/i, /\bpaediatric\s+nurse\b/i, /\boncology\s+nurse\b/i,
    /\bscrub\s*scout\s+nurse\b/i, /\bperioperative\s+nurse\b/i];
  const TITLE_EXCLUDE = [/\benrolled\s+nurse\b/i, /\bassistant\s+in\s+nursing\b/i, /\bAIN\b/i,
    /\bpersonal\s+care\s+worker\b/i, /\bnurse\s+assistant\b/i, /\bnursing\s+student\b/i];
  function titleInScope(value) {
    const title = clean(value);
    const mixed = /registered\s+nurse|\bRN\b|clinical\s+nurse/i.test(title)
      && TITLE_EXCLUDE.some(pattern => pattern.test(title));
    return TITLE_INCLUDE.some(pattern => pattern.test(title))
      && (!TITLE_EXCLUDE.some(pattern => pattern.test(title)) || mixed);
  }
  function registeredNurseTitle(value) {
    return /\bregistered[\s-]+nurses?\b|\bRNs?\b/i.test(clean(value));
  }
  const SPECIALTIES = [
    ['Aged Care', /aged\s+care|residential\s+care|elderly/i], ['Mental Health', /mental\s+health|psychiatr/i],
    ['Emergency', /\bemergency\b|\bED\s+nurse/i], ['ICU', /\bICU\b|intensive\s+care|critical\s+care/i],
    ['Theatre', /theatre|operating\s+room|scrub\s*scout|perioperative/i], ['Community', /community\s+nurs|community\s+care|home\s+care/i],
    ['General Practice', /general\s+practice|\bGP\b|practice\s+nurse/i], ['Paediatrics', /paediatric|pediatric|children/i],
    ['Oncology', /oncolog/i]
  ];

  function nurseMetadata(title, description, listed, salaryText) {
    const text = clean(`${title} ${description}`);
    return {
      specialty_tags: SPECIALTIES.filter(([, pattern]) => pattern.test(text)).map(([tag]) => tag),
      ahpra_required: /AHPRA|registered with the Australian Health Practitioner Regulation Agency/i.test(text),
      experience_years: Number((text.match(/(\d+)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience/i) || [])[1]) || null,
      shift_information: (text.match(/(?:day|night|evening|morning|rotating|shift|weekend)[^.;,]{0,80}/i) || [])[0] || null,
      facility_type: (text.match(/(?:hospital|clinic|aged care|residential care|community|general practice|GP)[^.;,]{0,50}/i) || [])[0] || null,
      visa_sponsorship: /visa sponsorship|sponsorship available|482 visa|海外护士|移民/i.test(text),
      relocation_assistance: /relocation|move(?:ment)? assistance|搬迁/i.test(text),
      remote_area: /remote area|rural|regional|偏远地区/i.test(text),
      listed_text: listed || null, salary_text: salaryText || null,
      detail_status: description && description.length >= 120 ? 'complete' : 'partial'
    };
  }

  function completenessScore(job) {
    const raw = job.raw_payload || {};
    let score = 0;
    score += job.title ? 10 : 0; score += job.company ? 10 : 0;
    score += job.city || job.state ? 10 : 0; score += job.posted_at ? 15 : 0;
    score += (job.description || '').length >= 120 || raw.detail_status === 'complete' ? 25 : 0;
    score += isSeekJobUrl(job.canonical_url) ? 10 : 0;
    score += job.employment_type ? 5 : 0; score += job.salary_min != null ? 5 : 0;
    score += raw.specialty_tags?.length ? 5 : 0; score += raw.shift_information ? 5 : 0;
    return score;
  }

  function valid(job, now = Date.now()) {
    if (!job || job.source !== 'seek_user_import' || job.country !== 'AU') return false;
    if (!clean(job.title)) return false;
    if (job.raw_payload?.collection_scope === 'registered_nurse' && !registeredNurseTitle(job.title)) return false;
    if (!['all_search_results','registered_nurse'].includes(job.raw_payload?.collection_scope) && !titleInScope(job.title)) return false;
    const published = Date.parse(job.posted_at || '');
    return !!job.company && !!(job.city || job.state) && (job.description || '').length >= 120
      && isSeekJobUrl(job.canonical_url)
      && Number.isFinite(published) && published <= now + 300000 && published >= now - 7 * 86400000
      && completenessScore(job) >= 75 && job.closed !== true;
  }

  function first(root, selectors) {
    for (const selector of selectors) {
      const node = root?.querySelector?.(selector);
      if (node) return node;
    }
    return null;
  }

  function textAt(root, selectors) {
    const node = first(root, selectors);
    return clean(node?.innerText || node?.textContent || node?.getAttribute?.('aria-label')) || null;
  }

  function detailData(root, pageUrl) {
    const detail = first(root, ['[data-automation="job-detail"]', '[data-testid="job-details"]',
      '[data-automation="jobAdDetails"]', '[data-testid="job-description"]', 'article[data-automation="job-detail"]']);
    let scope = detail?.querySelector ? detail : root;
    if (detail?.matches?.('[data-automation="jobAdDetails"], [data-testid="job-description"]')) {
      scope = detail;
      for (let i = 0; i < 5 && scope.parentElement; i++) {
        scope = scope.parentElement;
        if (first(scope, ['[data-automation="job-detail-title"]', '[data-testid="job-detail-title"]', 'h1'])) break;
      }
    }
    const detailLink = detail && !['BODY', 'HTML'].includes(scope?.tagName)
      ? first(scope, ['a[href*="/job/"]']) : null;
    const id = jobId(pageUrl) || jobId(seekUrl(detailLink?.href || detailLink?.getAttribute?.('href')));
    let structured = null;
    if (id) {
      for (const script of root?.querySelectorAll?.('script[type="application/ld+json"]') || []) {
        try {
          const parsed = JSON.parse(script.textContent || 'null');
          const entries = Array.isArray(parsed) ? parsed : parsed?.['@graph'] || [parsed];
          structured = entries.find(entry => String(entry?.['@type'] || '').includes('JobPosting')
            && jobId(entry.url || entry['@id'] || entry.identifier?.value) === id) || structured;
        } catch (_) { /* Ignore unrelated or malformed page metadata. */ }
      }
    }
    const detailTextAt = selectors => textAt(scope, selectors) || (scope !== root ? textAt(root, selectors) : null);
    const title = detailTextAt(['[data-automation="job-detail-title"]', '[data-testid="job-detail-title"]',
      '[data-testid="job-title"]', 'h1']) || clean(structured?.title);
    const company = detailTextAt(['[data-automation="advertiser-name"]', '[data-automation="job-detail-company"]',
      '[data-testid="company-name"]', '[data-testid="advertiser-name"]']) || clean(structured?.hiringOrganization?.name);
    const locationText = detailTextAt(['[data-automation="job-detail-location"]',
      '[data-testid="job-detail-location"]', '[data-testid="job-location"]']) ||
      clean([structured?.jobLocation?.address?.addressLocality, structured?.jobLocation?.address?.addressRegion].filter(Boolean).join(' '));
    const workType = detailTextAt(['[data-automation="job-detail-work-type"]', '[data-testid="work-type"]']);
    const salaryText = detailTextAt(['[data-automation="job-detail-salary"]', '[data-testid="job-salary"]']);
    const detailText = detailTextAt(['[data-automation="jobAdDetails"]', '[data-testid="job-description"]',
      '[data-testid="job-ad-details"]']) || clean(String(structured?.description || '').replace(/<[^>]+>/g, ' '));
    const dateNode = [...(scope?.querySelectorAll?.('time, span') || root?.querySelectorAll?.('time, span') || [])]
      .find(node => /^(?:(?:Posted|Listed)\s+)?\d+\s*(?:m|h|d|w|minutes?|hours?|days?|weeks?)\s+ago/i.test(clean(node?.innerText || node?.textContent)));
    const listed = clean(dateNode?.innerText || dateNode?.textContent) || clean(structured?.datePosted) || null;
    return {id, title, company, locationText, workType, salaryText, detailText, listed};
  }

  function parseCard(root, pageUrl, collectedAt = new Date().toISOString()) {
    const link = first(root, ['a[data-automation="jobTitle"]', 'h1', 'a[href*="/job/"]']);
    const href = seekUrl(link?.href || link?.getAttribute?.('href'));
    const id = jobId(href) || clean(root?.getAttribute?.('data-job-id')) || null;
    const title = clean(link?.innerText || link?.textContent || link?.getAttribute?.('aria-label'));
    if (!id || !title || !href) return null;
    const company = textAt(root, ['[data-automation="jobCompany"]', '[data-testid="company-name"]', '[data-automation="jobAdvertiser"]']);
    const locationText = textAt(root, ['[data-automation="jobLocation"]', '[data-testid="job-location"]', '[data-automation="job-detail-location"]']);
    const summary = textAt(root, ['[data-automation="jobDescription"]', '[data-testid="job-description"]', '[data-automation="jobShortDescription"]', '[data-testid="job-teaser"]']);
    const workType = textAt(root, ['[data-automation="jobWorkType"]', '[data-testid="job-work-type"]']);
    const salaryText = textAt(root, ['[data-automation="jobSalary"]', '[data-testid="job-salary"]']);
    const listed = textAt(root, ['[data-automation="jobListingDate"]', 'time']);
    const detailText = summary || (root?.body?.innerText || '');
    const place = location(locationText);
    const job = {
      source: 'seek_user_import', source_job_id: id, title, company,
      description: detailText, country: 'AU', state: place.state, city: place.city,
      remote_type: remoteType(locationText, workType, summary), employment_type: workType,
      canonical_url: href, apply_url: href, ...salary(salaryText),
      closed: /no longer available|job has closed|position has been filled|职位已关闭|职位不存在/i.test(detailText),
      posted_at: postedAt(listed, Date.parse(collectedAt) || Date.now()), collected_at: collectedAt,
      raw_payload: {location_text: locationText, salary_text: salaryText, listed_text: listed,
        teaser: summary, detail_text: detailText, closed: /no longer available|job has closed|position has been filled|职位已关闭|职位不存在/i.test(detailText), collected_from: seekUrl(pageUrl),
        ...nurseMetadata(title, detailText, listed, salaryText)}
    };
    job.raw_payload.quality_score = completenessScore(job);
    return job;
  }

  function parseDetail(root, pageUrl, collectedAt = new Date().toISOString()) {
    const {id, title, company, locationText, workType, salaryText, detailText, listed} = detailData(root, pageUrl);
    if (!id || !title || !company || !locationText || !detailText) return null;
    const href = canonicalJobUrl(id);
    const place = location(locationText);
    const job = {
      source: 'seek_user_import', source_job_id: id, title, company,
      description: detailText, country: 'AU', state: place.state, city: place.city,
      remote_type: remoteType(locationText, workType, detailText), employment_type: workType,
      canonical_url: href, apply_url: href, ...salary(salaryText),
      closed: /no longer available|job has closed|position has been filled|职位已关闭|职位不存在/i.test(detailText),
      posted_at: postedAt(listed, Date.parse(collectedAt) || Date.now()), collected_at: collectedAt,
      raw_payload: {location_text: locationText, salary_text: salaryText, listed_text: listed,
        detail_text: detailText, closed: /no longer available|job has closed|position has been filled|职位已关闭|职位不存在/i.test(detailText),
        collected_from: seekUrl(pageUrl), ...nurseMetadata(title, detailText, listed, salaryText)}
    };
    job.raw_payload.quality_score = completenessScore(job);
    return job;
  }

  function config(raw = {}) {
    const apiUrl = String(raw.apiUrl || 'http://localhost:8010').trim().replace(/\/+$/, '');
    const parsed = new URL(apiUrl);
    if (!['http:', 'https:'].includes(parsed.protocol)) throw Error('API 地址必须使用 http 或 https。');
    if (parsed.protocol === 'http:' && !['localhost', '127.0.0.1'].includes(parsed.hostname)) {
      throw Error('非本机 API 必须使用 https。');
    }
    const token = String(raw.token || '').trim();
    if (!token) throw Error('请填写设备令牌。');
    return {apiUrl, token};
  }

  const api = {clean, seekUrl, jobId, canonicalJobUrl, isSeekJobUrl, salary, location, remoteType, postedAt, nurseMetadata,
    completenessScore, titleInScope, registeredNurseTitle, valid, parseCard, parseDetail, detailData, config};
  if (typeof module !== 'undefined') module.exports = api;
  else globalThis.SeekCollector = api;
})();
