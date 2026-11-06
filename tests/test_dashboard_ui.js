// Exercise async UI data flow without a browser or third-party DOM dependency.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.value = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this[name] = value; }
  get firstElementChild() { return this.children[0]; }
  querySelectorAll() { return this.children.flatMap(n => [n, ...n.querySelectorAll()]).filter(n => n.tagName === 'details' && n.open); }
  focus() {}
}
const ids = ['accounts', 'usage-alerts', 'notice', 'repo', 'updated', 'usage-sync', 'refresh', 'type', 'scope', 'risk', 'workstreams', 'count', 'details'];
const elements = Object.fromEntries(ids.map(id => [id, new Element('div')]));
const windows = remaining => [{window:'weekly', remaining, units:'percent', scope:'shared', state:'available', observed_at:'2026-11-06T10:00:00Z'}];
const accounts = remaining => ({codex:{provider:'codex', plan:'test', state:'available', windows:windows(remaining)}});
let current = 80, delayedPoll, holdPoll = false, failPoll = false, outdatedServer = false;
const requests = [];
const document = {hidden:false, activeElement:null, createElement:tag => new Element(tag),
  createElementNS:(_ns, tag) => new Element(tag),
  getElementById:id => elements[id], addEventListener() {}};
const context = vm.createContext({document, URLSearchParams, AbortController, setTimeout, clearTimeout,
  setInterval(){}, console, fetch:async(path) => {
    requests.push(path);
    if(path === '/api/usage' && outdatedServer) return {ok:false,status:404,json:async()=>({error:'not found'})};
    if(path === '/api/usage' && failPoll) throw new Error('offline');
    if(path === '/api/usage' && holdPoll) {
      holdPoll = false;
      return new Promise(resolve => { delayedPoll = () => resolve({ok:true,json:async()=>({accounts:accounts(5),action_token:'token',warnings:[],checked_at:'2026-11-06T10:00:00Z'})}); });
    }
    if(path === '/api/usage/refresh') current = 95;
    return {ok:true,json:async()=>({accounts:accounts(current),action_token:'token',errors:[],warnings:[],workstreams:[],setup_needed:false,repo:'test',branch:'main',observed_at:'2026-11-06T10:00:00Z',checked_at:'2026-11-06T10:00:00Z'})};
  }});
const run = code => vm.runInContext(code, context);
const flush = () => new Promise(resolve => setImmediate(resolve));
async function main() {
  run(fs.readFileSync('coordinator/usagekit/dashboard_assets/app.js', 'utf8'));
  await flush(); await flush();
  assert.equal(run('state.accounts.codex.windows[0].remaining'), 80);
  assert.equal(run('busy'), false);
  assert.equal(elements.accounts.children[0].children[2].children[0].disabled, false, 'refresh button enabled after initial load');
  assert.equal(requests.filter(p=>p==='/api/usage/refresh').length, 0, 'initial/local reads do not fetch provider');

  holdPoll = true;
  const pending = run('pollUsage()'); await flush();
  await run('refreshUsage("codex")');
  delayedPoll(); await pending;
  assert.equal(run('state.accounts.codex.windows[0].remaining'), 95, 'old poll cannot replace fresh fetch');
  assert.equal(requests.filter(p=>p==='/api/usage/refresh').length, 1);

  failPoll = true; await run('pollUsage()');
  assert.match(elements['usage-sync'].textContent, /unavailable/);
  assert.equal(run('state.accounts.codex.windows[0].remaining'), 95, 'offline polling preserves saved values');
  run('state.accounts.codex.windows[0].state = "stale"; renderAccounts()');
  const flatten = element => [element, ...element.children.flatMap(flatten)];
  const cardNodes = flatten(elements.accounts);
  assert.equal(cardNodes.find(n => n.tagName === 'strong').textContent, '—', 'stale number must not be headline usage');
  assert.ok(cardNodes.some(n => n.textContent === 'Current usage unavailable'));
  assert.ok(cardNodes.some(n => String(n.textContent).includes('Last saved: 95% remaining')));
  run('state.accounts.codex.windows[0].state = "available"; state.accounts.codex.polling = {state:"error", error:"Sync failed"}; renderAccounts()');
  assert.ok(flatten(elements.accounts).some(n => n.textContent === 'Current usage unavailable'), 'failed provider poll must not imply current data');
  document.hidden = true;
  const count = requests.length; await run('pollUsage()');
  assert.equal(requests.length, count, 'hidden tab does not poll');
  document.hidden = false; failPoll = false; outdatedServer = true;
  await run('pollUsage()');
  assert.match(elements['usage-sync'].textContent, /server is outdated/);
  assert.match(elements['usage-sync'].textContent, /Ctrl\+C/);
  outdatedServer = false;
  await run('pollUsage()');
  run(`state.accounts.codex.windows[0] = {...state.accounts.codex.windows[0],
    remaining:10, reserve:10, reserve_alert:'reserve', alert_expires_at:'2099-01-01T00:00:00Z',
    history:{from:'2026-10-30T10:00:00Z',to:'2026-11-06T10:00:00Z',points:[
      {observed_at:'2026-11-06T08:00:00Z',remaining:20,cycle:0},
      {observed_at:'2026-11-06T08:30:00Z',remaining:10,cycle:0},
      {observed_at:'2026-11-06T09:00:00Z',remaining:100,cycle:1}]}};
    renderAccounts()`);
  assert.ok(flatten(elements['usage-alerts']).some(n => /reserve/.test(n.textContent)), 'fresh reserve alert visible');
  const historyNodes = flatten(elements.accounts);
  assert.ok(historyNodes.some(n => n.textContent === 'Usage history · 7 days'));
  assert.ok(historyNodes.some(n => n.textContent === 'New quota cycle'), 'reset boundary is labeled');
  assert.equal(historyNodes.filter(n => n.tagName === 'polyline').length, 1, 'line never crosses reset');
  const historyPanel = historyNodes.find(n => n.dataset.window === 'history:codex:weekly');
  historyPanel.open = true; run('renderAccounts()');
  assert.ok(flatten(elements.accounts).find(n => n.dataset.window === 'history:codex:weekly').open, 'history stays expanded');
  assert.equal(run('readingsKey({a:{history:{to:1}}}) === readingsKey({a:{history:{to:2}}})'), true, 'history clock does not invalidate routing');
  run('state.accounts.codex.polling = {state:"error"}; renderAccounts()');
  assert.equal(elements['usage-alerts'].children.length, 0, 'provider failure suppresses alert');
  run('delete state.accounts.codex.polling; usageErrors.codex = "failed"; renderAccounts()');
  assert.equal(elements['usage-alerts'].children.length, 0, 'manual failure suppresses alert');
  run('delete usageErrors.codex; state.accounts.codex.windows[0].alert_expires_at = "2000-01-01T00:00:00Z"; renderAccounts()');
  assert.equal(elements['usage-alerts'].children.length, 0, 'expired alert suppressed by browser clock');
  run('state.accounts.codex.windows[0].alert_expires_at = "2099-01-01T00:00:00Z"; renderAccounts()');
  failPoll = true; await run('pollUsage()');
  assert.equal(elements['usage-alerts'].children.length, 0, 'local read failure suppresses alert');
  failPoll = false;
  run('usageErrors.codex = "manual failed"; usageFailureAt.codex = 0');
  await run('pollUsage()');
  assert.equal(run('usageErrors.codex'), undefined, 'later saved observation recovers manual failure');
  console.log('Dashboard UI data-flow checks passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
