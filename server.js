require('dotenv').config();

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const express = require('express');
const Database = require('better-sqlite3');
const QRCode = require('qrcode');

const PORT = process.env.PORT || 3000;
const CF_MODEL = '@cf/black-forest-labs/flux-1-schnell';
// Used when reference photos are selected: accepts up to 4 input images, but costs more of the daily free limit.
const CF_PHOTO_MODEL = '@cf/black-forest-labs/flux-2-klein-9b';
const MAX_WORD_LENGTH = 50;
const MAX_WORDS_PER_PROMPT = 20;
const MAX_CONTEXT_LENGTH = 1000;
const MAX_CAPTION_LENGTH = 100;
const MAX_PHOTOS_STORED = 20;
const MAX_PHOTOS_PER_PROMPT = 4;
const MAX_PHOTO_BYTES = 1024 * 1024;
const SESSION_COOKIE = 'admin_session';
const SESSION_MS = 12 * 60 * 60 * 1000;
const MAX_LOGIN_ATTEMPTS = 5;
const LOGIN_LOCK_MS = 15 * 60 * 1000;

const PUBLIC_DIR = path.join(__dirname, 'public');
const IMAGES_DIR = path.join(PUBLIC_DIR, 'images');
// Reference photos live outside public/ and are only served to the admin.
const PHOTOS_DIR = path.join(__dirname, 'uploads');
fs.mkdirSync(IMAGES_DIR, { recursive: true });
fs.mkdirSync(PHOTOS_DIR, { recursive: true });

// --- Database ---
const db = new Database(path.join(__dirname, 'words.db'));
db.exec(`
  CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
  );
  CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
`);

const listWords = db.prepare('SELECT id, text, created_at FROM words ORDER BY id DESC');
const insertWord = db.prepare('INSERT INTO words (text) VALUES (?)');
const getWord = db.prepare('SELECT id, text, created_at FROM words WHERE id = ?');
const deleteWord = db.prepare('DELETE FROM words WHERE id = ?');

const getSetting = db.prepare('SELECT value FROM settings WHERE key = ?');
const setSetting = db.prepare(
  'INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value'
);

const listPhotos = db.prepare('SELECT id, filename, caption FROM photos ORDER BY id DESC');
const countPhotos = db.prepare('SELECT COUNT(*) AS n FROM photos');
const insertPhoto = db.prepare('INSERT INTO photos (filename, caption) VALUES (?, ?)');
const getPhoto = db.prepare('SELECT id, filename, caption FROM photos WHERE id = ?');
const deletePhoto = db.prepare('DELETE FROM photos WHERE id = ?');

// --- Admin login ---
// Sessions live in memory, so restarting the server logs the admin out.
const sessions = new Map(); // token -> expiry time (ms)
const failedLogins = new Map(); // client ip -> { count, since }

function sha256(text) {
  return crypto.createHash('sha256').update(text).digest();
}

function passwordMatches(supplied) {
  const password = process.env.ADMIN_PASSWORD;
  return Boolean(password) && crypto.timingSafeEqual(sha256(supplied), sha256(password));
}

function getCookie(req, name) {
  for (const part of (req.headers.cookie || '').split(';')) {
    const [key, ...rest] = part.trim().split('=');
    if (key === name) return rest.join('=');
  }
  return null;
}

function isAdmin(req) {
  const token = getCookie(req, SESSION_COOKIE);
  const expires = token && sessions.get(token);
  if (!expires) return false;
  if (expires < Date.now()) {
    sessions.delete(token);
    return false;
  }
  return true;
}

function requireAdmin(req, res, next) {
  if (isAdmin(req)) return next();
  res.status(401).json({ error: 'Log eerst in op het tabblad Genereren.' });
}

// Behind cloudflared, the visitor's real IP is in the CF-Connecting-IP header.
function clientIp(req) {
  return req.get('cf-connecting-ip') || req.ip;
}

// --- App ---
const app = express();
app.use(express.json({ limit: '2mb' })); // room for one uploaded photo
app.use(['/images', '/photos', '/api/generate', '/api/images', '/api/context', '/api/photos', '/api/qr.svg'], requireAdmin);
app.use('/photos', express.static(PHOTOS_DIR));
app.use(express.static(PUBLIC_DIR));

// Old bookmarks of the separate generate page
app.get('/generate', (req, res) => res.redirect('/#generate'));

