const profileSelect = document.getElementById('profile-select');
const activeProfileEl = document.getElementById('active-profile');
const statusText = document.getElementById('status-text');
const toastEl = document.getElementById('toast');
const loadingOverlay = document.getElementById('loading-overlay');
const logsEl = document.getElementById('logs');
const propsBox = document.getElementById('properties');
const apiChip = document.getElementById('api-status');
const controllerChip = document.getElementById('controller-status');
const serverChip = document.getElementById('server-status');
const drawer = document.getElementById('profile-drawer');
const drawerTitle = document.getElementById('drawer-title');
const propertiesPanel = document.getElementById('properties-panel');
const propertiesProfileLabel = document.getElementById('properties-profile-label');
const closeDrawerBtn = document.getElementById('close-drawer-btn');
const addProfileBtn = document.getElementById('add-profile-btn');
const openToolsBtn = document.getElementById('open-tools-btn');
let socket;
let cachedProfiles = [];

const defaultProfile = {
  name: '',
  server_path: '',
  description: '',
  server_ip: 'localhost',
  run_script: 'run.bat',
  auth_key: '',
  shutdown_key: '',
  inactivity_limit: 120,
  polling_interval: 60,
  pc_sleep_after_inactivity: true,
};

let toastTimeout;

function setStatus(message, isError = false) {
  if (statusText) {
    statusText.textContent = '';
  }
  if (!toastEl) return;

  toastEl.textContent = message;
  toastEl.classList.remove('error', 'success');
  toastEl.classList.add(isError ? 'error' : 'success', 'show');

  if (toastTimeout) clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => toastEl.classList.remove('show'), 2000);
}

function showLoading(show) {
  if (!loadingOverlay) return;
  loadingOverlay.classList.toggle('show', Boolean(show));
}

function setChip(chipEl, isOn, label) {
  chipEl.textContent = `${label}: ${isOn ? 'Running' : 'Stopped'}`;
  chipEl.classList.toggle('status-on', isOn);
  chipEl.classList.toggle('status-off', !isOn);
}

function toggleDrawer(open) {
  if (!drawer) return;
  drawer.classList.toggle('open', Boolean(open));
  drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
}

function setDrawerMode(title, showProperties, profileName = '') {
  if (drawerTitle) drawerTitle.textContent = title;
  if (propertiesPanel) propertiesPanel.classList.toggle('hidden', !showProperties);
  if (propertiesProfileLabel) {
    propertiesProfileLabel.textContent = `Profile: ${profileName || 'None'}`;
  }
  drawer.dataset.profileName = profileName || '';
}

function toDict(form) {
  const data = new FormData(form);
  const payload = {};
  data.forEach((value, key) => {
    if (key === 'pc_sleep_after_inactivity') {
      payload[key] = true;
    } else if (['inactivity_limit', 'polling_interval'].includes(key)) {
      payload[key] = Number(value || 0);
    } else {
      payload[key] = value;
    }
  });
  if (!payload.pc_sleep_after_inactivity) payload.pc_sleep_after_inactivity = false;
  return payload;
}

function isAbsolutePath(path) {
  if (!path) return false;
  const trimmed = path.trim();
  return /^([a-zA-Z]:[\\/]|\/)/.test(trimmed);
}

function fillFormFromProfile(profile) {
  if (!profile) profile = defaultProfile;
  const form = document.getElementById('profile-form');
  form.name.value = profile.name || '';
  form.server_path.value = profile.server_path || '';
  form.description.value = profile.description || '';
  form.server_ip.value = profile.server_ip || '';
  form.run_script.value = profile.run_script || '';
  form.auth_key.value = profile.auth_key || '';
  form.shutdown_key.value = profile.shutdown_key || '';
  form.inactivity_limit.value = Number.isFinite(profile.inactivity_limit)
    ? profile.inactivity_limit
    : defaultProfile.inactivity_limit;
  form.polling_interval.value = Number.isFinite(profile.polling_interval)
    ? profile.polling_interval
    : defaultProfile.polling_interval;
  form.pc_sleep_after_inactivity.checked = Boolean(profile.pc_sleep_after_inactivity);
}

