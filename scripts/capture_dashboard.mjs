/** Run: node scripts/capture_dashboard.mjs
 * Setup: npm --prefix frontend install; then npx playwright install --no-shell chromium in frontend.
 * Optional: PLAYWRIGHT_CHANNEL=msedge uses an installed Edge browser.
 * Uses the real demo endpoint and replay controls. No DOM/data/style substitutions.
 */
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = fileURLToPath(new URL('../', import.meta.url));
const require = createRequire(path.join(root, 'frontend', 'package.json'));
const { chromium } = require('playwright');
// Use the same encoder Playwright installs for recordVideo; no system FFmpeg needed.
const { registry: { registry } } = require(path.join(
  path.dirname(require.resolve('playwright-core/package.json')), 'lib/coreBundle.js'));
const out = path.join(root, 'docs', 'screens');
const api = 'http://127.0.0.1:8000';
const ui = 'http://127.0.0.1:5173';
const viewport = { width: 1600, height: 900 };
const children = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let browser;

async function available(url) {
  try { return (await fetch(url, { signal: AbortSignal.timeout(2000) })).ok; }
  catch { return false; }
}

async function start(url, command, args, cwd) {
  if (await available(url)) return;
  const child = spawn(command, args, {
    cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    detached: process.platform !== 'win32',
  });
  children.push(child);
  let failure;
  child.on('error', error => { failure = error; });
  child.stdout.on('data', data => process.stderr.write(data));
  child.stderr.on('data', data => process.stderr.write(data));
  const deadline = Date.now() + 120_000;
  while (!(await available(url))) {
    if (failure) throw failure;
    if (child.exitCode !== null) throw new Error(`${command} exited: ${child.exitCode}`);
    if (Date.now() > deadline) throw new Error(`Timed out starting ${url}`);
    await delay(500);
  }
}

async function json(route) {
  const response = await fetch(api + route, { signal: AbortSignal.timeout(300_000) });
  assert(response.ok, `${route}: HTTP ${response.status}`);
  return response.json();
}

async function ready(page) {
  await page.locator('.node').first().waitFor({ timeout: 300_000 });
  await page.locator('.graph--loading').waitFor({ state: 'hidden' });
  await page.evaluate(() => document.fonts.ready);
}

async function seek(page, index) {
  // Keyboard interaction with the app's existing native range control.
  const slider = page.getByRole('slider', { name: 'Replay position' });
  await slider.focus();
  let current = Number(await slider.inputValue());
  while (current !== index) {
    await slider.press(current < index ? 'ArrowRight' : 'ArrowLeft');
    const next = Number(await slider.inputValue());
    assert.notEqual(next, current, 'Replay slider did not move');
    current = next;
  }
  await slider.blur();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.mouse.move(1590, 890);
  await page.waitForTimeout(350); // allow the app's own color transitions to finish
}

async function verifyHealth(page, series, index) {
  for (const [service, data] of Object.entries(series.services)) {
    await page.getByRole('button', { name: `${service}: ${data.health[index]}`, exact: true }).waitFor();
  }
}

