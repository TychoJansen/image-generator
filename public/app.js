const MAX_WORD_LENGTH = 50;
const MAX_WORDS = 20;
const MAX_PHOTOS = 4;
const MAX_PHOTO_SIDE = 511; // the Cloudflare photo model needs reference images smaller than 512x512
const MAX_LARGE_PHOTO_SIDE = 1024; // larger copy for OpenAI, which keeps faces more recognizable

// Which image services are set up on the server (filled in after login).
let providers = { cloudflare: true, openai: false, openaiModel: '' };

// Small per-browser memory for the chosen service and quality; the page works fine without it.
const remember = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {}
  },
};

const $ = (id) => document.getElementById(id);

// Small fetch helper: returns parsed JSON, throws an Error (with .status) carrying the server's message on failure.
async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Verzoek mislukt (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

function show(el, message) {
  el.textContent = message;
  el.hidden = !message;
}

// --- Tabs (the URL hash keeps the tab, so /#generate links straight to it) ---
const ADMIN_TABS = ['generate', 'share'];
let currentTab = 'words';

function showTab(name) {
  if (!ADMIN_TABS.includes(name)) name = 'words';
  currentTab = name;
  for (const tab of document.querySelectorAll('.tab')) {
    tab.classList.toggle('active', tab.dataset.tab === name);
  }
  $('tab-words').hidden = name !== 'words';
  if (ADMIN_TABS.includes(name)) {
    openAdmin();
  } else {
    $('tab-login').hidden = true;
    $('tab-generate').hidden = true;
    $('tab-share').hidden = true;
  }
}

window.addEventListener('hashchange', () => showTab(location.hash.slice(1)));

// --- Words tab ---
$('word-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = $('word-input').value.trim();
  show($('word-message'), '');
  if (!text) return show($('word-error'), 'Het woord mag niet leeg zijn.');
  if (text.length > MAX_WORD_LENGTH) return show($('word-error'), `Een woord mag maximaal ${MAX_WORD_LENGTH} tekens lang zijn.`);
  try {
    await api('/api/words', { method: 'POST', body: JSON.stringify({ text }) });
    $('word-input').value = '';
    $('word-input').focus();
    show($('word-error'), '');
    show($('word-message'), `Bedankt! "${text}" is toegevoegd.`);
  } catch (err) {
    show($('word-error'), err.message);
  }
});

// --- Admin tabs (Genereren, Share): show the login form until the admin is logged in ---
async function openAdmin() {
  try {
    const { admin } = await api('/api/session');
    $('tab-login').hidden = admin;
    $('tab-generate').hidden = !admin || currentTab !== 'generate';
    $('tab-share').hidden = !admin || currentTab !== 'share';
    if (!admin) {
      $('password').focus();
    } else if (currentTab === 'generate') {
      loadProviders();
      loadWords();
      loadContext();
      loadPhotos();
      loadGallery();
    } else {
      loadShare();
    }
  } catch (err) {
    $('tab-login').hidden = false;
    show($('login-error'), err.message);
  }
}

// After a 401 (session expired or server restarted), go back to the login form.
function handleAdminError(err) {
  if (err.status === 401) return openAdmin();
  show($('generate-error'), err.message);
}

$('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('/api/login', { method: 'POST', body: JSON.stringify({ password: $('password').value }) });
    $('password').value = '';
    show($('login-error'), '');
    openAdmin();
  } catch (err) {
    show($('login-error'), err.message);
  }
});

for (const btn of document.querySelectorAll('.logout-btn')) {
  btn.addEventListener('click', async () => {
    await api('/api/logout', { method: 'POST' }).catch(() => {});
    $('result').hidden = true;
    $('idle').hidden = false;
    $('preview').hidden = true;
    show($('generate-error'), '');
    openAdmin();
  });
}

