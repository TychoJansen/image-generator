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
// OpenAI is optional; the model can be changed in .env (e.g. to a newer gpt-image model your account can use).
const OPENAI_MODEL = process.env.OPENAI_IMAGE_MODEL || 'gpt-image-2.5-sunburst';
// Models that accept input_fidelity=high (keeps faces from reference photos closer); newer models must omit it.
const OPENAI_FIDELITY_MODELS = ['gpt-image-1', 'gpt-image-1.5'];
const OPENAI_QUALITIES = ['low', 'medium', 'high'];
const MAX_WORD_LENGTH = 50;
const MAX_WORDS_PER_PROMPT = 20;
const MAX_CONTEXT_LENGTH = 1000;
const MAX_GLOSSARY_LENGTH = 3000;
const MAX_MERGES_LENGTH = 3000;
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
app.use(['/images', '/photos', '/api/generate', '/api/images', '/api/context', '/api/photos', '/api/qr.svg', '/api/providers', '/api/prompt', '/api/merges'], requireAdmin);
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

// Context (admin only): "context" is always added to the prompt; "glossary" lines are only added
// when their name appears in the selected words or photo descriptions.
app.get('/api/context', (req, res) => {
  res.json({
    context: getSetting.get('context')?.value || '',
    glossary: getSetting.get('glossary')?.value || '',
  });
});

app.put('/api/context', (req, res) => {
  const context = typeof req.body?.context === 'string' ? req.body.context.trim() : '';
  const glossary = typeof req.body?.glossary === 'string' ? req.body.glossary.trim() : '';
  if (context.length > MAX_CONTEXT_LENGTH) {
    return res.status(400).json({ error: `"Altijd meesturen" mag maximaal ${MAX_CONTEXT_LENGTH} tekens lang zijn.` });
  }
  if (glossary.length > MAX_GLOSSARY_LENGTH) {
    return res.status(400).json({ error: `De woordenlijst mag maximaal ${MAX_GLOSSARY_LENGTH} tekens lang zijn.` });
  }
  setSetting.run('context', context);
  setSetting.run('glossary', glossary);
  res.json({ context, glossary });
});

function largeName(filename) {
  return filename.replace(/\.jpg$/, '-large.jpg');
}

// Word cloud variants (admin only): lines like "paarden = paard, paardjes" that count as one word in the cloud.
app.get('/api/merges', (req, res) => {
  res.json({ merges: getSetting.get('merges')?.value || '' });
});

