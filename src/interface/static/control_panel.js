const profileSelect = document.getElementById('profile-select');
const activeProfileEl = document.getElementById('active-profile');
const statusText = document.getElementById('status-text');
const logsEl = document.getElementById('logs');
const propsBox = document.getElementById('properties');
let socket;

function setStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.style.color = isError ? 'var(--del-color, #c62828)' : 'inherit';
}

function toDict(form) {
  const data = new FormData(form);
  const payload = {};
  data.forEach((value, key) => {
    if (key === 'pc_sleep_after_inactivity') {
      payload[key] = true;
    } else if (['rcon_port', 'query_port', 'inactivity_limit', 'polling_interval'].includes(key)) {
      payload[key] = Number(value || 0);
    } else {
      payload[key] = value;
    }
  });
  if (!payload.pc_sleep_after_inactivity) payload.pc_sleep_after_inactivity = false;
  return payload;
}

async function refreshStatus() {
  const res = await fetch('/api/status');
  const data = await res.json();
  const profiles = data.profiles || [];
  profileSelect.innerHTML = '';
  profiles.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = p.name;
    if (p.name === data.active_profile) opt.selected = true;
    profileSelect.appendChild(opt);
  });
  activeProfileEl.textContent = data.active_profile || 'None';
}

function connectLogs(profile) {
  if (socket) {
    socket.disconnect();
  }
  socket = io();
  logsEl.textContent = '';
  socket.on('connect', () => {
    socket.emit('follow_logs', { profile });
  });
  socket.on('log_line', (payload) => {
    if (!payload || !payload.message) return;
    logsEl.textContent += `${payload.message}\n`;
    logsEl.scrollTop = logsEl.scrollHeight;
  });
}

async function activateProfile() {
  const name = profileSelect.value;
  if (!name) return;
  const res = await fetch(`/api/profiles/${encodeURIComponent(name)}/activate`, { method: 'POST' });
  if (res.ok) {
    setStatus(`Activated profile ${name}`);
    activeProfileEl.textContent = name;
    connectLogs(name);
  } else {
    const err = await res.json();
    setStatus(err.error || 'Failed to activate profile', true);
  }
}

async function bootstrapProfile() {
  const name = profileSelect.value;
  if (!name) return;
  const res = await fetch(`/api/profiles/${encodeURIComponent(name)}/bootstrap`, { method: 'POST' });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'Folders prepared');
  } else {
    setStatus(body.error || 'Failed to create folders', true);
  }
}

async function createProfile(evt) {
  evt.preventDefault();
  const payload = toDict(evt.target);
  const res = await fetch('/api/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (res.status === 201) {
    setStatus(`Saved profile ${body.name}`);
    evt.target.reset();
    await refreshStatus();
  } else {
    setStatus(body.error || 'Unable to save profile', true);
  }
}

async function startApi() {
  const res = await fetch('/api/start/api', { method: 'POST' });
  const body = await res.json();
  if (res.ok) setStatus(body.message || 'API starting');
  else setStatus(body.error || 'Failed to start API', true);
}

async function startController() {
  const res = await fetch('/api/start/controller', { method: 'POST' });
  const body = await res.json();
  if (res.ok) setStatus(body.message || 'Controller started');
  else setStatus(body.error || 'Failed to start controller', true);
}

function propsToText(map) {
  return Object.entries(map || {})
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');
}

function textToProps(text) {
  const output = {};
  text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
    .forEach((line) => {
      const idx = line.indexOf('=');
      if (idx === -1) return;
      const key = line.slice(0, idx).trim();
      const val = line.slice(idx + 1).trim();
      output[key] = val;
    });
  return output;
}

async function loadProperties() {
  const name = profileSelect.value;
  if (!name) return setStatus('Choose a profile first', true);
  const res = await fetch(`/api/profiles/${encodeURIComponent(name)}/properties`);
  const body = await res.json();
  if (res.ok) {
    propsBox.value = propsToText(body);
    setStatus('Loaded properties');
  } else {
    setStatus(body.error || 'Unable to load properties', true);
  }
}

async function saveProperties() {
  const name = profileSelect.value;
  if (!name) return setStatus('Choose a profile first', true);
  const payload = textToProps(propsBox.value);
  const res = await fetch(`/api/profiles/${encodeURIComponent(name)}/properties`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (res.ok) setStatus('Properties saved');
  else setStatus(body.error || 'Failed to save properties', true);
}

function init() {
  document.getElementById('profile-form').addEventListener('submit', createProfile);
  document.getElementById('activate-btn').addEventListener('click', activateProfile);
  document.getElementById('bootstrap-btn').addEventListener('click', bootstrapProfile);
  document.getElementById('start-api-btn').addEventListener('click', startApi);
  document.getElementById('start-controller-btn').addEventListener('click', startController);
  document.getElementById('load-props-btn').addEventListener('click', loadProperties);
  document.getElementById('save-props-btn').addEventListener('click', saveProperties);
  refreshStatus().then(() => {
    const current = profileSelect.value;
    if (current) connectLogs(current);
  });
}

document.addEventListener('DOMContentLoaded', init);
