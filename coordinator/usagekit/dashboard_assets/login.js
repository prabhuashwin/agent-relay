'use strict';
document.getElementById('pair-form').onsubmit = async event => {
  event.preventDefault();
  const button = document.getElementById('pair-submit');
  const status = document.getElementById('pair-status');
  const code = document.getElementById('pair-code');
  button.disabled = true; status.textContent = 'Pairing…';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch('/api/pair', {method:'POST', credentials:'same-origin', signal:controller.signal,
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code:code.value.trim(), label:document.getElementById('device-name').value.trim()})});
    code.value = '';
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Pairing failed.');
    window.location.replace('/');
  } catch (error) {
    status.textContent = error.name === 'AbortError' ? 'Pairing timed out. Reload to check whether it succeeded.' : error.message;
  } finally { code.value = ''; clearTimeout(timer); button.disabled = false; }
};
