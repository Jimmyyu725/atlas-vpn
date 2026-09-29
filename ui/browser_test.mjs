import { spawn, execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdtempSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const output = join(root, 'evidence/ui');
const profile = mkdtempSync(join(tmpdir(), 'atlas-ui-browser-'));
const login = JSON.parse(execFileSync('sudo', ['-n', 'cat', '/var/lib/atlas-vpn-ui/login.json'], { encoding: 'utf8' }));
const authorization = 'Basic ' + Buffer.from(login.username + ':' + login.password).toString('base64');
const chrome = spawn('/usr/bin/google-chrome', ['--headless=new', '--no-sandbox', '--disable-gpu', '--no-first-run', '--disable-background-networking', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let ws;
async function waitFor(predicate, label) {
  const end = Date.now() + 20000;
  while (Date.now() < end) { if (await predicate()) return; await sleep(150); }
  throw new Error('Timed out: ' + label);
}
try {
  const portFile = join(profile, 'DevToolsActivePort');
  await waitFor(() => existsSync(portFile), 'browser startup');
  const port = readFileSync(portFile, 'utf8').split('\n')[0];
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws = new WebSocket(pages.find(p => p.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let id = 0; const pending = new Map(); const errors = [];
  function call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const key = ++id;
      const timer = setTimeout(() => { pending.delete(key); reject(new Error('CDP timeout: ' + method)); }, 20000);
      pending.set(key, { resolve, reject, timer }); ws.send(JSON.stringify({ id: key, method, params }));
    });
  }
  ws.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.method === 'Page.javascriptDialogOpening') call('Page.handleJavaScriptDialog', { accept: true }).catch(() => {});
    if (data.method === 'Runtime.exceptionThrown') errors.push(data.params.exceptionDetails.text);
    const item = pending.get(data.id);
    if (!item) return;
    clearTimeout(item.timer); pending.delete(data.id);
    if (data.error) item.reject(new Error(data.error.message)); else item.resolve(data.result);
  };
  const evaluate = async expression => {
    const result = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true });
    if (result.exceptionDetails) throw new Error('Browser expression failed');
    return result.result.value;
  };
  await call('Page.enable'); await call('Network.enable'); await call('Runtime.enable');
  await call('Network.setExtraHTTPHeaders', { headers: { Authorization: authorization } });
  await call('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1024, deviceScaleFactor: 1, mobile: false });
  await call('Page.navigate', { url: 'http://10.77.0.1:8787/' });
  await waitFor(() => evaluate("document.querySelectorAll('.device').length >= 3"), 'device cards');
  const testName = 'ui-smoke-' + Date.now().toString(36);
  if (!process.argv.includes('--read-only')) {
    writeFileSync(join(output, 'browser-test-device.txt'), testName + '\n');
    await evaluate(`document.querySelector('#name').value=${JSON.stringify(testName)}; document.querySelector('#add').requestSubmit(); true`);
    const status = () => evaluate(`fetch('/api/status').then(r=>r.json()).then(s=>s.devices.find(d=>d.name===${JSON.stringify(testName)}))`);
    await waitFor(async () => Boolean(await status()), 'add device');
    await waitFor(() => evaluate('!busy'), 'add UI settled');
    const clickToggle = `Array.from(document.querySelectorAll('.device')).find(e=>e.querySelector('.device-name').textContent===${JSON.stringify(testName)}).querySelector('.actions button:last-child').click(); true`;
    await waitFor(() => evaluate(`Array.from(document.querySelectorAll('.device-name')).some(e=>e.textContent===${JSON.stringify(testName)})`), 'new device card');
    await evaluate(clickToggle);
    await waitFor(async () => (await status())?.enabled === false, 'disable device');
    await waitFor(() => evaluate('!busy'), 'disable UI settled');
    await evaluate(clickToggle);
    await waitFor(async () => (await status())?.enabled === true, 'enable device');
    await waitFor(() => evaluate('!busy'), 'enable UI settled');
    await evaluate(`Array.from(document.querySelectorAll('.device')).find(e=>e.querySelector('.device-name').textContent===${JSON.stringify(testName)}).querySelector('.actions button:first-of-type').click(); true`);
    await waitFor(() => evaluate("document.querySelector('#qr-image').complete && document.querySelector('#qr-image').naturalWidth > 0"), 'QR image');
    await evaluate("document.querySelector('#close-qr').click(); true");
    await evaluate(clickToggle);
    await waitFor(async () => (await status())?.enabled === false, 'disable temporary device for cleanup');
    await waitFor(() => evaluate('!busy'), 'cleanup UI settled');
    console.log('BROWSER PASS add=true disable=true enable=true qr=true');
  }
  if (errors.length) throw new Error('Browser runtime exceptions: ' + errors.join(';'));
  const desktop = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  writeFileSync(join(output, 'dashboard-desktop.png'), Buffer.from(desktop.data, 'base64'));
  await call('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await sleep(300);
  if (!await evaluate('document.documentElement.scrollWidth <= window.innerWidth')) throw new Error('Mobile horizontal overflow');
  const mobile = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  writeFileSync(join(output, 'dashboard-mobile.png'), Buffer.from(mobile.data, 'base64'));
  console.log('BROWSER PASS desktop=true mobile_no_overflow=true runtime_errors=0 screenshots_saved=true');
} finally {
  if (ws) ws.close();
  chrome.kill('SIGTERM');
  await Promise.race([new Promise(resolve => chrome.once('exit', resolve)), sleep(3000)]);
  rmSync(profile, { recursive: true, force: true });
}
