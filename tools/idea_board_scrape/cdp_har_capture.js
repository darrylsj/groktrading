// Passive network capture -> HAR.
// DevTools Save-as-HAR is blocked by an unresponsive native file picker on the box.
// This file pre-scrubs secrets. Still run redact_har.py before any HAR is kept.
// Do not write a raw (non-REDACTED) HAR inside the git repo.

const fs = require('fs');
const path = require('path');

const SECRET_NAME = /token|nonce|password|passwd|pwd|secret|api[-_]?key|apikey|session|sessid|auth|bearer|email|distinct_id|device_id|credential|cookie|signature/i;
const URL_HEADERS = new Set(['referer', 'referrer', 'location', 'content-location']);
const REDACT = '[REDACTED]';

function scrubUrl(url) {
  if (!url) return url || '';
  let parsed;
  try { parsed = new URL(url); } catch (err) { return REDACT; }
  parsed.username = '';
  parsed.password = '';
  const keys = [...parsed.searchParams.keys()];
  for (const key of keys) {
    if (SECRET_NAME.test(key)) parsed.searchParams.set(key, REDACT);
  }
  if (parsed.hash && SECRET_NAME.test(parsed.hash)) parsed.hash = '#' + REDACT;
  return parsed.toString();
}

function scrubText(text) {
  if (!text) return text || '';
  let out = String(text);
  out = out.replace(
    /("(?:[^"]*(?:token|nonce|password|passwd|secret|api_?key|apikey|session|auth|email|distinct_id|device_id)[^"]*)"\s*:\s*)"(?:\\.|[^"\\])*"/ig,
    '$1"' + REDACT + '"'
  );
  out = out.replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, REDACT);
  out = out.replace(/(bearer\s+)[A-Za-z0-9._\-+/=]{6,}/ig, '$1' + REDACT);
  return out;
}

function scrubHeaders(list) {
  return (list || []).map((header) => {
    const name = String(header.name || '');
    const lower = name.toLowerCase();
    if (URL_HEADERS.has(lower)) return { name, value: scrubUrl(String(header.value || '')) };
    if (SECRET_NAME.test(lower)) return { name, value: REDACT };
    return { name, value: header.value };
  });
}

function scrubQuery(url) {
  let parsed;
  try { parsed = new URL(url); } catch (err) { return []; }
  return [...parsed.searchParams.entries()].map(([name, value]) => (
    { name, value: SECRET_NAME.test(name) ? REDACT : value }
  ));
}

function decodeUtf8(buf) {
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(buf);
    return text;
  } catch (err) {
    return null;
  }
}

function assertHarDestination(outPath) {
  const abs = path.resolve(outPath);
  const repo = path.resolve(__dirname, '..', '..');
  const rel = path.relative(repo, abs);
  const inside = rel && !rel.startsWith('..') && !path.isAbsolute(rel);
  if (inside && !/REDACTED/i.test(path.basename(abs))) {
    console.error('REFUSE raw HAR inside the repo: ' + abs);
    process.exit(3);
  }
  if (!/REDACTED/i.test(path.basename(abs)) && !abs.startsWith('/tmp/')) {
    console.error('REFUSE raw HAR outside /tmp without REDACTED in the filename: ' + abs);
    process.exit(3);
  }
}

function scrubPageTitle(url) {
  return scrubUrl(url);
}

