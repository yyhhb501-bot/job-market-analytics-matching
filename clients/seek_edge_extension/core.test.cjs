const {test} = require('node:test');
const assert = require('node:assert/strict');
const C = require('./core.js');

test('all-search-results mode accepts complete non-nursing titles, but not teasers', () => {
  const job = {source:'seek_user_import', country:'AU', title:'Clinical Assessor Delegate',
    company:'Example Health', city:'Brisbane', description:'Full duties and responsibilities. '.repeat(8),
    canonical_url:'https://au.seek.com/job/987654323', posted_at:new Date().toISOString(),
    raw_payload:{collection_scope:'all_search_results'}};
  assert.equal(C.valid(job), true);
  assert.equal(C.valid({...job, description:'Short teaser'}), false);
});

test('accepts only SEEK AU URLs and extracts job ids', () => {
  assert.equal(C.jobId('https://www.seek.com.au/job/12345678?type=standard'), '12345678');
  assert.match(C.seekUrl('https://au.seek.com/Registered-Nurse-jobs'), /^https:\/\/au\.seek\.com\//);
  assert.match(C.seekUrl('/job/12345678'), /^https:\/\/au\.seek\.com\/job\/12345678/);
  assert.equal(C.seekUrl('https://evil.example/job/12345678'), null);
  assert.equal(C.seekUrl(undefined), null);
  assert.equal(C.isSeekJobUrl('https://au.seek.com/job/12345678'), true);
});

test('parses common Australian salary formats', () => {
  assert.deepEqual(C.salary('$120k - $140k + super'), {salary_min:120000, salary_max:140000, salary_currency:'AUD', salary_period:'year'});
  assert.deepEqual(C.salary('$55 - $65 per hour'), {salary_min:55, salary_max:65, salary_currency:'AUD', salary_period:'hour'});
  assert.deepEqual(C.salary('Competitive'), {});
});

test('parses SEEK shorthand posted times', () => {
  const now = Date.parse('2026-09-22T12:00:00Z');
  assert.equal(C.postedAt('Posted 7h ago', now), '2026-09-22T05:00:00.000Z');
  assert.equal(C.postedAt('1d ago', now), '2026-09-21T12:00:00.000Z');
  assert.equal(C.postedAt('Listed 1d ago', now), '2026-09-21T12:00:00.000Z');
});

test('reads matching JobPosting metadata on a standalone detail page', () => {
  const description = 'Provide registered nursing care for surgical patients, maintain complete clinical records, collaborate with the multidisciplinary team, and meet AHPRA requirements.';
  const metadata = { '@type':'JobPosting', url:'https://au.seek.com/job/94795151',
    title:'Registered Nurse', hiringOrganization:{name:'Example Hospital'},
    jobLocation:{address:{addressLocality:'Brisbane', addressRegion:'QLD'}},
    datePosted:'2026-09-22T05:00:00Z', description };
  const root = {
    querySelector: () => null,
    querySelectorAll: selector => selector === 'script[type="application/ld+json"]'
      ? [{textContent:JSON.stringify(metadata)}] : []
  };
  const job = C.parseDetail(root, 'https://au.seek.com/job/94795151', '2026-09-22T12:00:00Z');
  assert.equal(job?.company, 'Example Hospital');
  assert.equal(job?.state, 'QLD');
  assert.equal(job?.posted_at, '2026-09-22T05:00:00.000Z');
});

test('normalises location and work arrangement', () => {
  assert.deepEqual(C.location('Melbourne VIC (Hybrid)'), {city:'Melbourne', state:'VIC'});
  assert.equal(C.remoteType('Sydney NSW', 'Full time', 'Work from home'), 'remote');
  assert.equal(C.remoteType('Brisbane QLD (Hybrid)'), 'hybrid');
});

test('limits automatic card selection to in-scope nursing titles', () => {
  assert.equal(C.titleInScope('Registered Nurse'), true);
  assert.equal(C.titleInScope('Practice Nurse (RN/EN)'), true);
  assert.equal(C.titleInScope('Enrolled Nurse'), false);
  assert.equal(C.titleInScope('Registered Midwife'), false);
});

test('rejects insecure remote APIs and requires a token', () => {
  assert.equal(C.config({apiUrl:'http://localhost:8010/', token:'abc'}).apiUrl, 'http://localhost:8010');
  assert.throws(() => C.config({apiUrl:'http://example.com', token:'abc'}));
  assert.throws(() => C.config({apiUrl:'https://example.com', token:''}));
});

test('turns a recognised card into an import job', () => {
  const nodes = {
    'a[href*="/job/"]': {href:'https://www.seek.com.au/job/87654321', innerText:'Senior Data Analyst'},
    '[data-automation="jobCompany"]': {innerText:'Example Pty Ltd'},
    '[data-automation="jobLocation"]': {innerText:'Sydney NSW (Hybrid)'},
    '[data-automation="jobShortDescription"]': {innerText:'Build useful reports with a flexible hybrid team.'},
    '[data-automation="jobWorkType"]': {innerText:'Full time'},
    '[data-automation="jobSalary"]': {innerText:'$120k - $140k + super'}
  };
  const root = {querySelector: selector => nodes[selector] || null, getAttribute: () => null};
  const job = C.parseCard(root, 'https://www.seek.com.au/data-jobs', '2026-09-21T00:00:00Z');
  assert.equal(job.source, 'seek_user_import');
  assert.equal(job.source_job_id, '87654321');
  assert.equal(job.state, 'NSW');
  assert.equal(job.remote_type, 'hybrid');
  assert.equal(job.salary_min, 120000);
});

test('parses the current SEEK split-view detail panel', () => {
  const nodes = {
    '[data-automation="job-detail-title"]': {innerText:'Registered Nurse - Day Surgery'},
    '[data-automation="advertiser-name"]': {innerText:'Example Hospital'},
    '[data-automation="job-detail-location"]': {innerText:'Greenslopes, Brisbane QLD'},
    '[data-automation="job-detail-work-type"]': {innerText:'Part time'},
    '[data-automation="job-detail-salary"]': {innerText:'$39.96 - $54.01 p.h + superannuation'},
    '[data-automation="jobAdDetails"]': {innerText:'Provide safe patient-centred nursing care in the day surgery unit. Current AHPRA registration is required, together with at least 12 months of surgical nursing experience and strong clinical assessment skills.'}
  };
  const root = {
    querySelector: selector => nodes[selector] || null,
    querySelectorAll: () => [{innerText:'Posted 7h ago'}]
  };
  const job = C.parseDetail(root, 'https://au.seek.com/Registered-Nurse-jobs?jobId=94795151&type=standard', '2026-09-22T12:00:00Z');
  assert.equal(job.source_job_id, '94795151');
  assert.equal(job.canonical_url, 'https://au.seek.com/job/94795151');
  assert.equal(job.company, 'Example Hospital');
  assert.equal(job.state, 'QLD');
  assert.equal(job.salary_period, 'hour');
  assert.equal(job.posted_at, '2026-09-22T05:00:00.000Z');
  assert.equal(C.valid(job, Date.parse('2026-09-22T12:00:00Z')), true);
});

test('uses a link inside the detail pane when the search URL has no jobId', () => {
  const detailLink = {href:'https://au.seek.com/job/94795151'};
  const pane = {querySelector: selector => selector === 'a[href*="/job/"]' ? detailLink : null};
  const values = {
    '[data-automation="job-detail-title"]': {innerText:'Registered Nurse'},
    '[data-automation="advertiser-name"]': {innerText:'Example Hospital'},
    '[data-automation="job-detail-location"]': {innerText:'Brisbane QLD'},
    '[data-automation="jobAdDetails"]': {innerText:'Provide complete registered nursing care to patients in this hospital. Maintain clinical records, coordinate with the care team, and meet AHPRA registration requirements throughout the role.'}
  };
  const root = {
    querySelector: selector => selector === '[data-automation="job-detail"]' ? pane : values[selector] || null,
    querySelectorAll: () => [{innerText:'Posted 2h ago'}]
  };
  const job = C.parseDetail(root, 'https://au.seek.com/Registered-Nurse-jobs', '2026-09-22T12:00:00Z');
  assert.equal(job?.source_job_id, '94795151');
  assert.equal(job?.canonical_url, 'https://au.seek.com/job/94795151');
});
test('Registered Nurse scope recognises RN and excludes other nursing roles',()=>{
 for(const title of ['Registered Nurse','Registered Nurses - ICU','RN - Theatre'])
   assert.equal(C.registeredNurseTitle(title),true);
 for(const title of ['Enrolled Nurse','Clinical Nurse','Assistant in Nursing','Cleaner'])
   assert.equal(C.registeredNurseTitle(title),false);
});