app.get('/api/session', (req, res) => {
  res.json({ admin: isAdmin(req) });
});

app.post('/api/login', (req, res) => {
  if (!process.env.ADMIN_PASSWORD) {
    return res.status(503).json({ error: 'ADMIN_PASSWORD is niet ingesteld in .env. Vul het in en herstart de server.' });
  }

  const ip = clientIp(req);
  const now = Date.now();
  let attempts = failedLogins.get(ip);
  if (attempts && now - attempts.since > LOGIN_LOCK_MS) {
    failedLogins.delete(ip);
    attempts = undefined;
  }
  if (attempts && attempts.count >= MAX_LOGIN_ATTEMPTS) {
    const minutes = Math.ceil((attempts.since + LOGIN_LOCK_MS - now) / 60000);
    return res.status(429).json({ error: `Te vaak een verkeerd wachtwoord. Probeer het over ${minutes} minuut/minuten opnieuw.` });
  }

  const supplied = typeof req.body?.password === 'string' ? req.body.password : '';
  if (!passwordMatches(supplied)) {
    failedLogins.set(ip, { count: (attempts?.count || 0) + 1, since: attempts?.since || now });
    return res.status(401).json({ error: 'Verkeerd wachtwoord.' });
  }

  failedLogins.delete(ip);
  const token = crypto.randomBytes(32).toString('hex');
  sessions.set(token, now + SESSION_MS);
  res.cookie(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: 'strict',
    secure: req.secure || req.get('x-forwarded-proto') === 'https',
    maxAge: SESSION_MS,
  });
  res.json({ admin: true });
});

app.post('/api/logout', (req, res) => {
  sessions.delete(getCookie(req, SESSION_COOKIE));
  res.clearCookie(SESSION_COOKIE);
  res.json({ admin: false });
});

// Words: anyone can add, only the admin can see or delete them.
app.get('/api/words', requireAdmin, (req, res) => {
  res.json(listWords.all());
});

app.post('/api/words', (req, res) => {
  const text = typeof req.body?.text === 'string' ? req.body.text.trim() : '';
  if (!text) {
    return res.status(400).json({ error: 'Het woord mag niet leeg zijn.' });
  }
  if (text.length > MAX_WORD_LENGTH) {
    return res.status(400).json({ error: `Een woord mag maximaal ${MAX_WORD_LENGTH} tekens lang zijn.` });
  }
  insertWord.run(text);
  res.status(201).json({ text });
});

app.delete('/api/words/:id', requireAdmin, (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    return res.status(400).json({ error: 'Ongeldig woord-id.' });
  }
  const { changes } = deleteWord.run(id);
  if (changes === 0) {
    return res.status(404).json({ error: 'Woord niet gevonden.' });
  }
  res.status(204).end();
});

// Context: background information that is added to every prompt (admin only).
app.get('/api/context', (req, res) => {
  res.json({ context: getSetting.get('context')?.value || '' });
});

app.put('/api/context', (req, res) => {
  const context = typeof req.body?.context === 'string' ? req.body.context.trim() : '';
  if (context.length > MAX_CONTEXT_LENGTH) {
    return res.status(400).json({ error: `De context mag maximaal ${MAX_CONTEXT_LENGTH} tekens lang zijn.` });
  }
  setSetting.run('context', context);
  res.json({ context });
});

// Reference photos (admin only). The browser resizes them to a JPEG under 512x512 before uploading.
function photoJson(photo) {
  return { id: photo.id, caption: photo.caption, url: `/photos/${photo.filename}` };
}

app.get('/api/photos', (req, res) => {
  res.json(listPhotos.all().map(photoJson));
});

app.post('/api/photos', (req, res) => {
  const match = /^data:image\/jpeg;base64,([A-Za-z0-9+/=]+)$/.exec(req.body?.image || '');
  if (!match) {
    return res.status(400).json({ error: 'Ongeldige foto. Kies een JPG- of PNG-bestand.' });
  }
  const data = Buffer.from(match[1], 'base64');
  if (data.length > MAX_PHOTO_BYTES) {
    return res.status(400).json({ error: 'De foto is te groot.' });
  }
  const caption = typeof req.body?.caption === 'string' ? req.body.caption.trim() : '';
  if (caption.length > MAX_CAPTION_LENGTH) {
    return res.status(400).json({ error: `De beschrijving mag maximaal ${MAX_CAPTION_LENGTH} tekens lang zijn.` });
  }
  if (countPhotos.get().n >= MAX_PHOTOS_STORED) {
    return res.status(400).json({ error: `Je kunt maximaal ${MAX_PHOTOS_STORED} foto's bewaren. Verwijder er eerst een.` });
  }
  const filename = `${Date.now()}-${crypto.randomBytes(4).toString('hex')}.jpg`;
  fs.writeFileSync(path.join(PHOTOS_DIR, filename), data);
  const { lastInsertRowid } = insertPhoto.run(filename, caption);
  res.status(201).json(photoJson(getPhoto.get(lastInsertRowid)));
});

