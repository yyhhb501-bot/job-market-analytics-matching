// Isolated Chromium profile: verifies real manifest injection and isolated-world messaging.
// Only asks for status; never starts collectors or reads the user's browser profile.
const { chromium } = require('@playwright/test');
const { mkdtemp, rm } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const profile = await mkdtemp(path.join(tmpdir(), 'jobagg-bridge-test-'));
  const extensions = ['linkedin', 'seek'].map(p => path.resolve(__dirname, '../../../clients/' + p + '_edge_extension'));
  let context;
  try {
    context = await chromium.launchPersistentContext(profile, {
      channel: 'chromium', headless: true,
      args: ['--disable-extensions-except=' + extensions.join(','), '--load-extension=' + extensions.join(',')],
    });
    await context.route('http://localhost:3000/**', route => route.fulfill({
      contentType: 'text/html', body: '<!doctype html><title>Isolated extension bridge test</title><body>Test only</body>',
    }));
    const page = await context.newPage();
    await page.goto('http://localhost:3000/admin/imports');
    for (const platform of ['linkedin', 'seek']) {
      const reply = await page.evaluate(platform => new Promise(resolve => {
        const requestId = 'integration-' + platform;
        const timer = setTimeout(() => resolve({ error: 'bridge timeout' }), 8000);
        const listener = event => {
          if (event.source !== window || event.origin !== location.origin ||
              event.data?.type !== 'JOBAGG_COLLECTOR_RESPONSE' || event.data.requestId !== requestId) return;
          clearTimeout(timer); window.removeEventListener('message', listener); resolve(event.data);
        };
        window.addEventListener('message', listener);
        window.postMessage({ type: 'JOBAGG_COLLECTOR_REQUEST', platform, action: 'status', requestId }, location.origin);
      }), platform);
      assert.equal(reply.ok, true, platform + ': ' + JSON.stringify(reply));
      assert.equal(reply.value.platform, platform);
      assert.equal(reply.value.needsSetup, true);
      console.log(platform + ': manifest + real content bridge + service worker passed');
    }
    const workers = context.serviceWorkers();
    let linkedinWorker;
    for (const worker of workers) {
      if (await worker.evaluate(() => typeof globalThis.LinkedInCollector !== 'undefined')) linkedinWorker = worker;
    }
    assert.ok(linkedinWorker, 'LinkedIn service worker is loaded');
    const C = require('../../../clients/linkedin_edge_extension/core.js');
    const config = C.config({ keywords: 'Data Analyst', location: 'usa', days: 7, delay: 3, pageDwell: 0 });
    const run = { id: 'isolated-layout-test', status: 'running', mode: 'legacy', config,
      queue: C.buildQueue(config), queueIndex: 0, query: 0, page: 0, jobs: {} };
    const search = new URL(C.searchUrl(run));
    search.pathname = '/jobs/search-results/'; search.searchParams.delete('sortBy');
    await context.route('https://www.linkedin.com/**', route => route.fulfill({
      contentType: 'text/html', body: `<!doctype html><title>Test jobs</title><main>
        <p>99+ 条结果</p><div role="button" componentkey="job-card-component-ref-123456789">
          <p><span>Data Analyst (已通过验证的职位)</span><span aria-hidden="true">Data Analyst</span></p>
          <p>Fixture Company</p><p>Seattle, WA (Hybrid)</p></div>
        <button data-testid="pagination-controls-next-button-visible">下一步</button>
        <button aria-label="下一步" data-testid="carousel-inline-right-button" disabled>Next recommendation</button>
        </main>`,
    }));
    const source = await context.newPage(); await source.goto(search.href);
    await linkedinWorker.evaluate(async run => {
      const [tab] = await chrome.tabs.query({ url: 'https://www.linkedin.com/jobs/search-results/*' });
      await chrome.storage.local.set({ run: { ...run, tabId: tab.id } });
    }, run);
    await source.reload();
    let observed;
    for (let attempt = 0; attempt < 30; attempt++) {
      observed = await linkedinWorker.evaluate(async () => (await chrome.storage.local.get('run')).run);
      if (observed.pageBatch || observed.status === 'paused') break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.equal(observed.status, 'running', observed.message);
    assert.equal(observed.pageBatch.jobs.length, 1);
    assert.equal(observed.pageBatch.last, false, 'uses the pagination control, not the carousel');
    assert.equal(observed.pageBatch.jobs[0].title, 'Data Analyst');
    assert.equal(observed.pageBatch.jobs[0].company, 'Fixture Company');
    assert.equal(observed.pageBatch.jobs[0].source_job_id, '123456789');
    assert.equal(observed.pageBatch.jobs[0].raw_payload.search_sort, 'site-default');
    console.log('LinkedIn modern layout: real injected content script captured card and next-page control');
  } finally {
    if (context) await context.close();
    assert.equal(path.dirname(path.resolve(profile)), path.resolve(tmpdir()));
    assert.ok(path.basename(profile).startsWith('jobagg-bridge-test-'));
    await rm(profile, { recursive: true, force: true });
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