// --- Share (QR code to the Words tab) ---
// Uses the address the admin is viewing the page on, so it is the public link when opened through the tunnel.
function loadShare() {
  const url = `${location.origin}/#words`;
  const qr = `/api/qr.svg?url=${encodeURIComponent(url)}`;
  $('qr-img').src = qr;
  $('qr-big').src = qr;
  $('qr-download').href = qr;
  $('share-url').textContent = url;
  $('qr-big-url').textContent = url;
  $('share-warning').hidden = !['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
}

$('qr-open').addEventListener('click', () => $('qr-dialog').showModal());
$('qr-show').addEventListener('click', () => $('qr-dialog').showModal());
$('qr-close').addEventListener('click', () => $('qr-dialog').close());
$('qr-dialog').addEventListener('click', (e) => {
  if (e.target === $('qr-dialog')) $('qr-dialog').close();
});

$('share-copy').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText($('share-url').textContent);
    $('share-copy').textContent = '✓ Gekopieerd';
  } catch {
    $('share-copy').textContent = 'Kopiëren lukt niet';
  }
  setTimeout(() => ($('share-copy').textContent = 'Link kopiëren'), 2000);
});

async function loadWords() {
  try {
    const words = await api('/api/words');
    const list = $('word-list');
    list.innerHTML = '';
    for (const word of words) {
      const li = document.createElement('li');
      li.className = 'chip';
      const label = document.createElement('label');
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.value = word.id;
      box.checked = true;
      label.append(box, word.text);
      li.append(label, deleteButton(`Verwijder "${word.text}"`, () => removeWord(word.id)));
      list.append(li);
    }
    $('no-words').hidden = words.length > 0;
    updateWordCount();
    updateModelInfo();
  } catch (err) {
    handleAdminError(err);
  }
}

function deleteButton(title, onClick) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'icon-btn';
  btn.title = title;
  btn.setAttribute('aria-label', title);
  btn.textContent = '×';
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    onClick();
  });
  return btn;
}

function updateWordCount() {
  const total = $('word-list').querySelectorAll('input').length;
  const checked = $('word-list').querySelectorAll('input:checked').length;
  $('word-count').textContent = total ? `${checked} / ${total} gekozen` : '';
}

$('word-list').addEventListener('change', updateWordCount);

function selectAllWords(checked) {
  for (const box of $('word-list').querySelectorAll('input')) box.checked = checked;
  updateWordCount();
}

$('select-all').addEventListener('click', () => selectAllWords(true));
$('select-none').addEventListener('click', () => selectAllWords(false));

async function removeWord(id) {
  try {
    await api(`/api/words/${id}`, { method: 'DELETE' });
    loadWords();
  } catch (err) {
    handleAdminError(err);
  }
}

// --- Context ---
async function loadContext() {
  try {
    const { context, glossary } = await api('/api/context');
    $('context').value = context;
    $('glossary').value = glossary;
    updateContextCount();
  } catch (err) {
    handleAdminError(err);
  }
}

function updateContextCount() {
  $('context-count').textContent = `${$('context').value.length} / ${$('context').maxLength}`;
  $('glossary-count').textContent = `${$('glossary').value.length} / ${$('glossary').maxLength}`;
}

$('context').addEventListener('input', updateContextCount);
$('glossary').addEventListener('input', updateContextCount);

async function saveContext() {
  await api('/api/context', {
    method: 'PUT',
    body: JSON.stringify({ context: $('context').value, glossary: $('glossary').value }),
  });
}

$('save-context').addEventListener('click', async () => {
  try {
    await saveContext();
    show($('context-error'), '');
    $('context-saved').hidden = false;
    setTimeout(() => ($('context-saved').hidden = true), 2000);
  } catch (err) {
    if (err.status === 401) return openAdmin();
    show($('context-error'), err.message);
  }
});

// --- Photos ---
// Shrinks the photo in the browser to JPEGs: a small one (max 511x511, for Cloudflare)
// and a large one (max 1024x1024, for OpenAI).
async function resizePhoto(file) {
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error('Deze foto kan niet worden gelezen. Gebruik een JPG- of PNG-bestand.');
  }
  const toJpeg = (maxSide) => {
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.9);
  };
  return { image: toJpeg(MAX_PHOTO_SIDE), large: toJpeg(MAX_LARGE_PHOTO_SIDE) };
}

async function loadPhotos() {
  try {
    const photos = await api('/api/photos');
    const container = $('photos');
    container.innerHTML = '';
    for (const photo of photos) {
      const card = document.createElement('div');
      card.className = 'photo';
      const label = document.createElement('label');
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.value = photo.id;
      const img = document.createElement('img');
      img.src = photo.url;
      img.alt = photo.caption || 'Foto';
      const check = document.createElement('span');
      check.className = 'check';
      check.textContent = '✓';
      const caption = document.createElement('span');
      caption.className = 'caption';
      caption.textContent = photo.caption || 'Geen beschrijving';
      caption.title = photo.caption;
      label.append(box, img, check, caption);
      card.append(label, deleteButton('Foto verwijderen', () => removePhoto(photo.id)));
      container.append(card);
    }
    $('no-photos').hidden = photos.length > 0;
    updatePhotoSelection();
  } catch (err) {
    handleAdminError(err);
  }
}

