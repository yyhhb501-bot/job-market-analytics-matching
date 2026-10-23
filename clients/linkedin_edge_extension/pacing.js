/* Quotas and validation for the opt-in Beijing 09:00–23:00 collection plan. */
(function(root) {
  const HOUR = 3600000, DAY = 24 * HOUR, HOURLY_TARGET = 50, DAILY_TARGET = 600;
  function fresh(value, now = Date.now()) {
    const checked = Date.parse(value);
    return Number.isFinite(checked) && now - checked < DAY;
  }
  function window(now = Date.now()) {
    const local = new Date(now + 8 * HOUR);
    const start = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate(), 1);
    return {active:now >= start && now < start + 14 * HOUR,dayStart:start-9*HOUR,
      nextStart:now < start ? start : start + DAY,
      hour:Math.floor(now/HOUR),nextHour:(Math.floor(now/HOUR)+1)*HOUR};
  }
  function postedAt(value, now = Date.now()) {
    const input = String(value || '').trim();
    if (/^\d{4}-\d{2}-\d{2}T/.test(input)) {
      const parsed = Date.parse(input);
      return Number.isFinite(parsed) && parsed <= now ? new Date(parsed).toISOString() : null;
    }
    if (/\bjust now\b|刚刚/i.test(input)) return new Date(now).toISOString();
    const match = input.match(/(\d+)\s*(minute|hour|day|week)s?\s+ago\b/i)
      || input.match(/(\d+)\s*(分钟|小时|天|周)前/);
    if (!match) return null;
    const unit = {minute:60000, hour:HOUR, day:DAY, week:7*DAY, '分钟':60000, '小时':HOUR, '天':DAY, '周':7*DAY};
    return new Date(now - Number(match[1]) * unit[match[2].toLowerCase()]).toISOString();
  }
  function valid(job, days, now = Date.now()) {
    const published = Date.parse(job?.posted_at);
    return !!job && /^\d+$/.test(String(job.source_job_id)) && job.detail_status === 'complete'
      && typeof job.title === 'string' && !!job.title.trim()
      && typeof job.company === 'string' && !!job.company.trim()
      && typeof job.location === 'string' && !!job.location.trim()
      && typeof job.description === 'string' && job.description.trim().length > 80
      && job.canonical_url === `https://www.linkedin.com/jobs/view/${job.source_job_id}/`
      && job.closed === false && Number.isFinite(published) && published <= now
      && published >= now - days * DAY;
  }
  function count(run, now = Date.now()) {
    return Object.values(run.jobs || {}).filter(job => valid(job, run.config.days,
      run.pacing?.phase === 'daily' ? Date.parse(job.collected_at) : now)).length;
  }
  function slot(plan, now = Date.now()) {
    return Math.floor(now / HOUR);
  }
  function countDaily(ledger, now = Date.now()) {
    const start=window(now).dayStart;
    return Object.values(ledger || {}).filter(value=>{
      const time=Date.parse(value);return Number.isFinite(time) && time>=start && time<=now;
    }).length;
  }
  function allowance(plan, index) {
    // Missed slots never accumulate, so waking after a pause cannot burst.
    return Math.min(HOURLY_TARGET, Math.max(0, plan.target));
  }
  function interleave(items) {
    const groups = [...new Set(items.map(q => q.country))].map(country => items.filter(q => q.country === country));
    const out = [];
    for (let i = 0; groups.some(group => i < group.length); i++) {
      for (const group of groups) if (group[i]) out.push(group[i]);
    }
    return out;
  }
  const api = {HOUR, DAY, HOURLY_TARGET, DAILY_TARGET, countDaily, fresh, window, postedAt, valid, count, slot, allowance, interleave};
  if (typeof module !== 'undefined') module.exports = api;
  else root.LinkedInPacing = api;
})(globalThis);
