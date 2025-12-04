const profileSelect = document.getElementById('profile-select');
const activeProfileEl = document.getElementById('active-profile');
const statusText = document.getElementById('status-text');
const toastEl = document.getElementById('toast');
const loadingOverlay = document.getElementById('loading-overlay');
const loadingTitle = document.getElementById('loading-title');
const loadingSubtitle = document.getElementById('loading-subtitle');
const logsEl = document.getElementById('logs');
const propsBox = document.getElementById('properties');
const controllerChip = document.getElementById('controller-status');
const serverChip = document.getElementById('server-status');
const playitChip = document.getElementById('playit-status');
const drawer = document.getElementById('profile-drawer');
const drawerTitle = document.getElementById('drawer-title');
const propertiesPanel = document.getElementById('properties-panel');
const propertiesProfileLabel = document.getElementById('properties-profile-label');
const closeDrawerBtn = document.getElementById('close-drawer-btn');
const addProfileBtn = document.getElementById('add-profile-btn');
const logoutBtn = document.getElementById('logout-btn');
const openToolsBtn = document.getElementById('open-tools-btn');
const commandForm = document.getElementById('command-form');
const commandInput = document.getElementById('command-input');
const dialogOverlay = document.getElementById('dialog-overlay');
const dialogTitle = document.getElementById('dialog-title');
const dialogMessage = document.getElementById('dialog-message');
const dialogInputWrapper = document.getElementById('dialog-input-wrapper');
const dialogInput = document.getElementById('dialog-input');
const dialogConfirmBtn = document.getElementById('dialog-confirm-btn');
const dialogCancelBtn = document.getElementById('dialog-cancel-btn');
const dialogCloseBtn = document.getElementById('dialog-close-btn');
let socket;
let cachedProfiles = [];
let currentLogProfile = '';
let selectedProfile = '';
let playitPrompted = false;
let cachedPlayitPath = '';
let dialogResolver = null;
let lastStatus = null;

const defaultProfile = {
  name: '',
  server_path: '',
  description: '',
  run_script: 'run.bat',
  admin_auth_key: '',
  auth_key: '',
  shutdown_key: '',
  inactivity_limit: 1800,
  polling_interval: 60,
  pc_sleep_after_inactivity: true,
  shutdown_app_after_inactivity: true,
};

let toastTimeout;

function authHeaders(extra = {}) {
  const headers = { ...extra };
  const key = globalThis.ADMIN_AUTH_KEY || globalThis.AUTH_KEY;
  if (key) {
    headers.Authorization = `Bearer ${key}`;
  }
  return headers;
}

function setStatus(message, isError = false) {
  if (!toastEl) return;

  // Clear any existing timeout immediately
  if (toastTimeout) {
    clearTimeout(toastTimeout);
    toastTimeout = null;
  }

  // Remove show class to reset animation
  toastEl.classList.remove('show');

  // Force reflow to restart animation
  toastEl.offsetHeight; // eslint-disable-line no-unused-expressions

  toastEl.textContent = message;
  toastEl.classList.remove('error', 'success');
  toastEl.classList.add(isError ? 'error' : 'success', 'show');

  toastTimeout = setTimeout(() => toastEl.classList.remove('show'), 2000);
}

function closeDialog(result) {
  if (!dialogOverlay) return;
  dialogOverlay.classList.remove('open');
  dialogOverlay.setAttribute('aria-hidden', 'true');
  const resolver = dialogResolver;
  dialogResolver = null;
  if (resolver) resolver(result || { confirmed: false });
}

