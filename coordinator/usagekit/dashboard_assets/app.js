'use strict';
let state, selected, busy = false;
let usagePolling = false, fetchingUsage = null;
let usageEpoch = 0;
let usageUnavailable = false;
const usageErrors = {};
const usageFailureAt = {};
const $ = id => document.getElementById(id);
function el(tag, text, cls) { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; }
function badge(text) { return el('span', text, 'badge ' + (['passed','available','matches','released'].includes(text) ? 'good' : ['failed','changed-during-check','exhausted'].includes(text) ? 'bad' : 'warn')); }
function note(text, ok=false) { $('notice').replaceChildren(el('div', text, ok?'success':'error')); }
function list(parent, items) { const ul=el('ul'); for(const item of items) ul.append(el('li',item)); parent.append(ul); }
function section(title) {
  const collapsible = ['Checkpoint', 'Verification evidence'].includes(title);
  const s = el(collapsible ? 'details' : 'div', null, 'block');
  if (collapsible) { const summary = el('summary'); summary.append(el('h3', title)); s.append(summary); }
  else s.append(el('h3', title));
  return s;
}
function date(text) { return text ? new Date(text).toLocaleString() : 'unknown'; }
async function request(path, body) {
  const opts=body?{method:'POST',headers:{'Content-Type':'application/json','X-Relay-Token':state.action_token},body:JSON.stringify(body)}:{};
  const controller = new AbortController(); opts.signal = controller.signal;
  const timeout = setTimeout(() => controller.abort(), 35000);
  try {
    const response = await fetch(path, opts);
    if (response.status === 401) {
      window.location.replace('/');
      throw new Error('Session expired or revoked. Pair this device again.');
    }
    if (response.status === 404 && path.startsWith('/api/usage')) {
      throw new Error('Dashboard server is outdated. Stop it with Ctrl+C, then restart: python coordinator/usagectl.py board serve');
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Request failed');
    return data;
  }
  finally { clearTimeout(timeout); }
}
async function refresh(fromUsage = false) {
  if(busy || (fetchingUsage && fromUsage !== true))return; busy=true;$('refresh').disabled=true;
  usageEpoch++;
  try {
    const q=new URLSearchParams({type:$('type').value,scope:$('scope').value,risk:$('risk').value});
    state=await request('/api/status?'+q);recoverUsageErrors(state.accounts);usageUnavailable=false;$('notice').replaceChildren();
    if(state.errors.length)note(state.errors.join(' '));
    $('repo').textContent=state.repo+' · '+(state.branch||'detached HEAD');
    $('updated').textContent='Updated '+new Date(state.observed_at).toLocaleTimeString();
    renderAccounts(); renderStreams();
  } catch(error) { usageUnavailable=true; note(error.message+' Displayed data may be out of date.'); }
  finally { busy=false;$('refresh').disabled=Boolean(fetchingUsage);if(state)renderAccounts(); }
}
function renderAccounts() {
  $('remote-access').hidden = !state.remote_access?.authenticated;
  if (state.remote_access?.authenticated) {
    $('device-session').textContent = state.remote_access.label;
    $('logout').disabled = busy || Boolean(fetchingUsage);
  }
  renderUsageAlerts();
  const opened = new Set(Array.from($('accounts').querySelectorAll('details[open]')).map(n => n.dataset.window));
  const accountOpen = new Map(Array.from($('accounts').querySelectorAll('details'))
    .filter(n => n.className === 'account-details').map(n => [n.dataset.window, n.open]));
  const focused = document.activeElement?.id;
  const box=$('accounts');box.replaceChildren();
  if(state.setup_needed){box.append(el('div','No accounts configured. Run usagectl init, then add your accounts and usage windows.','empty'));return;}
  for(const [alias,a] of Object.entries(state.accounts)) {
    const card=el('article',null,'account');const title=el('div',null,'account-title');title.append(el('h3',alias),badge(a.state));card.append(title,el('div',a.provider+' · '+a.plan,'muted'));
    card.append(renderQuotaSummary(a));
    const info = el('details', null, 'account-details');
    info.dataset.window = 'account:' + alias;
    info.open = accountOpen.has(info.dataset.window) ? accountOpen.get(info.dataset.window) : !window.matchMedia?.('(max-width: 600px)').matches;
    const more = el('summary', 'Details & history'); more.id = 'account-more-' + alias;
    info.append(more);
    if (a.provider === 'codex' || a.can_refresh) {
      const controls = el('div', null, 'usage-controls');
      const button = el('button', fetchingUsage === alias ? 'Fetching usage…' : 'Refresh usage');
      button.id = 'fetch-' + alias;
      button.disabled = Boolean(fetchingUsage) || busy;
      button.onclick = () => refreshUsage(alias);
      controls.append(button, el('p', a.provider === 'claude' ?
        'Experimental account sync using your local Claude login. Includes usage from other devices.' :
        'Reads the current Codex CLI login. This alias must match that account.', 'muted'));
      info.append(controls);
      if (a.polling) {
        info.append(el('p', a.polling.state === 'error' ? a.polling.error :
          'Account sync every ' + a.polling.interval_seconds + 's · ' +
          (a.polling.last_success ? 'last success ' + age(a.polling.last_success) : 'waiting for provider'), 'usage-hint'));
        if (a.polling.state === 'error') info.append(el('p',
          'Last successful sync: ' + (a.polling.last_success ? date(a.polling.last_success) : 'none') +
          ' · Retry: ' + date(a.polling.next_attempt) + ' · Failed attempts: ' + (a.polling.failures || 1), 'muted'));
      } else {
        info.append(el('p', 'Automatic account sync is off. Start the server with --codex-account ' + alias, 'usage-hint'));
      }
    } else {
      info.append(el('p', a.capture_enabled ? 'Terminal capture enabled · updates after Claude responses. No on-demand fetch.' : 'Terminal capture is off for this account. Enable it to receive updates.', 'usage-hint'));
      if (!a.capture_enabled) info.append(el('pre', 'usagectl config capture-claude --account ' + alias));
    }
    if (usageErrors[alias]) card.append(el('p', usageErrors[alias] + ' Last saved readings are shown below.', 'usage-error'));
    const windows = el('div', null, 'windows');
    for (const w of a.windows) {
      const row = el('div', null, 'window');
      const labels = {five_hour:'Current session', seven_day:'Weekly · all models', fable_weekly:'Weekly · Fable'};
      row.append(el('p', labels[w.window] || (w.window === 'weekly' ? 'Weekly limit' : w.window.replaceAll('_', ' ')), 'window-label'));
      const value = el('div', null, 'window-value');
      const current = w.remaining != null && ['available', 'exhausted'].includes(w.state) && a.polling?.state !== 'error';
      value.append(el('strong', current ? String(w.remaining) + (w.units === 'percent' ? '%' : '') : '—'),
        el('span', current ? (w.units === 'percent' ? 'remaining' : w.units + ' remaining') : 'Current usage unavailable'));
      row.append(value);
      if (!current && w.remaining != null) {
        row.append(el('p', 'Last saved: ' + w.remaining + (w.units === 'percent' ? '%' : ' ' + w.units) + ' remaining · ' + age(w.observed_at), 'historical-reading'));
      } else if (current && w.units === 'percent') {
        row.append(el('p', (Math.round((100 - w.remaining) * 100) / 100) + '% used', 'muted'));
      }
      if (current && w.units === 'percent' && w.state === 'available' && Number.isFinite(w.remaining)) {
        const meter = el('meter'); meter.min = 0; meter.max = 100; meter.value = Math.max(0, Math.min(100, w.remaining));
        meter.setAttribute('aria-label', w.window + ' remaining'); row.append(meter);
      }
      row.append(badge(w.state));
      row.append(el('p', w.observed_at ? 'Updated ' + age(w.observed_at) : 'No observation received', 'observation-age'));
      if (w.scope !== 'shared') row.append(el('p', a.provider === 'claude' && a.polling ? 'Model allowance · account sync' : 'Model allowance · manual update may be needed', 'muted'));
      const observation = el('details', null, 'observation');
      observation.dataset.window = alias + ':' + w.window;
      observation.open = opened.has(observation.dataset.window);
      observation.append(el('summary', 'Observation details'), el('p', 'Observed ' + date(w.observed_at) + ' · resets ' + date(w.resets_at) + ' · source: ' + (w.source || 'unknown'), 'muted'));
      row.append(observation);
      row.append(renderHistory(alias, w, opened));
      windows.append(row);
    }
    info.append(windows);
    card.append(info);
    box.append(card);
  }
  if (focused && (focused.startsWith('fetch-') || focused.startsWith('account-more-'))) $(focused)?.focus();
}
function renderQuotaSummary(account) {
  const summary = el('div', null, 'quota-summary');
  summary.append(el('p', 'Remaining', 'quota-heading'));
  const timestamp = account.windows[0]?.observed_at;
  const sharedTime = timestamp && account.windows.every(w => w.observed_at === timestamp);
  const labels = {five_hour:'Session', seven_day:'Weekly', weekly:'Weekly', fable_weekly:'Fable weekly'};
  for (const w of account.windows) {
    const item = el('div', null, 'quota-item');
    const current = w.remaining != null && ['available','exhausted'].includes(w.state) && account.polling?.state !== 'error';
    const line = el('div', null, 'quota-line');
    line.append(el('span', labels[w.window] || w.window.replaceAll('_',' ')),
      el('strong', current ? String(w.remaining) + (w.units === 'percent' ? '%' : ' ' + w.units) : '\u2014'));
    item.append(line);
    if (current && w.units === 'percent' && Number.isFinite(w.remaining)) {
      const meter = el('meter'); meter.min=0; meter.max=100; meter.value=Math.max(0,Math.min(100,w.remaining));
      meter.setAttribute('aria-label', (labels[w.window] || w.window) + ' remaining'); item.append(meter);
    }
    if (!current || !sharedTime) item.append(el('p', current ? 'Updated ' + (w.observed_at ? age(w.observed_at) : 'at an unknown time') : 'Current usage unavailable', current ? 'quota-caption' : 'quota-caption quota-warning'));
    summary.append(item);
  }
  if (sharedTime) summary.append(el('p', 'Updated ' + age(timestamp), 'quota-freshness'));
  if (account.polling?.state === 'error') summary.append(el('p', 'Account sync failed. Open details for the error.', 'usage-error'));
  return summary;
}
function renderUsageAlerts() {
  const box = $('usage-alerts');
  box.replaceChildren();
  if (usageUnavailable) return;
  for (const [alias, account] of Object.entries(state.accounts)) {
    if (account.polling?.state === 'error' || usageErrors[alias]) continue;
    for (const w of account.windows) {
      if (!w.reserve_alert || !['available', 'exhausted'].includes(w.state) ||
          !(Date.parse(w.alert_expires_at) > Date.now())) continue;
      const unit = w.units === 'percent' ? '%' : ' ' + w.units;
      const text = alias + ' · ' + w.window.replaceAll('_', ' ') + ': ' +
        (w.reserve_alert === 'exhausted' ? 'Quota exhausted' : 'At or below reserve') +
        ' · ' + w.remaining + unit + ' remaining · reserve ' + w.reserve + unit;
      box.append(el('p', text, 'reserve-alert'));
    }
  }
}
function recoverUsageErrors(accounts) {
  for (const [alias, account] of Object.entries(accounts)) {
    if (!usageErrors[alias] || account.polling?.state === 'error') continue;
    const success = Math.max(Date.parse(account.polling?.last_success) || 0,
      ...account.windows.map(w => Date.parse(w.observed_at) || 0));
    if (success > usageFailureAt[alias]) {
      delete usageErrors[alias]; delete usageFailureAt[alias];
    }
  }
}
function svgElement(tag, attributes) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}
function renderHistory(alias, w, opened) {
  const panel = el('details', null, 'usage-history');
  panel.dataset.window = 'history:' + alias + ':' + w.window;
  panel.open = opened.has(panel.dataset.window);
  panel.append(el('summary', 'Usage history · 7 days'));
  if (!w.history) {
    panel.append(el('p', 'History unavailable. Restart the dashboard server to load this feature.', 'muted'));
    return panel;
  }
  const points = w.history.points;
  if (!points.length) {
    panel.append(el('p', 'No saved readings in the last seven days.', 'muted'));
    return panel;
  }
  const start = Date.parse(w.history.from), end = Date.parse(w.history.to);
  const ceiling = w.units === 'percent' ? 100 : Math.max(1, ...points.map(p => p.remaining));
  const x = p => 12 + 336 * (Date.parse(p.observed_at) - start) / (end - start);
  const y = p => 108 - 96 * p.remaining / ceiling;
  const chart = svgElement('svg', {viewBox:'0 0 360 120', role:'img',
    'aria-label': w.window + ' remaining over seven days. Exact readings in the table below.'});
  const segments = [];
  for (const point of points) {
    const last = segments.at(-1)?.at(-1);
    if (!last || last.cycle !== point.cycle || Date.parse(point.observed_at) - Date.parse(last.observed_at) > 7200000) segments.push([]);
    segments.at(-1).push(point);
  }
  chart.append(svgElement('line', {x1:12,y1:108,x2:348,y2:108,class:'history-axis'}));
  const scale = svgElement('text', {x:12,y:10,class:'history-scale'});
  scale.textContent = '0–' + ceiling + (w.units === 'percent' ? '%' : ' ' + w.units);
  chart.append(scale);
  for (const segment of segments) {
    if (segment.length > 1) chart.append(svgElement('polyline', {
      points:segment.map(p => x(p).toFixed(2) + ',' + y(p).toFixed(2)).join(' '),class:'history-line'}));
    for (const point of segment) chart.append(svgElement('circle', {cx:x(point),cy:y(point),r:2,class:'history-point'}));
  }
  panel.append(chart, el('p', date(w.history.from) + ' — ' + date(w.history.to), 'muted'));
  panel.append(el('p', 'Remaining ' + w.units + ' · hourly first, low, high and last readings. Lines stop at cycle changes or gaps over two hours.', 'muted'));
  const table = el('table'), head = el('tr');
  for (const label of ['Observed', 'Remaining', 'Resets']) head.append(el('th', label));
  const thead = el('thead'); thead.append(head); table.append(thead);
  const body = el('tbody');
  let previous;
  for (const point of points) {
    if (previous && previous.cycle !== point.cycle) {
      const boundary = el('tr'), label = el('td', point.boundary === 'reset-unknown' ?
        'Reading change · reset unknown' : 'New quota cycle', 'history-boundary');
      label.setAttribute('colspan', '3'); boundary.append(label); body.append(boundary);
    }
    const row = el('tr');
    row.append(el('td', date(point.observed_at)), el('td', point.remaining + (w.units === 'percent' ? '%' : ' ' + w.units)), el('td', date(point.resets_at)));
    body.append(row); previous = point;
  }
  table.append(body);
  const scroll = el('div', null, 'history-table'); scroll.setAttribute('tabindex', '0');
  scroll.setAttribute('role', 'region'); scroll.setAttribute('aria-label', w.window + ' history readings');
  scroll.append(table); panel.append(scroll);
  return panel;
}
function age(timestamp) {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000));
  if (seconds < 60) return seconds + 's ago';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
  return Math.floor(seconds / 86400) + 'd ago';
}
function readingsKey(accounts) {
  return JSON.stringify(accounts, (key, value) => ['age_minutes', 'history'].includes(key) ? undefined : value);
}
async function pollUsage() {
  if (document.hidden || usagePolling || fetchingUsage || busy || !state) return;
  usagePolling = true;
  const epoch = usageEpoch;
  try {
    const result = await request('/api/usage');
    // Do not overwrite a provider refresh or workspace load started during this request.
    if (fetchingUsage || busy || epoch !== usageEpoch) return;
    const changed = readingsKey(state.accounts) !== readingsKey(result.accounts);
    state.accounts = result.accounts; state.action_token = result.action_token;
    state.remote_access = result.remote_access;
    recoverUsageErrors(result.accounts);
    usageUnavailable = false;
    state.setup_needed = !Object.keys(result.accounts).length;
    renderAccounts();
    $('usage-sync').textContent = result.warnings.length ? result.warnings.join(' ') : 'Saved readings · auto-updating';
    if (changed && state.workstreams.length) $('updated').textContent = 'Usage changed · reload workspace to update routing';
  } catch (error) {
    usageUnavailable = true; renderUsageAlerts();
    $('usage-sync').textContent = error.message.startsWith('Dashboard server is outdated') ? error.message : 'Local updates unavailable. Displayed readings may be out of date.';
  } finally { usagePolling = false; }
}
async function refreshUsage(alias) {
  if (fetchingUsage || busy) return;
  usageEpoch++;
  fetchingUsage = alias; renderAccounts();
  for (const id of ['refresh','type','scope','risk']) $(id).disabled = true;
  $('usage-sync').textContent = 'Fetching account limits from the provider…';
  try {
    const result = await request('/api/usage/refresh', {account: alias});
    delete usageErrors[alias]; delete usageFailureAt[alias];
    state.accounts = result.accounts; state.action_token = result.action_token;
    usageUnavailable = false;
    $('updated').textContent = 'Usage changed · reload workspace to update routing';
    await refresh(true);
    $('usage-sync').textContent = 'Account reading fetched from the provider';
  } catch (error) {
    usageErrors[alias] = error.name === 'AbortError' ? 'Refresh timed out; reload local readings to check the outcome.' : error.message;
    usageFailureAt[alias] = Date.now();
    $('usage-sync').textContent = 'Provider refresh failed. Last saved readings retained.';
  } finally { fetchingUsage = null; for (const id of ['refresh','type','scope','risk']) $(id).disabled = false; renderAccounts(); }
}
function renderStreams() {
  const box=$('workstreams');box.replaceChildren();$('count').textContent=state.workstreams.length;
  if(!state.workstreams.some(w=>w.slug===selected))selected=state.workstreams[0]?.slug;
  if (!selected) {
    const empty = el('div', null, 'empty');
    const icon = el('span', '⌘', 'empty-icon'); icon.setAttribute('aria-hidden', 'true');
    empty.append(icon, el('h3', 'A fresh start'), el('p', 'Your workstreams will appear here when you save your first checkpoint.')); box.append(empty);
    const start = el('div', null, 'empty-detail');
    start.append(el('h3', 'Bring your first task into focus.'), el('p', 'Save a checkpoint from your project terminal. Then refresh to see its progress, verification, and next step here.'),
      el('div', 'PREPARE A CHECKPOINT', 'step-label'), el('pre', 'usagectl handoff prepare --workstream my-task --owner YOUR_ACCOUNT --goal "Your objective" --next "Next action"'));
    $('details').replaceChildren(start); return;
  }
  for(const w of state.workstreams){const card=el('button',null,'stream'+(w.slug===selected?' selected':''));card.setAttribute('aria-pressed',String(w.slug===selected));const row=el('div',null,'row');row.append(el('h3',w.slug),badge(w.checkpoint_matches?w.status:'checkpoint stale'));card.append(row,el('p',w.goal),el('div',w.owner+' · checks: '+w.verification.status,'muted'));card.onclick=()=>{selected=w.slug;renderStreams();};box.append(card);}
  renderDetails(state.workstreams.find(w=>w.slug===selected));
}
function renderDetails(w) {
  const box=$('details');box.replaceChildren();
  const next=section('Continue the work');next.append(el('p',w.next_action));
  const r=w.recommendation, advice=el('div',null,'recommendation');advice.append(badge(r.action||'unknown'),el('p',(r.recommended?'Account: '+r.recommended+' · ':'')+'Confidence: '+r.confidence));list(advice,r.reasons);if(r.uncertainty)advice.append(el('p',r.uncertainty));advice.append(el('p',r.next_step));next.append(advice);box.append(next);
  const cp=section('Checkpoint');cp.append(badge(w.checkpoint_matches?'matches':'stale'),el('p','Prepared '+date(w.prepared_at),'muted'));if(w.mismatches.length)list(cp,w.mismatches);if(w.acceptance.length){cp.append(el('h3','Acceptance criteria'));list(cp,w.acceptance);}if(w.remaining.length){cp.append(el('h3','Remaining'));list(cp,w.remaining);}if(w.failures.length){cp.append(el('h3','Known blockers'));list(cp,w.failures);}box.append(cp);
  cp.firstElementChild.append(cp.children[1]);
  const v=section('Verification evidence');v.firstElementChild.append(badge(w.verification.status));
  if(w.verification.command){v.append(el('pre',w.verification.command.join(' ')),el('p','Finished '+date(w.verification.finished_at)+' · exit '+w.verification.exit_code,'muted'));if(w.verification.output_tail)v.append(el('pre',w.verification.output_tail));}
  v.append(el('p','Evidence covers the last recorded command, not every acceptance criterion. Checks run explicitly from your terminal.','muted'),el('pre','usagectl board check --workstream '+w.slug+' -- python -m unittest discover -q'));
  if(w.reported_verification.length){v.append(el('h3','Reported in checkpoint · not independently executed'));list(v,w.reported_verification.map(c=>c.command+': '+c.status+' — '+c.result));}box.append(v);
  const transfer=section('Transfer ownership');transfer.append(el('p','Stop the source agent before releasing. Relay cannot stop or lock independent IDE sessions. Both steps recheck the repository.','muted'));
  if(w.status==='released'){
    const label=el('label','Destination account');const select=el('select');for(const alias of Object.keys(state.accounts)){const option=el('option',alias);option.value=alias;select.append(option);}label.append(select);transfer.append(label);
    const claim=el('button','Claim & prepare resume prompt','primary');claim.disabled=!select.options.length;
    claim.onclick=()=>action(claim,'/api/claim',{workstream:w.slug,to:select.value,ticket:w.release_ticket});transfer.append(el('p','Source released. Choose the account that will continue.'),claim);
  } else {
    const label=el('label',null,'confirm'),check=el('input');check.type='checkbox';label.append(check,el('span','I stopped the source writer ('+w.owner+') and am ready to release ownership.'));const release=el('button','Release ownership','primary');release.disabled=true;check.onchange=()=>release.disabled=!check.checked||!w.checkpoint_matches;release.onclick=()=>action(release,'/api/release',{workstream:w.slug,owner:w.owner,source_stopped:check.checked});transfer.append(label,release);
  }
  box.append(transfer);
}
async function action(button, path, body) {
  if (fetchingUsage || busy) { note('Wait for the current refresh to finish before transferring ownership.'); return; }
  button.disabled = true;
  try {
    const result = await request(path, body);
    await refresh();
    note(result.warning || (result.status === 'claimed' ? 'Ownership transferred. Copy the resume prompt below.' : 'Ownership released. The destination can now claim it.'), !result.warning);
    if (result.prompt) {
      const panel = section('Resume prompt'), text = el('textarea');
      text.readOnly = true; text.value = result.prompt; text.setAttribute('aria-label', 'Resume prompt');
      const copy = el('button', 'Copy prompt');
      copy.onclick = async () => {
        try { await navigator.clipboard.writeText(result.prompt); copy.textContent = 'Copied'; }
        catch { text.select(); note('Select and copy the resume prompt manually.'); }
      };
      panel.append(text, copy); $('details').append(panel);
    }
  } catch (error) { note(error.message); button.disabled = false; }
}
function updateMobileNavigation() {
  const inWorkstreams = $('workspace').getBoundingClientRect().top <= window.innerHeight * .45;
  $('nav-accounts').setAttribute('aria-current', inWorkstreams ? 'false' : 'location');
  $('nav-workstreams').setAttribute('aria-current', inWorkstreams ? 'location' : 'false');
}
document.addEventListener('scroll', updateMobileNavigation, {passive:true});
window.addEventListener?.('resize', updateMobileNavigation);
$('refresh').onclick=refresh;for(const id of ['type','scope','risk'])$(id).onchange=refresh;
$('logout').onclick = async () => {
  if (busy || fetchingUsage) return;
  $('logout').disabled = true;
  try { await request('/api/logout', {}); window.location.replace('/'); }
  catch (error) { note(error.message); $('logout').disabled = false; }
};
refresh().then(pollUsage).then(updateMobileNavigation);
setInterval(() => { if (state && !document.hidden) renderUsageAlerts(); pollUsage(); }, 5000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) pollUsage(); });