app.delete('/api/photos/:id', (req, res) => {
  const photo = getPhoto.get(Number(req.params.id));
  if (!photo) {
    return res.status(404).json({ error: 'Foto niet gevonden.' });
  }
  deletePhoto.run(photo.id);
  fs.rmSync(path.join(PHOTOS_DIR, photo.filename), { force: true });
  res.status(204).end();
});

// QR code for the share link (admin only). The page passes its own address, so it is the public
// tunnel link when the admin opens the app through it.
app.get('/api/qr.svg', async (req, res) => {
  const url = typeof req.query.url === 'string' ? req.query.url : '';
  if (!/^https?:\/\/\S+$/.test(url) || url.length > 500) {
    return res.status(400).json({ error: 'Ongeldige link voor de QR-code.' });
  }
  const svg = await QRCode.toString(url, { type: 'svg', margin: 2, errorCorrectionLevel: 'M' });
  res.type('image/svg+xml').send(svg);
});

// Images
app.get('/api/images', (req, res) => {
  const files = fs
    .readdirSync(IMAGES_DIR)
    .filter((f) => f.endsWith('.jpg') || f.endsWith('.png'))
    .sort((a, b) => parseInt(b, 10) - parseInt(a, 10));
  res.json(files.map((f) => ({ filename: f, url: `/images/${f}` })));
});

app.delete('/api/images/:filename', (req, res) => {
  const { filename } = req.params;
  // Only plain generated names like 1792436799692.jpg, so nothing outside the images folder can be touched.
  if (!/^\d+\.(jpg|png)$/.test(filename)) {
    return res.status(400).json({ error: 'Ongeldige bestandsnaam.' });
  }
  const file = path.join(IMAGES_DIR, filename);
  if (!fs.existsSync(file)) {
    return res.status(404).json({ error: 'Afbeelding niet gevonden.' });
  }
  fs.rmSync(file);
  res.status(204).end();
});

function missingCredentials() {
  return ['CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN'].filter((name) => !process.env[name]);
}

// Turns a failed Cloudflare response into a readable message.
function cloudflareErrorMessage(status, body) {
  const errors = Array.isArray(body?.errors) ? body.errors : [];
  const text = errors.map((e) => (e.code ? `${e.message} (code ${e.code})` : e.message)).join('; ');
  const dailyLimit =
    status === 429 ||
    errors.some((e) => e.code === 4006 || /daily free allocation|neurons/i.test(e.message || ''));
  if (dailyLimit) {
    return `Dagelijkse gratis limiet van Workers AI bereikt. Probeer het morgen opnieuw (de limiet wordt om 00:00 UTC gereset). Melding van Cloudflare: ${text || `HTTP ${status}`}`;
  }
  if (status === 401 || status === 403) {
    return `Cloudflare heeft de inloggegevens geweigerd (HTTP ${status}). Controleer CLOUDFLARE_ACCOUNT_ID en CLOUDFLARE_API_TOKEN in .env. Melding van Cloudflare: ${text || 'geen details'}`;
  }
  return `Fout van de Cloudflare API (HTTP ${status}): ${text || 'geen details'}`;
}

// The prompt stays in English (the image models follow English best); context and captions are passed as written.
function buildPrompt(words, context, photos) {
  let prompt = `A detailed, colorful image combining: ${words.join(', ')}.`;
  if (context) {
    prompt += `\n\nBackground information about these words and the situation:\n${context}`;
  }
  if (photos.length > 0) {
    const refs = photos.map((p, i) => `image ${i}${p.caption ? ` shows ${p.caption}` : ''}`).join('; ');
    prompt += `\n\nUse the reference images for how the people, animals, places and objects look (${refs}).`;
  }
  return prompt;
}