function showDialog(options = {}) {
  if (!dialogOverlay || !dialogConfirmBtn || !dialogCancelBtn) {
    // Fallback to native prompts when modal markup is unavailable
    if (options.input) {
      const value = window.prompt(options.message || options.title || '', options.defaultValue || '');
      return Promise.resolve({ confirmed: Boolean(value !== null), value: value ? value.trim() : null });
    }
    const confirmed = window.confirm(options.message || options.title || '');
    return Promise.resolve({ confirmed });
  }
  const {
    title = 'Confirm',
    message = '',
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    showCancel = true,
    input = false,
    placeholder = '',
    defaultValue = '',
  } = options;

  dialogTitle.textContent = title;
  dialogMessage.textContent = message;
  dialogConfirmBtn.textContent = confirmText;
  dialogCancelBtn.textContent = cancelText;
  dialogCancelBtn.classList.toggle('hidden', !showCancel);
  dialogInputWrapper.classList.toggle('hidden', !input);
  if (dialogInput) {
    if (input) {
      dialogInput.value = defaultValue || '';
      dialogInput.placeholder = placeholder || '';
    } else {
      dialogInput.value = '';
      dialogInput.placeholder = '';
    }
  }

  dialogOverlay.classList.add('open');
  dialogOverlay.setAttribute('aria-hidden', 'false');

  setTimeout(() => {
    if (input && dialogInput) dialogInput.focus();
    else dialogConfirmBtn.focus();
  }, 20);

  return new Promise((resolve) => {
    dialogResolver = resolve;
    dialogConfirmBtn.onclick = () =>
      closeDialog({ confirmed: true, value: input ? dialogInput.value.trim() : null });
    dialogCancelBtn.onclick = () => closeDialog({ confirmed: false });
    dialogCloseBtn.onclick = () => closeDialog({ confirmed: false });
    dialogOverlay.onclick = (event) => {
      if (event.target === dialogOverlay) closeDialog({ confirmed: false });
    };
  });
}

function showInputDialog(options = {}) {
  return showDialog({ ...options, input: true });
}

async function ensurePlayitConfigured() {
  if (!lastStatus) {
    lastStatus = await refreshStatus();
  }
  if (lastStatus && lastStatus.playit_configured) return true;

  setStatus('No path is defined for Playit.exe', true);
  const saved = await promptForPlayitPath();
  if (saved) {
    lastStatus = await refreshStatus();
  }
  return Boolean(lastStatus && lastStatus.playit_configured);
}

function showLoading(show, title = null, subtitle = null) {
  if (!loadingOverlay) return;
  if (title && loadingTitle) loadingTitle.textContent = title;
  if (subtitle && loadingSubtitle) loadingSubtitle.textContent = subtitle;
  loadingOverlay.classList.toggle('show', Boolean(show));
}

function setChip(chipEl, isOn) {
  const valueSpan = chipEl.querySelector('.status-value');
  if (valueSpan) {
    valueSpan.textContent = isOn ? 'Running' : 'Stopped';
  }
  chipEl.classList.toggle('status-on', isOn);
  chipEl.classList.toggle('status-off', !isOn);
}

function updateServerChip(state) {
  if (!serverChip) return;
  const stateText = state || 'stopped';
  const pretty =
    stateText === 'starting'
      ? 'Starting...'
      : stateText === 'stopping'
        ? 'Stopping...'
        : stateText.charAt(0).toUpperCase() + stateText.slice(1);

  const valueSpan = serverChip.querySelector('.status-value');
  if (valueSpan) {
    valueSpan.textContent = pretty;
  }

  serverChip.classList.remove('status-on', 'status-off', 'status-starting', 'status-stopping');
  if (stateText === 'running') {
    serverChip.classList.add('status-on');
  } else if (stateText === 'starting') {
    serverChip.classList.add('status-starting');
  } else if (stateText === 'stopping') {
    serverChip.classList.add('status-stopping');
  } else {
    serverChip.classList.add('status-off');
  }
}

function updatePlayitChip(configured, running) {
  if (!playitChip) return;
  const value = configured ? (running ? 'Running' : 'Stopped') : 'Not configured';

  const valueSpan = playitChip.querySelector('.status-value');
  if (valueSpan) {
    valueSpan.textContent = value;
  }

  playitChip.classList.toggle('status-on', Boolean(configured && running));
  playitChip.classList.toggle('status-off', !configured || !running);
  playitChip.classList.toggle('status-starting', false);
}