async function refreshStatus() {
  const res = await fetch('/api/status');
  const data = await res.json();
  cachedProfiles = data.profiles || [];
  profileSelect.innerHTML = '';
  cachedProfiles.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = p.name;
    if (p.name === data.active_profile) opt.selected = true;
    profileSelect.appendChild(opt);
  });
  activeProfileEl.textContent = data.active_profile || 'None';
  setChip(apiChip, Boolean(data.api_running), 'API');
  setChip(controllerChip, Boolean(data.controller_running), 'Controller');
  setChip(serverChip, Boolean(data.server_running), 'Server');

  // Update button states
  const startBtn = document.getElementById('start-server-btn');
  const stopBtn = document.getElementById('stop-server-btn');
  if (startBtn && stopBtn) {
    startBtn.disabled = Boolean(data.server_running);
    stopBtn.disabled = !Boolean(data.server_running);
  }
}

function connectLogs(profile) {
  console.log('connectLogs called for profile:', profile);
  if (!profile) {
    logsEl.textContent = '';
    if (socket) socket.disconnect();
    return;
  }
  if (socket) {
    console.log('Disconnecting existing socket');
    socket.disconnect();
    socket = null;
  }
  console.log('Creating new socket connection');
  socket = io({
    reconnection: true,
    reconnectionAttempts: 10,
    reconnectionDelay: 1000
  });
  logsEl.textContent = '';
  socket.on('connect', () => {
    console.log('Socket connected! Emitting follow_logs for profile:', profile);
    socket.emit('follow_logs', { profile });
  });
  socket.on('log_line', (payload) => {
    console.log('Received log_line:', payload);
    if (!payload || !payload.message) return;
    logsEl.textContent += payload.message + '\n';
    logsEl.scrollTop = logsEl.scrollHeight;
  });
  socket.on('disconnect', () => {
    console.log('Socket disconnected, will reconnect in 2 seconds');
    setTimeout(() => {
      if (socket && !socket.connected) {
        console.log('Attempting to reconnect socket');
        socket.connect();
      }
    }, 2000);
  });
  socket.on('connect_error', (error) => {
    console.error('Socket connection error:', error);
  });
}

function openNewProfileDrawer() {
  fillFormFromProfile(defaultProfile);
  if (propsBox) propsBox.value = '';
  setDrawerMode('Create profile', false, '');
  toggleDrawer(true);
}

function openProfileTools() {
  const name = profileSelect.value;
  if (!name) return setStatus('Choose a profile first', true);
  const found = cachedProfiles.find((p) => p.name === name) || defaultProfile;
  fillFormFromProfile(found);
  setDrawerMode(`Manage ${name}`, true, name);
  connectLogs(name);
  loadProperties(name);
  toggleDrawer(true);
}

function closeDrawer() {
  toggleDrawer(false);
}

async function activateProfile() {
  const name = profileSelect.value;
  if (!name) return;
  showLoading(true);
  try {
    const res = await fetch(`/api/profiles/${encodeURIComponent(name)}/activate`, { method: 'POST' });
    if (res.ok) {
      setStatus(`Activated profile ${name}`);
      activeProfileEl.textContent = name;
      connectLogs(name);
      await refreshStatus();
    } else {
      const err = await res.json();
      setStatus(err.error || 'Failed to activate profile', true);
    }
  } catch (error) {
    setStatus('Unable to activate profile', true);
  } finally {
    showLoading(false);
  }
}