try {
  await mkdir(out, { recursive: true });
  await start(api + '/health', process.env.UV ?? 'uv',
    ['run', 'uvicorn', 'causeway.api.main:app', '--reload'], root);
  // npm.cmd needs cmd.exe on Windows; command text is fixed, never user input.
  await start(ui, process.platform === 'win32' ? 'cmd.exe' : 'npm',
    process.platform === 'win32'
      ? ['/d', '/s', '/c', 'npm run dev -- --host 127.0.0.1 --strictPort']
      : ['run', 'dev', '--', '--host', '127.0.0.1', '--strictPort'], path.join(root, 'frontend'));
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL ?? 'chromium' });
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  await page.goto(ui);
  const seedResponse = page.waitForResponse(r => r.url().endsWith('/demo/seed') && r.request().method() === 'POST', { timeout: 300_000 });
  await page.getByRole('button', { name: /^(Generate demo data|Regenerate demo data)$/ }).click();
  const seeded = await seedResponse;
  assert(seeded.ok(), 'Demo seeding failed');
  console.error('Demo dataset:', await seeded.json());
  await ready(page);
  const [series, { incidents }, graph] = await Promise.all([
    json('/api/timeseries'), json('/api/incidents'), json('/api/causal-graph'),
  ]);
  assert(graph.edges.length > 0, 'Builder returned no causal edges');
  const incident = incidents.reduce((best, item) => !best || item.services.length > best.services.length ? item : best, null);
  assert(incident, 'No incident detected');
  const indexOf = timestamp => series.timestamps.indexOf(timestamp);
  const begin = indexOf(incident.start);
  const end = indexOf(incident.end);
  assert(begin >= 0 && end > begin, 'Incident timestamps are outside the series');
  const services = Object.keys(series.services);
  const health = (s, i) => series.services[s].health[i];
  let healthy = begin - 1;
  while (healthy >= 0 && !services.every(s => health(s, healthy) === 'healthy')) healthy--;
  assert(healthy >= 0, 'No all-green pre-incident frame exists');
  const indices = Array.from({ length: end - begin }, (_, i) => begin + i);
  const cascade = indices.find(i => health('db-pool', i) === 'critical'
    && services.some(s => s !== 'db-pool' && health(s, i) === 'degraded')
    && services.some(s => health(s, i) === 'healthy'));
  const full = indices.find(i => services.every(s => health(s, i) === 'critical'));
  assert(cascade !== undefined, 'No real mid-cascade red/amber/green frame exists');
  assert(full !== undefined, 'No real full-cascade frame exists');
  const report = await json(`/api/root-cause?incident_time=${encodeURIComponent(incident.start)}`);
  assert.equal(report.root_cause, 'db-pool', 'The real report did not identify db-pool');
  assert.equal(report.causal_chain.length, 4, 'The real report did not return four hops');

  for (const [filename, index] of [['01-healthy.png', healthy], ['02-cascade.png', cascade], ['03-root-cause.png', full]]) {
    await seek(page, index);
    await verifyHealth(page, series, index);
    if (index === full) {
      await page.locator('.finding__service').filter({ hasText: /^db-pool$/ }).waitFor();
      assert.equal(await page.locator('.chain__node.is-revealed').count(), 5);
      assert.match(await page.locator('.stats').innerText(), /4\/4/);
    }
    const filenamePath = path.join(out, filename);
    await page.screenshot({ path: filenamePath });
    console.log(filenamePath);
  }
  await context.close();

  // A separate context keeps seeding and screenshot setup out of the video.
  const recording = await browser.newContext({ viewport, deviceScaleFactor: 1,
    recordVideo: { dir: path.join(out, '.recordings'), size: viewport } });
  const replay = await recording.newPage();
  const video = replay.video();
  await replay.goto(ui);
  await ready(replay);
  await replay.getByRole('button', { name: 'Rewind to incident', exact: true }).click();
  await replay.getByRole('group', { name: 'Replay speed' }).getByRole('button', { name: '1×', exact: true }).click();
  await replay.getByRole('button', { name: 'Play', exact: true }).click();
  await replay.evaluate(() => window.scrollTo(0, 0));
  await replay.mouse.move(1590, 890);
  await replay.waitForTimeout(25_000);
  await replay.getByRole('button', { name: 'Pause', exact: true }).click();
  await recording.close();
  const videoPath = path.join(out, 'replay.webm');
  const rawVideoPath = await video.path();
  // Drop initial page loading/control setup, preserving the final 25 seconds.
  // Re-encode so the cut is frame-accurate rather than tied to VP8 keyframes.
  await new Promise((resolve, reject) => {
    const encoder = spawn(registry.findExecutable('ffmpeg').executablePath(),
      ['-y', '-sseof', '-25', '-i', rawVideoPath, '-t', '25',
        '-c:v', 'libvpx', '-deadline', 'realtime', '-cpu-used', '8', '-crf', '10',
        '-b:v', '4M', videoPath], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
    let errors = '';
    encoder.stderr.on('data', data => { errors += data; });
    encoder.on('error', reject);
    encoder.on('exit', code => code === 0 ? resolve() : reject(new Error(errors)));
  });
  await video.delete();
  console.log(videoPath);
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  await browser?.close();
  for (const child of children.reverse()) {
    if (!child.pid) continue;
    if (process.platform === 'win32') {
      await new Promise(resolve => {
        const stop = spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true, stdio: 'ignore' });
        stop.on('exit', resolve);
        stop.on('error', resolve);
      });
    } else {
      try { process.kill(-child.pid, 'SIGTERM'); } catch { /* already stopped */ }
    }
  }
}