app.put('/api/merges', (req, res) => {
  const merges = typeof req.body?.merges === 'string' ? req.body.merges.trim() : '';
  if (merges.length > MAX_MERGES_LENGTH) {
    return res.status(400).json({ error: `De lijst mag maximaal ${MAX_MERGES_LENGTH} tekens lang zijn.` });
  }
  setSetting.run('merges', merges);
  res.json({ merges });
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
  // Optional larger copy (up to 1024px) that OpenAI uses; Cloudflare needs the small one.
  let large = null;
  if (req.body?.large) {
    const largeMatch = /^data:image\/jpeg;base64,([A-Za-z0-9+/=]+)$/.exec(req.body.large);
    large = largeMatch && Buffer.from(largeMatch[1], 'base64');
    if (!large || large.length > MAX_PHOTO_BYTES) {
      return res.status(400).json({ error: 'De grote versie van de foto is ongeldig of te groot.' });
    }
  }
  const filename = `${Date.now()}-${crypto.randomBytes(4).toString('hex')}.jpg`;
  fs.writeFileSync(path.join(PHOTOS_DIR, filename), data);
  if (large) fs.writeFileSync(path.join(PHOTOS_DIR, largeName(filename)), large);
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
  fs.rmSync(path.join(PHOTOS_DIR, largeName(photo.filename)), { force: true });
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

// Which image services are set up in .env (shown on the Generate tab).
app.get('/api/providers', (req, res) => {
  res.json({
    cloudflare: missingCredentials().length === 0,
    openai: Boolean(process.env.OPENAI_API_KEY),
    openaiModel: OPENAI_MODEL,
  });
});

// An error with a message that can be shown to the admin as is.
class GenerationError extends Error {}

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

// Turns a failed OpenAI response into a readable message.
function openaiErrorMessage(status, body) {
  const error = body?.error || {};
  const text = error.message || 'geen details';
  if (status === 401) {
    return `OpenAI heeft de API-sleutel geweigerd. Controleer OPENAI_API_KEY in .env. Melding van OpenAI: ${text}`;
  }
  if (error.code === 'insufficient_quota' || error.code === 'billing_hard_limit_reached') {
    return `Je OpenAI-tegoed of budgetlimiet is bereikt. Vul je tegoed aan of verhoog je limiet op platform.openai.com. Melding van OpenAI: ${text}`;
  }
  if (status === 429) {
    return `Te veel verzoeken naar OpenAI in korte tijd. Wacht even en probeer het opnieuw. Melding van OpenAI: ${text}`;
  }
  if (error.code === 'moderation_blocked' || /safety|moderation/i.test(text)) {
    return `OpenAI heeft dit verzoek geweigerd vanwege het veiligheidsbeleid. Pas de woorden, context of foto's aan. Melding van OpenAI: ${text}`;
  }
  if (status === 403 || /verif/i.test(text)) {
    return `Je OpenAI-account heeft (nog) geen toegang tot ${OPENAI_MODEL}. Mogelijk moet je organisatie eerst geverifieerd worden op platform.openai.com. Melding van OpenAI: ${text}`;
  }
  return `Fout van de OpenAI API (HTTP ${status}): ${text}`;
}

// Glossary lines look like "Whisky: a small brown dog" or "Paris, Dalwhinnie: two brown horses".
// Everything before the first colon are names (separated by commas, "/", "and" or "en").
function parseGlossary(text) {
  return text
    .split('\n')
    .map((line) => line.trim().replace(/^[-*•]\s*/, ''))
    .map((line) => {
      const colon = line.indexOf(':');
      if (colon < 1) return null;
      const names = line
        .slice(0, colon)
        .split(/,|\/|\s+(?:and|en|&)\s+/i)
        .map((name) => name.trim().toLowerCase())
        .filter(Boolean);
      return { names, line };
    })
    .filter(Boolean);
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Keeps only the glossary lines whose name occurs (as a whole word) in the given texts.
function matchGlossary(glossaryText, texts) {
  const haystack = texts.join(' | ').toLowerCase();
  return parseGlossary(glossaryText).filter(({ names }) =>
    names.some((name) => new RegExp(`(^|[^\\p{L}\\p{N}])${escapeRegExp(name)}($|[^\\p{L}\\p{N}])`, 'u').test(haystack))
  );
}

// The prompt stays in English (the image models follow English best); context and captions are passed as written.
// FLUX numbers reference images from 0, OpenAI from 1.
function buildPrompt(words, photos, firstImageNumber) {
  const always = getSetting.get('context')?.value || '';
  const glossary = matchGlossary(getSetting.get('glossary')?.value || '', [...words, ...photos.map((p) => p.caption)]);

  const parts = [`Create one detailed, colorful illustration based on these words: ${words.join(', ')}.`];
  if (always) {
    parts.push(`Always follow these instructions:\n${always}`);
  }
  if (glossary.length > 0) {
    parts.push(`What some of these words mean:\n${glossary.map((g) => `- ${g.line}`).join('\n')}`);
  }
  if (photos.length > 0) {
    const refs = photos
      .map((p, i) => `image ${i + firstImageNumber}${p.caption ? ` shows ${p.caption}` : ''}`)
      .join('; ');
    parts.push(
      `Reference images: ${refs}. Use them only for how these specific people, animals or places look ` +
        '(faces, hair, fur, build). Do not copy anything else from them: no extra people, animals, objects, ' +
        'poses or backgrounds.'
    );
  }
  parts.push('Only show the people and animals that are mentioned above. Do not add any other people or animals.');
  return parts.join('\n\n');
}

async function postJson(url, init, service) {
  let response;
  try {
    response = await fetch(url, { method: 'POST', ...init });
  } catch (err) {
    console.error(`Could not reach ${service}:`, err);
    throw new GenerationError(`Kan de ${service} API niet bereiken: ${err.message}`);
  }
  const body = await response.json().catch(() => null);
  return { response, body };
}

// Cloudflare: FLUX.1 schnell (JSON) for text only, FLUX.2 klein (multipart, small photos) with photos.
async function generateWithCloudflare(prompt, photos) {
  const missing = missingCredentials();
  if (missing.length > 0) {
    throw new GenerationError(
      `Cloudflare-gegevens ontbreken: ${missing.join(', ')}. Vul ze in het .env-bestand in en herstart de server.`
    );
  }
  const model = photos.length > 0 ? CF_PHOTO_MODEL : CF_MODEL;
  const headers = { Authorization: `Bearer ${process.env.CLOUDFLARE_API_TOKEN}` };
  let body;
  if (photos.length === 0) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify({ prompt, steps: 4 });
  } else {
    body = new FormData();
    body.append('prompt', prompt);
    body.append('width', '1024');
    body.append('height', '1024');
    photos.forEach((photo, i) => {
      const data = fs.readFileSync(path.join(PHOTOS_DIR, photo.filename));
      body.append(`input_image_${i}`, new Blob([data], { type: 'image/jpeg' }), photo.filename);
    });
  }
  const url = `https://api.cloudflare.com/client/v4/accounts/${process.env.CLOUDFLARE_ACCOUNT_ID}/ai/run/${model}`;
  const { response, body: result } = await postJson(url, { headers, body }, 'Cloudflare');
  if (!response.ok || result?.success === false) {
    throw new GenerationError(cloudflareErrorMessage(response.status, result));
  }
  if (!result?.result?.image) {
    throw new GenerationError('Fout van de Cloudflare API: het antwoord bevatte geen afbeelding.');
  }
  return { model, b64: result.result.image };
}

// OpenAI: /images/generations for text only, /images/edits with the (large) photos as reference images.
async function generateWithOpenAI(prompt, photos, quality) {
  if (!process.env.OPENAI_API_KEY) {
    throw new GenerationError('OPENAI_API_KEY ontbreekt. Vul hem in het .env-bestand in en herstart de server.');
  }
  const headers = { Authorization: `Bearer ${process.env.OPENAI_API_KEY}` };
  const params = { model: OPENAI_MODEL, prompt, size: '1024x1024', quality, output_format: 'jpeg', n: 1 };
  let url;
  let body;
  if (photos.length === 0) {
    url = 'https://api.openai.com/v1/images/generations';
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(params);
  } else {
    url = 'https://api.openai.com/v1/images/edits';
    if (OPENAI_FIDELITY_MODELS.includes(OPENAI_MODEL)) params.input_fidelity = 'high';
    body = new FormData();
    for (const [key, value] of Object.entries(params)) body.append(key, String(value));
    for (const photo of photos) {
      const large = path.join(PHOTOS_DIR, largeName(photo.filename));
      const file = fs.existsSync(large) ? large : path.join(PHOTOS_DIR, photo.filename);
      body.append('image[]', new Blob([fs.readFileSync(file)], { type: 'image/jpeg' }), photo.filename);
    }
  }
  const { response, body: result } = await postJson(url, { headers, body }, 'OpenAI');
  if (!response.ok) {
    throw new GenerationError(openaiErrorMessage(response.status, result));
  }
  const b64 = result?.data?.[0]?.b64_json;
  if (!b64) {
    throw new GenerationError('Fout van de OpenAI API: het antwoord bevatte geen afbeelding.');
  }
  return { model: OPENAI_MODEL, b64 };
}

// Validates the selected words and photos. Returns { error } or { provider, quality, words, photos, prompt }.
function readSelection(body) {
  const provider = body?.provider === 'openai' ? 'openai' : 'cloudflare';
  const quality = OPENAI_QUALITIES.includes(body?.quality) ? body.quality : 'medium';

  const ids = Array.isArray(body?.ids) ? body.ids.map(Number) : [];
  if (ids.length === 0) return { error: 'Selecteer minstens één woord.' };
  if (ids.length > MAX_WORDS_PER_PROMPT) return { error: `Selecteer maximaal ${MAX_WORDS_PER_PROMPT} woorden.` };
  const words = ids.map((id) => getWord.get(id)).filter(Boolean);
  if (words.length !== ids.length) {
    return { error: 'Een of meer geselecteerde woorden bestaan niet meer. Herlaad de pagina.' };
  }

  const photoIds = Array.isArray(body?.photoIds) ? body.photoIds.map(Number) : [];
  if (photoIds.length > MAX_PHOTOS_PER_PROMPT) return { error: `Selecteer maximaal ${MAX_PHOTOS_PER_PROMPT} foto's.` };
  const photos = photoIds.map((id) => getPhoto.get(id)).filter(Boolean);
  if (photos.length !== photoIds.length) {
    return { error: "Een of meer geselecteerde foto's bestaan niet meer. Herlaad de pagina." };
  }

  const prompt = buildPrompt(
    words.map((w) => w.text),
    photos,
    provider === 'openai' ? 1 : 0
  );
  return { provider, quality, photos, prompt };
}

// Shows the prompt that would be sent, without generating (and paying for) an image.
app.post('/api/prompt', (req, res) => {
  const selection = readSelection(req.body);
  if (selection.error) return res.status(400).json({ error: selection.error });
  res.json({ prompt: selection.prompt });
});

app.post('/api/generate', async (req, res) => {
  const selection = readSelection(req.body);
  if (selection.error) return res.status(400).json({ error: selection.error });
  const { provider, quality, photos, prompt } = selection;

  let result;
  try {
    result =
      provider === 'openai'
        ? await generateWithOpenAI(prompt, photos, quality)
        : await generateWithCloudflare(prompt, photos);
  } catch (err) {
    if (!(err instanceof GenerationError)) throw err;
    console.error(err.message);
    return res.status(502).json({ error: err.message });
  }

  const image = Buffer.from(result.b64, 'base64');
  const isPng = image.subarray(0, 4).toString('hex') === '89504e47';
  const filename = `${Date.now()}.${isPng ? 'png' : 'jpg'}`;
  fs.writeFileSync(path.join(IMAGES_DIR, filename), image);
  res.json({ prompt, model: result.model, filename, url: `/images/${filename}` });
});

app.listen(PORT, (err) => {
  if (err) {
    console.error(`Could not start the server on port ${PORT}: ${err.message}`);
    process.exit(1);
  }
  console.log(`Server running at http://localhost:${PORT}`);
  const missing = missingCredentials();
  if (missing.length > 0) {
    console.warn(`Warning: ${missing.join(', ')} not set. Cloudflare image generation will fail until you add them to .env.`);
  }
  if (process.env.OPENAI_API_KEY) {
    console.log(`OpenAI image generation enabled (model: ${OPENAI_MODEL}).`);
  }
  if (!process.env.ADMIN_PASSWORD) {
    console.warn('Warning: ADMIN_PASSWORD not set. The Generate tab is locked until you add it to .env.');
  }
});