async function main() {
  const OUT = process.argv[2];
  const DURATION_MS = parseInt(process.argv[3] || '90000', 10);
  const MATCH = process.argv[4] || 'trademachine.com';
  const MAX_BODY = 3 * 1024 * 1024;
  if (!OUT) {
    console.error('usage: cdp_har_capture.js OUT_REDACTED.har [duration_ms] [url_match]');
    process.exit(2);
  }
  assertHarDestination(OUT);
  const { chromium } = require('/usr/local/lib/node_modules/playwright-core');
  const CDP = 'http://127.0.0.1:9232';

  const browser = await chromium.connectOverCDP(CDP);
  const ctx = browser.contexts()[0];
  const pages = ctx.pages();
  const page = pages.find((item) => (item.url() || '').includes(MATCH));
  if (!page) {
    console.error('NO_TM_PAGE');
    process.exit(2);
  }
  console.error('attached to: ' + scrubUrl(page.url()));

  const entries = [];
  const pending = [];

  page.on('response', async (resp) => {
    const req = resp.request();
    const resourceType = req.resourceType();
    const task = (async () => {
      const requestHeaders = scrubHeaders(
        Object.entries(await req.allHeaders().catch(() => ({}))).map(([name, value]) => ({ name, value }))
      );
      const responseHeaders = scrubHeaders(
        Object.entries(await resp.allHeaders().catch(() => ({}))).map(([name, value]) => ({ name, value }))
      );
      const location = responseHeaders.find((header) => header.name.toLowerCase() === 'location');
      const entry = {
        startedDateTime: new Date().toISOString(),
        time: 0,
        _resourceType: resourceType,
        request: {
          method: req.method(),
          url: scrubUrl(req.url()),
          httpVersion: 'HTTP/1.1',
          headers: requestHeaders,
          queryString: scrubQuery(req.url()),
          cookies: [],
          headersSize: -1,
          bodySize: -1,
        },
        response: {
          status: resp.status(),
          statusText: resp.statusText(),
          httpVersion: 'HTTP/1.1',
          headers: responseHeaders,
          cookies: [],
          content: { size: -1, mimeType: '', text: '' },
          redirectURL: location ? location.value : '',
          headersSize: -1,
          bodySize: -1,
        },
        cache: {},
        timings: { send: 0, wait: 0, receive: 0 },
      };
      const post = req.postData();
      if (post) {
        const contentType = (await req.allHeaders().catch(() => ({})))['content-type'] || '';
        entry.request.postData = {
          mimeType: contentType,
          text: scrubText(post.slice(0, MAX_BODY)),
          params: [],
        };
      }
      const contentType = (
        entry.response.headers.find((header) => header.name.toLowerCase() === 'content-type') || {}
      ).value || '';
      entry.response.content.mimeType = contentType;
      const keepBody = resourceType === 'xhr' || resourceType === 'fetch' || resourceType === 'document'
        || /json|text/i.test(contentType);
      if (keepBody) {
        try {
          const buf = await resp.body();
          const slice = buf.slice(0, MAX_BODY);
          const text = decodeUtf8(slice);
          if (text === null) {
            entry.response.content.text = '';
            entry.response.content._error = 'unsupported_encoding';
          } else {
            entry.response.content.size = buf.length;
            entry.response.content.text = scrubText(text);
          }
        } catch (err) {
          entry.response.content._error = String(err.message || err).slice(0, 200);
        }
      }
      entries.push(entry);
    })().catch(() => {});
    pending.push(task);
  });

  await new Promise((resolve) => setTimeout(resolve, DURATION_MS));
  await Promise.allSettled(pending);

  const har = {
    log: {
      version: '1.2',
      creator: {
        name: 'cdp_har_capture (playwright-core over CDP)',
        version: '1.0',
        comment: 'pre-scrubbed; run redact_har.py before keeping the file',
      },
      pages: [{
        startedDateTime: new Date().toISOString(),
        id: 'page_1',
        title: scrubPageTitle(page.url()),
        pageTimings: {},
      }],
      entries: entries.map((entry) => ({ ...entry, pageref: 'page_1' })),
    },
  };
  fs.writeFileSync(OUT, JSON.stringify(har, null, 1), { mode: 0o600 });
  console.error('entries=' + entries.length + ' -> ' + OUT + ' (still run redact_har.py; do not commit raw HARs)');
  await browser.close();
}

module.exports = {
  scrubUrl,
  scrubText,
  scrubHeaders,
  scrubQuery,
  decodeUtf8,
  assertHarDestination,
  scrubPageTitle,
};

if (require.main === module) {
  main().catch((err) => {
    console.error(String(err && err.message ? err.message : err));
    process.exit(1);
  });
}