async function deleteProfile() {
  const name = profileSelect.value;
  if (!name) return setStatus('Choose a profile first', true);
  const res = await fetch(`/api/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'Profile deleted');
    await refreshStatus();
    connectLogs(profileSelect.value);
  } else {
    setStatus(body.error || 'Unable to delete profile', true);
  }
}

async function saveProfile(evt) {
  evt.preventDefault();
  const payload = toDict(evt.target);

  if (!isAbsolutePath(payload.server_path)) {
    setStatus('Server folder must be an absolute path (e.g. C:/Servers/Pack or /srv/mc/pack)', true);
    return;
  }

  const exists = cachedProfiles.some((p) => p.name === payload.name);
  const url = exists ? `/api/profiles/${encodeURIComponent(payload.name)}` : '/api/profiles';
  const method = exists ? 'PUT' : 'POST';

  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (res.ok) {
    setStatus(`${exists ? 'Updated' : 'Saved'} profile ${body.name}`);
    await refreshStatus();
    profileSelect.value = body.name;
    fillFormFromProfile(body);
    connectLogs(body.name);
    setDrawerMode(`Manage ${body.name}`, true, body.name);
    loadProperties(body.name);
  } else {
    setStatus(body.error || 'Unable to save profile', true);
  }
}

async function startServer() {
  const startBtn = document.getElementById('start-server-btn');
  const stopBtn = document.getElementById('stop-server-btn');

  const res = await fetch('/api/start/server', { method: 'POST' });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'Server starting');
    startBtn.disabled = true;
    stopBtn.disabled = false;
  } else {
    setStatus(body.error || 'Failed to start server', true);
  }
  await refreshStatus();
}

async function stopServer() {
  const startBtn = document.getElementById('start-server-btn');
  const stopBtn = document.getElementById('stop-server-btn');

  const res = await fetch('/api/stop/server', { method: 'POST' });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'Server stopped');
    startBtn.disabled = false;
    stopBtn.disabled = true;
  } else {
    setStatus(body.error || 'Failed to stop server', true);
  }
  await refreshStatus();
}

async function startApi() {
  const res = await fetch('/api/start/api', { method: 'POST' });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'API starting');
  } else setStatus(body.error || 'Failed to start API', true);
  await refreshStatus();
}

async function startController() {
  const res = await fetch('/api/start/controller', { method: 'POST' });
  const body = await res.json();
  if (res.ok) setStatus(body.message || 'Controller started');
  else setStatus(body.error || 'Failed to start controller', true);
  await refreshStatus();
}

async function stopApi() {
  const res = await fetch('/api/stop/api', { method: 'POST' });
  const body = await res.json();
  if (res.ok) setStatus(body.message || 'API stopped');
  else setStatus(body.error || 'Failed to stop API', true);
  await refreshStatus();
}

async function stopController() {
  const res = await fetch('/api/stop/controller', { method: 'POST' });
  const body = await res.json();
  if (res.ok) setStatus(body.message || 'Controller stopped');
  else setStatus(body.error || 'Failed to stop controller', true);
  await refreshStatus();
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
      output[key] = line.slice(idx + 1).trim();
    });
  return output;
}

async function loadProperties(profileName) {
  const name = profileName || drawer.dataset.profileName || profileSelect.value;
  if (!name) return setStatus('Choose a profile first', true);
  const res = await fetch(`/api/profiles/${encodeURIComponent(name)}/properties`);
  const body = await res.json();
  if (res.ok) {
    propsBox.value = propsToText(body);
    if (propertiesProfileLabel) propertiesProfileLabel.textContent = `Profile: ${name}`;
    setStatus('Loaded properties');
  } else {
    setStatus(body.error || 'Unable to load properties', true);
  }
}

async function saveProperties() {
  const name = drawer.dataset.profileName || profileSelect.value;
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
  document.getElementById('profile-form').addEventListener('submit', saveProfile);
  document.getElementById('activate-btn').addEventListener('click', activateProfile);
  document.getElementById('delete-profile-btn').addEventListener('click', deleteProfile);
  document.getElementById('start-server-btn').addEventListener('click', startServer);
  document.getElementById('stop-server-btn').addEventListener('click', stopServer);
  document.getElementById('start-api-btn').addEventListener('click', startApi);
  document.getElementById('start-controller-btn').addEventListener('click', startController);
  document.getElementById('stop-api-btn').addEventListener('click', stopApi);
  document.getElementById('stop-controller-btn').addEventListener('click', stopController);
  document.getElementById('load-props-btn').addEventListener('click', loadProperties);
  document.getElementById('save-props-btn').addEventListener('click', saveProperties);
  if (addProfileBtn) addProfileBtn.addEventListener('click', openNewProfileDrawer);
  if (openToolsBtn) openToolsBtn.addEventListener('click', openProfileTools);
  if (closeDrawerBtn) closeDrawerBtn.addEventListener('click', closeDrawer);
  if (drawer) {
    drawer.addEventListener('click', (event) => {
      if (event.target === drawer) closeDrawer();
    });
  }
  profileSelect.addEventListener('change', () => {
    const name = profileSelect.value;
    connectLogs(name);
  });
  refreshStatus().then(() => {
    const current = profileSelect.value;
    if (current) {
      connectLogs(current);
    }
  });
  setInterval(refreshStatus, 5000);
}

document.addEventListener('DOMContentLoaded', init);