app.post('/api/generate', async (req, res) => {
  const missing = missingCredentials();
  if (missing.length > 0) {
    return res.status(500).json({
      error: `Cloudflare-gegevens ontbreken: ${missing.join(', ')}. Vul ze in het .env-bestand in en herstart de server.`,
    });
  }

  const ids = Array.isArray(req.body?.ids) ? req.body.ids.map(Number) : [];
  if (ids.length === 0) {
    return res.status(400).json({ error: 'Selecteer minstens één woord.' });
  }
  if (ids.length > MAX_WORDS_PER_PROMPT) {
    return res.status(400).json({ error: `Selecteer maximaal ${MAX_WORDS_PER_PROMPT} woorden.` });
  }

  const words = ids.map((id) => getWord.get(id)).filter(Boolean);
  if (words.length !== ids.length) {
    return res.status(400).json({ error: 'Een of meer geselecteerde woorden bestaan niet meer. Herlaad de pagina.' });
  }

  const photoIds = Array.isArray(req.body?.photoIds) ? req.body.photoIds.map(Number) : [];
  if (photoIds.length > MAX_PHOTOS_PER_PROMPT) {
    return res.status(400).json({ error: `Selecteer maximaal ${MAX_PHOTOS_PER_PROMPT} foto's.` });
  }
  const photos = photoIds.map((id) => getPhoto.get(id)).filter(Boolean);
  if (photos.length !== photoIds.length) {
    return res.status(400).json({ error: "Een of meer geselecteerde foto's bestaan niet meer. Herlaad de pagina." });
  }

  const prompt = buildPrompt(
    words.map((w) => w.text),
    getSetting.get('context')?.value || '',
    photos
  );

  // Text only: the fast, cheap model with a JSON body. With photos: the FLUX.2 model, which needs multipart form data.
  const model = photos.length > 0 ? CF_PHOTO_MODEL : CF_MODEL;
  const headers = { Authorization: `Bearer ${process.env.CLOUDFLARE_API_TOKEN}` };
  let requestBody;
  if (photos.length === 0) {
    headers['Content-Type'] = 'application/json';
    requestBody = JSON.stringify({ prompt, steps: 4 });
  } else {
    requestBody = new FormData();
    requestBody.append('prompt', prompt);
    requestBody.append('width', '1024');
    requestBody.append('height', '1024');
    photos.forEach((photo, i) => {
      const data = fs.readFileSync(path.join(PHOTOS_DIR, photo.filename));
      requestBody.append(`input_image_${i}`, new Blob([data], { type: 'image/jpeg' }), photo.filename);
    });
  }
  const url = `https://api.cloudflare.com/client/v4/accounts/${process.env.CLOUDFLARE_ACCOUNT_ID}/ai/run/${model}`;

  let response;
  let body;
  try {
    response = await fetch(url, { method: 'POST', headers, body: requestBody });
    body = await response.json().catch(() => null);
  } catch (err) {
    console.error('Could not reach Cloudflare:', err);
    return res.status(502).json({ error: `Kan de Cloudflare API niet bereiken: ${err.message}` });
  }

  if (!response.ok || body?.success === false) {
    const message = cloudflareErrorMessage(response.status, body);
    console.error(message);
    return res.status(502).json({ error: message });
  }

  const b64 = body?.result?.image;
  if (!b64) {
    return res.status(502).json({ error: 'Fout van de Cloudflare API: het antwoord bevatte geen afbeelding.' });
  }

  const image = Buffer.from(b64, 'base64');
  const isPng = image.subarray(0, 4).toString('hex') === '89504e47';
  const filename = `${Date.now()}.${isPng ? 'png' : 'jpg'}`;
  fs.writeFileSync(path.join(IMAGES_DIR, filename), image);
  res.json({ prompt, model, filename, url: `/images/${filename}` });
});

app.listen(PORT, (err) => {
  if (err) {
    console.error(`Could not start the server on port ${PORT}: ${err.message}`);
    process.exit(1);
  }
  console.log(`Server running at http://localhost:${PORT}`);
  const missing = missingCredentials();
  if (missing.length > 0) {
    console.warn(`Warning: ${missing.join(', ')} not set. Image generation will fail until you add them to .env.`);
  }
  if (!process.env.ADMIN_PASSWORD) {
    console.warn('Warning: ADMIN_PASSWORD not set. The Generate tab is locked until you add it to .env.');
  }
});