// Shows how many photos are picked.
function updatePhotoSelection() {
  const count = $('photos').querySelectorAll('input:checked').length;
  $('photo-count').textContent = `${count} / ${MAX_PHOTOS} gekozen`;
  updateModelInfo();
}

// --- Service choice (Cloudflare or OpenAI) ---
function selectedProvider() {
  return document.querySelector('input[name="provider"]:checked').value;
}

async function loadProviders() {
  try {
    providers = await api('/api/providers');
  } catch (err) {
    return handleAdminError(err);
  }
  const saved = remember.get('provider');
  if (saved) document.querySelector(`input[name="provider"][value="${saved}"]`).checked = true;
  const quality = remember.get('quality');
  if (quality) $('quality').value = quality;
  updateModelInfo();
}

// Shows which model will be used, based on the chosen service and whether photos are picked.
function updateModelInfo() {
  const withPhotos = $('photos').querySelectorAll('input:checked').length > 0;
  const openai = selectedProvider() === 'openai';
  $('quality-row').hidden = !openai;
  $('openai-missing').hidden = !openai || providers.openai;
  $('generate-btn').disabled = $('word-list').querySelectorAll('input').length === 0 || (openai && !providers.openai);

  if (openai) {
    $('model-name').textContent = providers.openaiModel || 'OpenAI';
    $('model-note').textContent = `${withPhotos ? "gebruikt je foto's · " : ''}betaald per afbeelding · kan tot een minuut duren`;
  } else if (withPhotos) {
    $('model-name').textContent = 'FLUX.2 [klein] 9B';
    $('model-note').textContent = "gebruikt je foto's · ongeveer 5 per dag gratis";
  } else {
    $('model-name').textContent = 'FLUX.1 [schnell]';
    $('model-note').textContent = 'snel, alleen tekst · ruim 150 per dag gratis';
  }
}

for (const radio of document.querySelectorAll('input[name="provider"]')) {
  radio.addEventListener('change', () => {
    remember.set('provider', selectedProvider());
    updateModelInfo();
  });
}

$('quality').addEventListener('change', () => remember.set('quality', $('quality').value));

$('photos').addEventListener('change', (e) => {
  const count = $('photos').querySelectorAll('input:checked').length;
  if (e.target.checked && count > MAX_PHOTOS) {
    e.target.checked = false;
    show($('photo-error'), `Je kunt maximaal ${MAX_PHOTOS} foto's tegelijk gebruiken.`);
  } else {
    show($('photo-error'), '');
  }
  updatePhotoSelection();
});

$('photo-file').addEventListener('change', () => {
  const file = $('photo-file').files[0];
  $('photo-file-name').textContent = file ? file.name : 'Kies een foto';
});

$('photo-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = $('photo-file').files[0];
  if (!file) return show($('photo-error'), 'Kies eerst een foto.');
  try {
    const { image, large } = await resizePhoto(file);
    await api('/api/photos', {
      method: 'POST',
      body: JSON.stringify({ image, large, caption: $('photo-caption').value }),
    });
    $('photo-form').reset();
    $('photo-file-name').textContent = 'Kies een foto';
    show($('photo-error'), '');
    loadPhotos();
  } catch (err) {
    if (err.status === 401) return openAdmin();
    show($('photo-error'), err.message);
  }
});

async function removePhoto(id) {
  try {
    await api(`/api/photos/${id}`, { method: 'DELETE' });
    loadPhotos();
  } catch (err) {
    handleAdminError(err);
  }
}

async function loadGallery() {
  try {
    const images = await api('/api/images');
    const gallery = $('gallery');
    gallery.innerHTML = '';
    for (const img of images) {
      const item = document.createElement('div');
      item.className = 'gallery-item';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'open';
      btn.title = 'Groot bekijken';
      const el = document.createElement('img');
      el.src = img.url;
      el.alt = 'Gegenereerde afbeelding';
      el.loading = 'lazy';
      btn.append(el);
      btn.addEventListener('click', () => openLightbox(img));
      item.append(btn, deleteButton('Afbeelding verwijderen', () => removeImage(img)));
      gallery.append(item);
    }
    $('gallery-empty').hidden = images.length > 0;
    $('gallery-count').textContent = images.length ? `${images.length}` : '';
  } catch (err) {
    handleAdminError(err);
  }
}

