const MAX_WORD_LENGTH = 50;
const MAX_WORDS = 20;
const MAX_PHOTOS = 4;
const MAX_PHOTO_SIDE = 511; // the photo model needs reference images smaller than 512x512

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
function showTab(name) {
  if (name !== 'generate') name = 'words';
  for (const tab of document.querySelectorAll('.tab')) {
    tab.classList.toggle('active', tab.dataset.tab === name);
  }
  $('tab-words').hidden = name !== 'words';
  $('tab-generate').hidden = name !== 'generate';
  if (name === 'generate') openGenerate();
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
    show($('word-error'), '');
    show($('word-message'), `Bedankt! "${text}" is toegevoegd.`);
  } catch (err) {
    show($('word-error'), err.message);
  }
});

// --- Generate tab ---
async function openGenerate() {
  try {
    const { admin } = await api('/api/session');
    $('login').hidden = admin;
    $('admin').hidden = !admin;
    if (admin) {
      loadWords();
      loadContext();
      loadPhotos();
      loadGallery();
    } else {
      $('password').focus();
    }
  } catch (err) {
    $('login').hidden = false;
    show($('login-error'), err.message);
  }
}

// After a 401 (session expired or server restarted), go back to the login form.
function handleAdminError(err) {
  if (err.status === 401) return openGenerate();
  show($('generate-error'), err.message);
}

$('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('/api/login', { method: 'POST', body: JSON.stringify({ password: $('password').value }) });
    $('password').value = '';
    show($('login-error'), '');
    openGenerate();
  } catch (err) {
    show($('login-error'), err.message);
  }
});

$('logout-btn').addEventListener('click', async () => {
  await api('/api/logout', { method: 'POST' }).catch(() => {});
  $('result').hidden = true;
  show($('generate-error'), '');
  openGenerate();
});

async function loadWords() {
  try {
    const words = await api('/api/words');
    const list = $('word-list');
    list.innerHTML = '';
    for (const word of words) {
      const li = document.createElement('li');
      const label = document.createElement('label');
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.value = word.id;
      box.checked = true;
      label.append(box, ' ', word.text);
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'danger';
      del.textContent = 'Verwijderen';
      del.addEventListener('click', () => removeWord(word.id));
      li.append(label, del);
      list.append(li);
    }
    $('no-words').hidden = words.length > 0;
    $('generate-btn').disabled = words.length === 0;
  } catch (err) {
    handleAdminError(err);
  }
}

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
    const { context } = await api('/api/context');
    $('context').value = context;
  } catch (err) {
    handleAdminError(err);
  }
}

async function saveContext() {
  await api('/api/context', { method: 'PUT', body: JSON.stringify({ context: $('context').value }) });
}

$('save-context').addEventListener('click', async () => {
  try {
    await saveContext();
    show($('context-error'), '');
    $('context-saved').hidden = false;
    setTimeout(() => ($('context-saved').hidden = true), 2000);
  } catch (err) {
    if (err.status === 401) return openGenerate();
    show($('context-error'), err.message);
  }
});

// --- Photos ---
// Shrinks the photo in the browser to a JPEG of at most 511x511, as the photo model requires.
async function resizeToJpeg(file) {
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error('Deze foto kan niet worden gelezen. Gebruik een JPG- of PNG-bestand.');
  }
  const scale = Math.min(1, MAX_PHOTO_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.9);
}

async function loadPhotos() {
  try {
    const photos = await api('/api/photos');
    const container = $('photos');
    container.innerHTML = '';
    for (const photo of photos) {
      const card = document.createElement('div');
      card.className = 'photo';
      const img = document.createElement('img');
      img.src = photo.url;
      img.alt = photo.caption || 'Foto';
      const label = document.createElement('label');
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.value = photo.id;
      label.append(box, ' ', photo.caption || 'Gebruiken');
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'danger';
      del.textContent = 'Verwijderen';
      del.addEventListener('click', () => removePhoto(photo.id));
      card.append(img, label, del);
      container.append(card);
    }
    $('no-photos').hidden = photos.length > 0;
  } catch (err) {
    handleAdminError(err);
  }
}

$('photo-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = $('photo-file').files[0];
  if (!file) return show($('photo-error'), 'Kies eerst een foto.');
  try {
    const image = await resizeToJpeg(file);
    await api('/api/photos', { method: 'POST', body: JSON.stringify({ image, caption: $('photo-caption').value }) });
    $('photo-form').reset();
    show($('photo-error'), '');
    loadPhotos();
  } catch (err) {
    if (err.status === 401) return openGenerate();
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
      const a = document.createElement('a');
      a.href = img.url;
      a.target = '_blank';
      const el = document.createElement('img');
      el.src = img.url;
      el.alt = img.filename;
      el.loading = 'lazy';
      a.append(el);
      gallery.append(a);
    }
    $('gallery-empty').hidden = images.length > 0;
  } catch (err) {
    handleAdminError(err);
  }
}

$('generate-btn').addEventListener('click', async () => {
  const ids = [...$('word-list').querySelectorAll('input:checked')].map((b) => Number(b.value));
  if (ids.length === 0) return show($('generate-error'), 'Selecteer minstens één woord.');
  if (ids.length > MAX_WORDS) return show($('generate-error'), `Selecteer maximaal ${MAX_WORDS} woorden.`);
  const photoIds = [...$('photos').querySelectorAll('input:checked')].map((b) => Number(b.value));
  if (photoIds.length > MAX_PHOTOS) return show($('generate-error'), `Selecteer maximaal ${MAX_PHOTOS} foto's.`);

  show($('generate-error'), '');
  $('generate-btn').disabled = true;
  $('status').hidden = false;
  try {
    await saveContext(); // so unsaved changes in the context box are used too
    const data = await api('/api/generate', { method: 'POST', body: JSON.stringify({ ids, photoIds }) });
    $('result-prompt').textContent = data.prompt;
    $('result-img').src = data.url;
    $('result').hidden = false;
    loadGallery();
  } catch (err) {
    handleAdminError(err);
  } finally {
    $('generate-btn').disabled = false;
    $('status').hidden = true;
  }
});

showTab(location.hash.slice(1));
