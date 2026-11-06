'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ids = ['pair-form', 'pair-submit', 'pair-status', 'pair-code', 'device-name'];
const elements = Object.fromEntries(ids.map(id => [id, {value:'',disabled:false,textContent:''}]));
let redirect, sent, succeed = true;
const context = vm.createContext({document:{getElementById:id=>elements[id]},
  window:{location:{replace:path=>{redirect=path;}}}, AbortController, setTimeout, clearTimeout,
  fetch:async (path, options) => {
    sent = {path, options};
    return {ok:succeed, json:async()=>succeed ? {action_token:'csrf'} : {error:'Pairing failed'}};
  }});
vm.runInContext(fs.readFileSync('coordinator/usagekit/dashboard_assets/login.js','utf8'), context);
async function main() {
  for (const id of ids) assert.ok(fs.readFileSync('coordinator/usagekit/dashboard_assets/login.html','utf8').includes('id="'+id+'"'));
  elements['pair-code'].value = ' secret-code ';
  elements['device-name'].value = ' My phone ';
  await elements['pair-form'].onsubmit({preventDefault(){}});
  assert.equal(redirect, '/');
  assert.equal(sent.path, '/api/pair');
  assert.deepEqual(JSON.parse(sent.options.body), {code:'secret-code',label:'My phone'});
  assert.equal(elements['pair-code'].value, '');
  assert.equal(elements['pair-submit'].disabled, false);
  succeed = false; redirect = undefined; elements['pair-code'].value = 'bad';
  await elements['pair-form'].onsubmit({preventDefault(){}});
  assert.equal(redirect, undefined);
  assert.equal(elements['pair-status'].textContent, 'Pairing failed');
  assert.equal(elements['pair-code'].value, '');
  console.log('Device pairing UI checks passed');
}
main().catch(error => {console.error(error); process.exitCode=1;});