function toggleDrawer(open) {
  if (!drawer) return;
  // Move focus out before hiding to avoid aria-hidden/focus conflicts
  if (!open && document.activeElement && drawer.contains(document.activeElement)) {
    document.activeElement.blur();
  }
  drawer.classList.toggle('open', Boolean(open));
  drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
  drawer.toggleAttribute('inert', !open);
  if (!open) {
    drawer.removeAttribute('data-profile-name');
  }
  if (open) {
    setTimeout(() => {
      const nameInput = drawer.querySelector('input[name="name"]');
      if (nameInput) nameInput.focus();
    }, 30);
  } else {
    if (addProfileBtn) addProfileBtn.focus();
  }
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
  // Track checkbox fields that should be sent as booleans
  const checkboxKeys = new Set(['pc_sleep_after_inactivity', 'shutdown_app_after_inactivity']);
  data.forEach((value, key) => {
    if (checkboxKeys.has(key)) {
      payload[key] = true;
    } else if (['inactivity_limit', 'polling_interval'].includes(key)) {
      payload[key] = Number(value || 0);
    } else {
      payload[key] = value;
    }
  });
  checkboxKeys.forEach((key) => {
    if (!payload[key]) payload[key] = false;
  });
  return payload;
}

async function fetchServerState() {
  try {
    const res = await fetch('/api/server/state', { headers: authHeaders() });
    if (!res.ok) return null;
    const body = await res.json();
    return body.state || null;
  } catch (err) {
    return null;
  }
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
  form.run_script.value = profile.run_script || '';
  form.admin_auth_key.value = profile.admin_auth_key || '';
  form.auth_key.value = profile.auth_key || '';
  form.shutdown_key.value = profile.shutdown_key || '';
  form.inactivity_limit.value = Number.isFinite(profile.inactivity_limit)
    ? profile.inactivity_limit
    : defaultProfile.inactivity_limit;
  form.polling_interval.value = Number.isFinite(profile.polling_interval)
    ? profile.polling_interval
    : defaultProfile.polling_interval;
  form.pc_sleep_after_inactivity.checked = Boolean(profile.pc_sleep_after_inactivity);
  form.shutdown_app_after_inactivity.checked =
    profile.shutdown_app_after_inactivity !== undefined
      ? Boolean(profile.shutdown_app_after_inactivity)
      : Boolean(defaultProfile.shutdown_app_after_inactivity);
}

async function refreshStatus() {
  const res = await fetch('/api/status', { headers: authHeaders() });
  const data = await res.json();
  lastStatus = data;
  cachedProfiles = data.profiles || [];
  const previousSelection = selectedProfile || profileSelect.value;
  profileSelect.innerHTML = '';
  const desiredSelection = cachedProfiles.some((p) => p.name === previousSelection)
    ? previousSelection
    : data.active_profile;

  cachedProfiles.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = p.name;
    if (p.name === desiredSelection) opt.selected = true;
    profileSelect.appendChild(opt);
  });
  activeProfileEl.textContent = data.active_profile || 'None';
  setChip(controllerChip, Boolean(data.controller_running));
  updatePlayitChip(Boolean(data.playit_configured), Boolean(data.playit_running));

  let serverState = data.server_running ? 'running' : 'stopped';
  try {
    const stateRes = await fetch('/api/server/state', { headers: authHeaders() });
    if (stateRes.ok) {
      const stateBody = await stateRes.json();
      serverState = stateBody.state;
      updateServerChip(serverState);
    } else {
      updateServerChip(serverState);
    }
  } catch (error) {
    updateServerChip(serverState);
  }

  // Update button states
  const startBtn = document.getElementById('start-server-btn');
  const stopBtn = document.getElementById('stop-server-btn');
  const forceStopBtn = document.getElementById('force-stop-server-btn');
  if (startBtn && stopBtn && forceStopBtn) {
    const isRunning = serverState === 'running';
    const isStarting = serverState === 'starting';
    const isStopping = serverState === 'stopping';
    startBtn.disabled = isRunning || isStarting;
    stopBtn.disabled = !(isRunning || isStarting || isStopping);
    // Enable force stop if server is running, starting, or stopping
    forceStopBtn.disabled = !(isRunning || isStarting || isStopping);
  }

  const active = data.active_profile || '';
  if (active && active !== currentLogProfile) {
    connectLogs(active);
  }

  const startPlayitBtn = document.getElementById('start-playit-btn');
  const stopPlayitBtn = document.getElementById('stop-playit-btn');
  const playitSettingsBtn = document.getElementById('playit-settings-btn');
  if (startPlayitBtn && stopPlayitBtn) {
    startPlayitBtn.disabled = !data.playit_configured || data.playit_running;
    stopPlayitBtn.disabled = !data.playit_running;
  }

  const startControllerBtn = document.getElementById('start-controller-btn');
  const stopControllerBtn = document.getElementById('stop-controller-btn');
  if (startControllerBtn && stopControllerBtn) {
    const controllerRunning = Boolean(data.controller_running);
    startControllerBtn.disabled = controllerRunning;
    stopControllerBtn.disabled = !controllerRunning;
  }
  if (playitSettingsBtn) {
    playitSettingsBtn.disabled = false;
    playitSettingsBtn.removeAttribute('disabled');
  }

  return data;
}


