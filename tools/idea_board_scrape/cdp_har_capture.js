// Passive network capture -> HAR (fallback: DevTools HAR export blocked by unresponsive native file picker)
const { chromium } = require('/usr/local/lib/node_modules/playwright-core');
const fs = require('fs');

const CDP = 'http://127.0.0.1:9232';
const OUT = process.argv[2];
const DURATION_MS = parseInt(process.argv[3] || '90000', 10);
const MATCH = process.argv[4] || 'trademachine.com';
const MAX_BODY = 3 * 1024 * 1024;

function hdrs(o) { return Object.entries(o || {}).map(([name, value]) => ({ name, value })); }

(async () => {
  const browser = await chromium.connectOverCDP(CDP);
  const ctx = browser.contexts()[0];
  const pages = ctx.pages();
  const page = pages.find(p => (p.url() || '').includes(MATCH));
  if (!page) { console.error('NO_TM_PAGE'); process.exit(2); }
  console.error('attached to: ' + page.url());

  const entries = [];
  const pending = [];

  page.on('response', async (resp) => {
    const req = resp.request();
    const rt = req.resourceType();
    const p = (async () => {
      const e = {
        startedDateTime: new Date().toISOString(),
        time: 0,
        _resourceType: rt,
        request: {
          method: req.method(),
          url: req.url(),
          httpVersion: 'HTTP/1.1',
          headers: hdrs(await req.allHeaders().catch(() => ({}))),
          queryString: [...new URL(req.url()).searchParams.entries()].map(([name, value]) => ({ name, value })),
          cookies: [],
          headersSize: -1,
          bodySize: -1,
        },
        response: {
          status: resp.status(),
          statusText: resp.statusText(),
          httpVersion: 'HTTP/1.1',
          headers: hdrs(await resp.allHeaders().catch(() => ({}))),
          cookies: [],
          content: { size: -1, mimeType: '', text: '' },
          redirectURL: '',
          headersSize: -1,
          bodySize: -1,
        },
        cache: {},
        timings: { send: 0, wait: 0, receive: 0 },
      };
      const pd = req.postData();
      if (pd) e.request.postData = { mimeType: (await req.allHeaders().catch(() => ({})))['content-type'] || '', text: pd.slice(0, MAX_BODY), params: [] };
      const ct = (e.response.headers.find(h => h.name.toLowerCase() === 'content-type') || {}).value || '';
      e.response.content.mimeType = ct;
      if (rt === 'xhr' || rt === 'fetch' || rt === 'document' || /json|text/i.test(ct)) {
        try {
          const buf = await resp.body();
          e.response.content.size = buf.length;
          e.response.content.text = buf.slice(0, MAX_BODY).toString('utf8');
        } catch (err) { e.response.content._error = String(err.message || err).slice(0, 200); }
      }
      entries.push(e);
    })().catch(() => {});
    pending.push(p);
  });

  await new Promise(r => setTimeout(r, DURATION_MS));
  await Promise.allSettled(pending);

  const har = {
    log: {
      version: '1.2',
      creator: { name: 'cdp_har_capture (playwright-core over CDP)', version: '1.0', comment: 'DevTools Save-as-HAR blocked: native file picker unresponsive' },
      pages: [{ startedDateTime: new Date().toISOString(), id: 'page_tm_today', title: page.url(), pageTimings: {} }],
      entries: entries.map(e => ({ ...e, pageref: 'page_tm_today' })),
    },
  };
  fs.writeFileSync(OUT, JSON.stringify(har, null, 1), { mode: 0o600 });
  console.error('entries=' + entries.length + ' -> ' + OUT);
  await browser.close();
})();