async function removeImage(img) {
  if (!confirm('Deze afbeelding definitief verwijderen?')) return false;
  try {
    await api(`/api/images/${img.filename}`, { method: 'DELETE' });
    // If it is the image shown as the latest result, clear that too.
    if ($('result-img').src.endsWith(img.url)) {
      $('result').hidden = true;
      $('idle').hidden = false;
    }
    loadGallery();
    return true;
  } catch (err) {
    handleAdminError(err);
    return false;
  }
}

// --- Lightbox ---
let lightboxImage = null;

function openLightbox(img) {
  lightboxImage = img;
  $('lightbox-img').src = img.url;
  $('lightbox-download').href = img.url;
  $('lightbox').showModal();
}

$('lightbox-delete').addEventListener('click', async () => {
  if (lightboxImage && (await removeImage(lightboxImage))) $('lightbox').close();
});

$('lightbox-close').addEventListener('click', () => $('lightbox').close());
// Clicking the dark backdrop (the dialog itself, outside its content) closes it too.
$('lightbox').addEventListener('click', (e) => {
  if (e.target === $('lightbox')) $('lightbox').close();
});

// The current selection on the Generate tab, or null (with an error shown) if it is not valid.
function currentSelection() {
  const ids = [...$('word-list').querySelectorAll('input:checked')].map((b) => Number(b.value));
  const photoIds = [...$('photos').querySelectorAll('input:checked')].map((b) => Number(b.value));
  let error = '';
  if (ids.length === 0) error = 'Selecteer minstens één woord.';
  else if (ids.length > MAX_WORDS) error = `Selecteer maximaal ${MAX_WORDS} woorden.`;
  else if (photoIds.length > MAX_PHOTOS) error = `Selecteer maximaal ${MAX_PHOTOS} foto's.`;
  if (error) {
    show($('generate-error'), error);
    return null;
  }
  return { ids, photoIds, provider: selectedProvider(), quality: $('quality').value };
}

$('preview-btn').addEventListener('click', async () => {
  const selection = currentSelection();
  if (!selection) return;
  show($('generate-error'), '');
  try {
    await saveContext();
    const { prompt } = await api('/api/prompt', { method: 'POST', body: JSON.stringify(selection) });
    $('preview').textContent = prompt;
    $('preview').hidden = false;
  } catch (err) {
    handleAdminError(err);
  }
});

$('generate-btn').addEventListener('click', async () => {
  const selection = currentSelection();
  if (!selection) return;
  const { provider } = selection;

  $('preview').hidden = true;
  show($('generate-error'), '');
  $('generate-btn').disabled = true;
  $('result').hidden = true;
  $('idle').hidden = true;
  $('status-text').textContent =
    provider === 'openai' ? 'Afbeelding wordt gegenereerd, dit kan tot een minuut duren…' : 'Afbeelding wordt gegenereerd…';
  $('status').hidden = false;
  try {
    await saveContext(); // so unsaved changes in the context box are used too
    const data = await api('/api/generate', {
      method: 'POST',
      body: JSON.stringify(selection),
    });
    $('result-prompt').textContent = data.prompt;
    $('result-img').src = data.url;
    $('result-download').href = data.url;
    $('result').hidden = false;
    loadGallery();
  } catch (err) {
    // The tunnel cuts off requests that take longer than about 100 seconds (no JSON reply, e.g. 524).
    // The server keeps going and saves the image, so check the gallery again a bit later.
    if ([502, 504, 524].includes(err.status) && err.message.startsWith('Verzoek mislukt')) {
      show($('generate-error'), 'Het genereren duurt langer dan de verbinding toelaat. De afbeelding wordt op de achtergrond afgemaakt en verschijnt zo vanzelf in de galerij.');
      setTimeout(loadGallery, 30000);
      setTimeout(loadGallery, 90000);
    } else {
      handleAdminError(err);
    }
  } finally {
    updateModelInfo();
    $('status').hidden = true;
    $('idle').hidden = !$('result').hidden;
  }
});

showTab(location.hash.slice(1));