function connectLogs(profile) {
  console.log('connectLogs called for profile:', profile);
  if (!profile) {
    logsEl.textContent = '';
    if (socket) socket.disconnect();
    currentLogProfile = '';
    return;
  }
  if (socket) {
    console.log('Disconnecting existing socket');
    socket.disconnect();
    socket = null;
  }
  console.log('Creating new socket connection');
  socket = io('/', {
    reconnection: true,
    reconnectionAttempts: 10,
    reconnectionDelay: 1000,
    transports: ['polling', 'websocket'],
  });
  logsEl.textContent = '';
  socket.on('connect', () => {
    console.log('Socket connected! Emitting follow_logs for profile:', profile);
    socket.emit('follow_logs', { profile });
    currentLogProfile = profile;
  });
  socket.on('log_line', (payload) => {
    console.log('Received log_line:', payload);
    if (!payload?.message) return;
    // Append without rewriting the entire textContent to keep things snappy
    logsEl.insertAdjacentText('beforeend', `${payload.message}\n`);
    // Trim extremely long logs in the DOM to avoid sluggishness
    const maxChars = 20000;
    if (logsEl.textContent.length > maxChars) {
      logsEl.textContent = logsEl.textContent.slice(logsEl.textContent.length - maxChars);
    }
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
  loadProperties(name);
  toggleDrawer(true);
}

function closeDrawer() {
  toggleDrawer(false);
}


// javascript
// javascript
async function activateProfile(nameOverride, forceRestart = false) {
  const name = typeof nameOverride === 'string' ? nameOverride : profileSelect.value;
  const activeName = (activeProfileEl.textContent || '').trim();
  const targetName = (name || '').trim();
  const shouldForce = Boolean(forceRestart);

  if (!targetName) return;

  const sameProfile = targetName.toLowerCase() === activeName.toLowerCase();

  // If same profile and not forcing, inform and do nothing
  if (sameProfile && !shouldForce) {
    setStatus('Profile is already active', true);
    return;
  }

  // If same profile and forcing, announce restart
  if (sameProfile && shouldForce) {
    setStatus('Restarting services for active profile...');
  } else {
    setStatus(`Switching to profile ${targetName}...`);
  }

  showLoading(true, sameProfile ? 'Restarting services…' : 'Switching profile…', 'Stopping services and preparing the profile.');

  try {
    const res = await fetch(`/api/profiles/${encodeURIComponent(targetName)}/activate`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      // Hint to the server to force a restart when re\-activating the same profile
      body: JSON.stringify({ force_restart: shouldForce }),
    });

    // Try to parse JSON error gracefully
    let err = null;
    let body = null;
    try { body = await res.json(); } catch (_) { /* no body */ }

    if (res.ok) {
      setStatus(sameProfile ? `Restarted services for ${targetName}` : `Activated profile ${targetName}`);
      activeProfileEl.textContent = targetName;
      connectLogs(targetName);
      await refreshStatus();
    } else {
      setStatus((body && body.error) || 'Failed to activate/restart profile', true);
    }
  } catch (error) {
    setStatus('Unable to activate/restart profile', true);
  } finally {
    showLoading(false);
  }
}




async function deleteProfile() {
  const name = profileSelect.value;
  if (!name) return setStatus('Choose a profile first', true);
  const isActive = activeProfileEl && activeProfileEl.textContent === name;
  const { confirmed } = await showDialog({
    title: 'Delete profile',
    message: isActive
      ? `Delete active profile "${name}"? This will stop its services and remove it.`
      : `Delete profile "${name}"? This only removes it from your list.`,
    confirmText: 'Delete',
    cancelText: 'Cancel',
  });
  if (!confirmed) return;
  const res = await fetch(`/api/profiles/${encodeURIComponent(name)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'Profile deleted');
    await refreshStatus();
    closeDrawer();
    const nextProfile = profileSelect.value;
    connectLogs(nextProfile || '');
  } else {
    setStatus(body.error || 'Unable to delete profile', true);
  }
}

async function saveProfile(evt) {
  evt.preventDefault();
  const payload = toDict(evt.target);

  // Check for duplicate profile names
  const profileName = payload.name.trim();
  const existingProfile = cachedProfiles.find(p => p.name.toLowerCase() === profileName.toLowerCase());
  const isEditing = cachedProfiles.some(p => p.name === drawer.dataset.profileName);

  if (existingProfile && (!isEditing || drawer.dataset.profileName.toLowerCase() !== profileName.toLowerCase())) {
    setStatus('A profile with this name already exists. Please choose a different name.', true);
    return;
  }

  if (!isAbsolutePath(payload.server_path)) {
    setStatus('Server folder must be an absolute path (e.g. C:/Servers/Pack or /srv/mc/pack)', true);
    return;
  }

  if (!payload.admin_auth_key || !payload.admin_auth_key.trim()) {
    setStatus('ADMIN_AUTHKEY is required', true);
    return;
  }

  const exists = cachedProfiles.some((p) => p.name === payload.name);
  const url = exists ? `/api/profiles/${encodeURIComponent(payload.name)}` : '/api/profiles';
  const method = exists ? 'PUT' : 'POST';

  const res = await fetch(url, {
    method,
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (res.ok) {
    const isNew = !exists;
    const isActiveProfile = activeProfileEl && activeProfileEl.textContent === body.name;
    setStatus(`${exists ? 'Updated' : 'Saved'} profile ${body.name}`);

    await refreshStatus();
    profileSelect.value = body.name;
    fillFormFromProfile(body);
    setDrawerMode(`Manage ${body.name}`, true, body.name);
    loadProperties(body.name);
    closeDrawer();

    if (isNew) {
      // Hide loading before showing dialog
      showLoading(false);

      const { confirmed: shouldActivate } = await showDialog({
        title: 'Start new profile?',
        message: `Start profile "${body.name}" now? This will stop services for the current profile.`,
        confirmText: 'Start now',
        cancelText: 'Not now',
      });

      if (shouldActivate) {
        showLoading(true, 'Starting profile...', 'Initializing services for the new profile.');
        await activateProfile(body.name, true);
        showLoading(false);
      } else {
        setStatus(`Saved profile ${body.name}`);
      }
    } else if (isActiveProfile) {
      const { confirmed: restartNow } = await showDialog({
        title: 'Restart services now?',
        message: 'Changes to this active profile require services to restart to take effect. Restart now?',
        confirmText: 'Restart now',
        cancelText: 'Later',
      });
      if (restartNow) {
        await activateProfile(body.name, true);
      } else {
        setStatus('Changes saved. Restart services later to apply updates.');
      }
    }
  } else {
    setStatus(body.error || 'Unable to save profile', true);
  }
}

async function startServer() {
  const startBtn = document.getElementById('start-server-btn');
  const stopBtn = document.getElementById('stop-server-btn');

  const state = (await fetchServerState()) || (lastStatus?.server_running ? 'running' : 'stopped');
  if (state === 'running') {
    setStatus('Server is already running');
    updateServerChip('running');
    if (startBtn) startBtn.disabled = true;
    if (stopBtn) stopBtn.disabled = false;
    return;
  }

  if (state === 'starting') {
    setStatus('Server is already starting');
    updateServerChip('starting');
    if (startBtn) startBtn.disabled = true;
    if (stopBtn) stopBtn.disabled = true;
    return;
  }

  const res = await fetch('/api/start/server', { method: 'POST', headers: authHeaders() });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'Server starting');
    if (startBtn) startBtn.disabled = true;
    if (stopBtn) stopBtn.disabled = false;
    updateServerChip('starting');
    pollServerReadiness();
  } else {
    setStatus(body.error || 'Failed to start server', true);
  }
  await refreshStatus();
}

async function stopServer() {
  const startBtn = document.getElementById('start-server-btn');
  const stopBtn = document.getElementById('stop-server-btn');

  const currentState = (await fetchServerState()) || (lastStatus?.server_running ? 'running' : 'stopped');

  if (currentState === 'stopped' || currentState === 'inactive') {
    setStatus('Server is not running', true);
    updateServerChip('stopped');
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = false;
    return;
  }

  if (currentState === 'starting') {
    setStatus('Server is starting up. Please wait before stopping.', true);
    updateServerChip('starting');
    if (startBtn) startBtn.disabled = true;
    if (stopBtn) stopBtn.disabled = true;
    return;
  }

  const res = await fetch('/api/stop/server', { method: 'POST', headers: authHeaders() });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'Server stopping');
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = false;
    updateServerChip('stopping');
    pollServerShutdown();
  } else {
    setStatus(body.error || 'Failed to stop server', true);
    if ((body.error || '').toLowerCase().includes('not running')) {
      updateServerChip('stopped');
    }
  }
  await refreshStatus();
}

async function forceStopServer() {
  const { confirmed } = await showDialog({
    title: 'Force Stop Server?',
    message: 'This will immediately kill the server process without saving. Players may lose progress. Continue?',
    confirmText: 'Force Stop',
    cancelText: 'Cancel',
  });

  if (!confirmed) return;

  const stopBtn = document.getElementById('stop-server-btn');
  const startBtn = document.getElementById('start-server-btn');
  const forceStopBtn = document.getElementById('force-stop-server-btn');

  const res = await fetch('/api/stop/server/force', { method: 'POST', headers: authHeaders() });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'Server force stopped');
    if (stopBtn) stopBtn.disabled = true;
    if (forceStopBtn) forceStopBtn.disabled = true;
    if (startBtn) startBtn.disabled = false;
    updateServerChip('stopped');
    // Poll for shutdown to update chip and status
    await pollServerShutdown();
  } else {
    setStatus(body.error || 'Failed to force stop server', true);
  }
  // Always refresh status after force stop to update button states
  await refreshStatus();
}
async function pollServerReadiness(retries = 20) {
  for (let i = 0; i < retries; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    try {
      const res = await fetch('/api/server/state', { headers: authHeaders() });
      if (!res.ok) continue;
      const body = await res.json();
      updateServerChip(body.state);
      if (body.state === 'running') {
        setStatus('Server is running');
        return;
      }
    } catch (err) {
      // ignore and retry
    }
  }
}

async function pollServerShutdown(retries = 15) {
  for (let i = 0; i < retries; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    try {
      const res = await fetch('/api/server/state', { headers: authHeaders() });
      if (!res.ok) continue;
      const body = await res.json();
      updateServerChip(body.state);
      if (body.state === 'stopped' || body.state === 'inactive') {
        setStatus('Server stopped');
        return;
      }
    } catch (err) {
      // ignore and retry
    }
  }
}


async function startController() {
  const status = await refreshStatus();
  if (status?.controller_running) {
    setStatus('Controller already running');
    return;
  }

  const res = await fetch('/api/start/controller', { method: 'POST', headers: authHeaders() });
  const body = await res.json();
  if (res.ok) setStatus(body.message || 'Controller started');
  else setStatus(body.error || 'Failed to start controller', true);
  await refreshStatus();
}


async function stopController() {
  if (lastStatus && !lastStatus.controller_running) {
    setStatus('Controller is not running', true);
    return;
  }

  const res = await fetch('/api/stop/controller', { method: 'POST', headers: authHeaders() });
  const body = await res.json();
  if (res.ok) setStatus(body.message || 'Controller stopped');
  else setStatus(body.error || 'Failed to stop controller', true);
  await refreshStatus();
}

async function promptForPlayitPath() {
  if (!dialogOverlay) {
    setStatus('Unable to open dialog – missing modal markup', true);
    return false;
  }

  const defaultPath =
    (lastStatus && lastStatus.playit_path) ||
    cachedPlayitPath ||
    localStorage.getItem('playitPath') ||
    '';

  const { confirmed, value } = await showInputDialog({
    title: 'Configure PlayitGG',
    message: 'Enter the full path to PlayitGG.exe so we can start the tunnel automatically.',
    confirmText: 'Save & Start',
    cancelText: 'Cancel',
    placeholder: 'C:/foldername/PlayitGG.exe or C:/foldername/',
    defaultValue: defaultPath,
  });
  if (!confirmed) {
    setStatus('PlayitGG path not updated', true);
    return false;
  }

  const path = (value || '').trim();
  if (!path) {
    setStatus('PlayitGG path is required', true);
    return false;
  }

  // If Playit is currently running, stop it before swapping path
  if (lastStatus && lastStatus.playit_running) {
    try {
      await stopPlayit();
    } catch (_) {
      /* ignore */
    }
  }

  const res = await fetch('/api/playit/path', {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ path }),
  });
  const body = await res.json();
  if (res.ok) {
    setStatus('PlayitGG path saved');
    cachedPlayitPath = path;
    localStorage.setItem('playitPath', path);
    await refreshStatus();
    // Start Playit with the new path
    await startPlayit();
    return true;
  }

  setStatus(body.error || 'Unable to save PlayitGG path', true);
  return false;
}

async function startPlayit() {
  // Ensure we have fresh status data
  if (!lastStatus) {
    lastStatus = await refreshStatus();
  }

  if (!lastStatus || !lastStatus.playit_configured) {
    setStatus('Path to Playit.exe not configured', true);
    const configured = await promptForPlayitPath();
    if (!configured) return;
    // Refresh after configuration
    lastStatus = await refreshStatus();
  }

  if (lastStatus && lastStatus.playit_running) {
    setStatus('PlayitGG is already running', true);
    return;
  }

  const res = await fetch('/api/start/playit', { method: 'POST', headers: authHeaders() });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'PlayitGG started');
  } else if (body.require_path) {
    setStatus('Path to Playit.exe not configured', true);
    await promptForPlayitPath();
  } else {
    setStatus(body.error || 'Failed to start PlayitGG', true);
  }
  await refreshStatus();
}

async function stopPlayit() {
  // Ensure we have fresh status data
  if (!lastStatus) {
    lastStatus = await refreshStatus();
  }

  if (!lastStatus || !lastStatus.playit_configured) {
    setStatus('Path to Playit.exe not configured', true);
    return;
  }

  if (!lastStatus.playit_running) {
    setStatus('PlayitGG is not running', true);
    return; // Exit early, don't call refreshStatus
  }

  const res = await fetch('/api/stop/playit', { method: 'POST', headers: authHeaders() });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'PlayitGG stopped');
  } else {
    setStatus(body.error || 'Failed to stop PlayitGG', true);
  }
  lastStatus = await refreshStatus();
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
  const res = await fetch(`/api/profiles/${encodeURIComponent(name)}/properties`, { headers: authHeaders() });
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
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (res.ok) {
    setStatus('Properties saved');
    const isActiveProfile = activeProfileEl && activeProfileEl.textContent === name;
    if (isActiveProfile) {
      const { confirmed: restartNow } = await showDialog({
        title: 'Restart services now?',
        message: 'Property changes need a restart of the active services to take effect. Restart now?',
        confirmText: 'Restart now',
        cancelText: 'Later',
      });
      if (restartNow) {
        await activateProfile(name, true);
      } else {
        setStatus('Properties saved. Restart services later to apply updates.');
      }
    }
  } else setStatus(body.error || 'Failed to save properties', true);
}


async function sendCommand(evt) {
  evt.preventDefault();
  const command = commandInput.value.trim();
  if (!command) return setStatus('Enter a command to send', true);

  const res = await fetch('/api/server/command', {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ command }),
  });
  const body = await res.json();
  if (res.ok) {
    setStatus(body.message || 'Command sent');
    commandInput.value = '';
  } else {
    setStatus(body.error || 'Failed to send command', true);
  }
}

async function logout() {
  const result = await showDialog({
    title: 'Logout',
    message: 'Are you sure you want to logout?',
    confirmText: 'Logout',
    cancelText: 'Cancel',
  });

  if (!result.confirmed) return;

  try {
    const res = await fetch('/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    if (res.ok) {
      window.location.href = '/login';
    } else {
      setStatus('Failed to logout', true);
    }
  } catch (error) {
    console.error('Logout error:', error);
    setStatus('Failed to logout', true);
  }
}

function init() {
  document.getElementById('profile-form').addEventListener('submit', saveProfile);
  document.getElementById('activate-btn').addEventListener('click', activateProfile);
  document.getElementById('delete-profile-btn').addEventListener('click', deleteProfile);
  document.getElementById('start-server-btn').addEventListener('click', startServer);
  document.getElementById('stop-server-btn').addEventListener('click', stopServer);
  document.getElementById('force-stop-server-btn').addEventListener('click', forceStopServer);
  document.getElementById('start-controller-btn').addEventListener('click', startController);
  document.getElementById('stop-controller-btn').addEventListener('click', stopController);
  const startPlayitBtn = document.getElementById('start-playit-btn');
  const stopPlayitBtn = document.getElementById('stop-playit-btn');
  const playitSettingsBtn = document.getElementById('playit-settings-btn');
  if (startPlayitBtn) startPlayitBtn.addEventListener('click', startPlayit);
  if (stopPlayitBtn) stopPlayitBtn.addEventListener('click', stopPlayit);
  if (playitSettingsBtn) {
    playitSettingsBtn.disabled = false;
    playitSettingsBtn.addEventListener('click', (event) => {
      event.preventDefault();
      playitPrompted = false; // allow manual prompt even if we already tried
      promptForPlayitPath();
    });
  }
  document.getElementById('save-props-btn').addEventListener('click', saveProperties);
  if (addProfileBtn) addProfileBtn.addEventListener('click', openNewProfileDrawer);
  if (logoutBtn) logoutBtn.addEventListener('click', logout);
  if (openToolsBtn) openToolsBtn.addEventListener('click', openProfileTools);
  if (closeDrawerBtn) closeDrawerBtn.addEventListener('click', closeDrawer);
  if (commandForm) commandForm.addEventListener('submit', sendCommand);
  if (drawer) {
    drawer.addEventListener('click', (event) => {
      if (event.target === drawer) closeDrawer();
    });
  }
  profileSelect.addEventListener('change', () => {
    selectedProfile = profileSelect.value;
  });
  (async () => {
    try {
      const data = await refreshStatus();
      const current = profileSelect.value;
      if (current) {
        connectLogs(current);
      }
      if (data && !data.playit_configured && !playitPrompted) {
        playitPrompted = true;
        const configured = await promptForPlayitPath();
        if (configured) {
          lastStatus = await refreshStatus();
        } else {
          playitPrompted = false; // allow retry on next refresh
        }
      }
    } catch (err) {
      console.error('Initial status refresh failed', err);
    }
  })();
  setInterval(() => {
    refreshStatus().catch((err) => console.error('Periodic status refresh failed', err));
  }, 5000);
}

document.addEventListener('DOMContentLoaded', init);
