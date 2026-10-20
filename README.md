# Image generator

## What is this?

A small web app that turns words from other people into images made by AI.

1. You share one link. Anyone who opens it can add a word or short phrase, like "sunset", "dragon" or
   "a red bicycle". They cannot see what others have added.
2. You, the admin, log in with a password. You see all collected words, pick the ones you want, and click
   **Generate image**.
3. The app combines the selected words into one prompt ("A detailed, colorful image combining: sunset, dragon, …")
   and sends it to [Cloudflare Workers AI](https://developers.cloudflare.com/workers-ai/), which draws the image
   with the FLUX.1 schnell model. The image appears on the page and is added to your gallery.

The app is a single page with two tabs:

| Tab          | Who can use it          | What it does                                                          |
|--------------|-------------------------|-----------------------------------------------------------------------|
| **Words**    | Everyone                | Add a word or short phrase (max 50 characters).                       |
| **Generate** | Only you (password)     | See and delete words, select up to 20, add context and reference photos, generate an image, view the gallery. |

How it is built: a Node.js server (Express) stores the words in a small SQLite database file (`words.db`) and saves
the generated images as `.jpg` files in `public/images/`. The web page is plain HTML, CSS and JavaScript. Your
Cloudflare credentials and admin password stay on the server and are never sent to the browser.

### Context and photos

On the Generate tab you can steer the image further:

- **Context** has two boxes:
  - **Altijd meesturen** (always): sent with every image – the style, who must always be in it, what is not allowed
    (*"A warm wedding illustration. Always include Laureanne and Jerrel. No text in the image."*).
  - **Woordenlijst** (glossary): one line per name, `Name: description`, e.g. `Whisky: a small brown dog`.
    A line is only sent when its name appears (as a whole word) in the selected words or in the description of a
    ticked photo. Several names per line are allowed: `Paris, Dalwhinnie, paarden: two brown horses`.
    This keeps the image focused: characters that are not asked for are not described, so they are not drawn.
  - **Prompt bekijken** shows the exact prompt for the current selection without generating an image.
  The AI understands English best, but Dutch works too.
- **Photos**: upload photos of people, animals or places and tick up to 4 to use. You can give each photo a short
  description (*"Bram, our dog"*) so the AI knows who or what it shows. The browser shrinks photos to under
  512×512 pixels before uploading, as the model requires. Photos are stored in `uploads/` and only you can see them.

### Choosing the AI service

On the Generate tab you choose per image between **Cloudflare** (free) and **OpenAI** (best quality, paid):

| Service | Photos selected? | Model | Cost |
|---------|------------------|-------|------|
| Cloudflare | No  | FLUX.1 [schnell] (`@cf/black-forest-labs/flux-1-schnell`) – fast, text only | Free, 150+ per day |
| Cloudflare | Yes | FLUX.2 [klein] 9B (`@cf/black-forest-labs/flux-2-klein-9b`) – uses reference photos | Free, about 5 per day |
| OpenAI | Either | `gpt-image-2.5-sunburst` (or the model set in `OPENAI_IMAGE_MODEL`) – follows long prompts well, keeps people recognizable | Paid per image; higher quality costs more |

- OpenAI is optional: without `OPENAI_API_KEY` in `.env`, only Cloudflare works.
- For OpenAI you also pick a **quality** (low / medium / high). Higher quality looks better but costs more and takes longer.
- OpenAI can take up to a minute. If it takes longer than the tunnel allows (about 100 seconds), the page says so;
  the image is still finished on the server and appears in the gallery shortly after.
- New photo uploads are also stored in a larger version (up to 1024 px) that OpenAI uses. Cloudflare uses the small one.
- Your choice of service and quality is remembered in your browser.

Only use photos of people who are okay with it.

## What you need

- **Node.js 20 or newer**: download the LTS version from https://nodejs.org and install it.
  Check it worked by opening a **new** terminal and running `node --version`.
- **A free Cloudflare account** (https://dash.cloudflare.com/sign-up) for the image generation.
- **Optional: an OpenAI account with an API key and credit** (https://platform.openai.com) to also use OpenAI.
- **Optional:** `cloudflared`, only if people outside your own network should be able to open the app
  (see [Share it over the internet](#share-it-over-the-internet)).

## Set up (once)

All commands below are typed in a terminal (on Windows: PowerShell, or the terminal in VS Code).

**1. Get the code and go to the project folder.** Clone the repository (or download it as a ZIP from GitHub and unzip it):

```powershell
git clone https://github.com/TychoJansen/image-generator.git
cd image-generator
```

If you already have the folder, `cd` into it instead. Put the path in quotes if it contains spaces,
for example `cd "C:\My Projects\image-generator"`.

**2. Install the dependencies.** This creates the `node_modules` folder:

```powershell
npm install
```

**3. Create the `.env` file** (skip this if `.env` already exists):

```powershell
Copy-Item .env.example .env      # Windows PowerShell
cp .env.example .env             # macOS / Linux
```

**4. Fill in `.env`.** Open it in an editor and fill in the three values:

```
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_API_TOKEN=your-api-token
ADMIN_PASSWORD=choose-a-long-password
```

- **CLOUDFLARE_ACCOUNT_ID**: in the Cloudflare dashboard, open *Workers & Pages*; the Account ID is in the right sidebar.
- **CLOUDFLARE_API_TOKEN**: click your profile icon → *My Profile* → *API Tokens* → *Create Token* →
  use the **Workers AI** template → *Create Token*, and copy the token.
- **ADMIN_PASSWORD**: a password you make up, for the Generate tab. Use a long one (16+ characters).
  If it is empty, the Generate tab stays locked, even for you.
- **OPENAI_API_KEY** (optional): on https://platform.openai.com → *API keys* → *Create new secret key*.
  You need credit on your OpenAI account. Some image models require a one-time organization verification there.
- **OPENAI_IMAGE_MODEL** (optional): defaults to `gpt-image-2.5-sunburst`, OpenAI's newest image model. If your account
  has no access to it, use e.g. `gpt-image-2` or `gpt-image-1.5`. With `gpt-image-1` / `gpt-image-1.5` the app also asks
  OpenAI to keep faces from the reference photos as close as possible (`input_fidelity: high`).

Save the file. `.env` is listed in `.gitignore`, so it is never committed to git.

## Run the app

**1. Start the server** in the project folder:

```powershell
npm start
```

You should see:

```
Server running at http://localhost:3000
```

The terminal stays busy (no new prompt) while the app is running. That is correct: keep this terminal open.

**2. Open the app** in your browser: http://localhost:3000

- The **Words** tab opens first. Add a few words.
- Click the **Generate** tab, log in with your `ADMIN_PASSWORD`, select words and click **Generate image**.
  You can go straight to this tab with http://localhost:3000/#generate.

**3. Stop the server** by pressing **Ctrl+C** in that terminal.

After changing `.env`, stop the server and run `npm start` again so it picks up the new values.

## Share it over the internet

By default only you (and maybe people on the same Wi-Fi) can open the app. To give others a link that works
from anywhere, use a free Cloudflare tunnel.

**1. Install cloudflared** (once). On Windows:

```powershell
winget install Cloudflare.cloudflared
```

Then close and reopen VS Code / your terminal so it can find the new command.

**2. Start the tunnel.** Keep the app running in its terminal, open a **second** terminal and run:

```powershell
cloudflared tunnel --url http://localhost:3000
```

**3. Share the link.** In the output, find the box with an address like:

```
https://some-random-words.trycloudflare.com
```

Send that link to people. They land on the Words tab. You use the same link and click **Generate**.

**Or use the QR code.** Open the app through the public link, open the **Share** tab (log in first):
it shows a QR code that opens the Words tab. Click **Groot tonen** to show it full-size on a screen or projector,
or **Downloaden** to save it (SVG) for printing. The QR code always points to the address you opened the app on,
so open it through the public link, not `localhost`. A new tunnel link means a new QR code.

Good to know:

- The link only works while your computer is on and **both** terminals (`npm start` and `cloudflared`) are running.
- Every time you restart `cloudflared` you get a **new** link; the old one stops working.
  Restarting only the app (`npm start`) keeps the same link.
- To stop sharing, press **Ctrl+C** in the `cloudflared` terminal.
- A red `ERR Failed to initialize DNS local resolver` line in the output is harmless.
- Running a public tunnel from a work laptop may be against company policy. Check first.

## Limits and security

- Words must not be empty and can be at most 50 characters. You can select at most 20 words per image.
- After 5 wrong passwords, that visitor is locked out of the Generate tab for 15 minutes.
- A login lasts 12 hours and ends when the server restarts.
- Context: max 1,000 characters. Photos: max 20 stored, max 4 per image, description max 100 characters.
- The Workers AI free tier has a daily limit (10,000 neurons, resets at 00:00 UTC). When it is reached,
  the app says so; try again the next day.
- There is no limit on how many words visitors can add. Delete unwanted ones on the Generate tab.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `npm : The term 'npm' is not recognized` | Node.js is not installed, or the terminal was opened before installing it. Close VS Code completely and open it again. |
| The prompt comes back right after `Server running …` | Another program is using port 3000; the next line says so. Close the other server, or add `PORT=3001` to `.env` and open http://localhost:3001. |
| "Missing Cloudflare credentials" | `CLOUDFLARE_ACCOUNT_ID` or `CLOUDFLARE_API_TOKEN` is empty in `.env`. Fill it in, save, and restart the server. |
| "Cloudflare rejected the credentials" | The account ID or token is wrong, or the token lacks the Workers AI permission. Create a new token with the **Workers AI** template. |
| "OpenAI heeft de API-sleutel geweigerd" | `OPENAI_API_KEY` in `.env` is wrong. Create a new key on platform.openai.com and restart the server. |
| "OpenAI-tegoed of budgetlimiet is bereikt" | Add credit or raise your budget limit on platform.openai.com. |
| "geen toegang tot gpt-image-…" | Verify your organization on platform.openai.com, or set `OPENAI_IMAGE_MODEL` to a model you can use. |
| "Daily free Workers AI limit reached" | You used up today's free generations. Try again after 00:00 UTC. |
| "ADMIN_PASSWORD is not set" | Add `ADMIN_PASSWORD=…` to `.env` and restart the server. |
| "Too many wrong passwords" | Wait 15 minutes, or restart the server. |

## Project files

| File / folder | What it is |
|---------------|------------|
| `server.js` | The server: API routes, login, database and Cloudflare calls |
| `public/index.html`, `public/app.js`, `public/style.css` | The web page with both tabs |
| `public/images/` | Generated images (not committed to git) |
| `uploads/` | Uploaded reference photos, admin only (not committed to git) |
| `words.db` | The SQLite database with the words, context and photo list, created on first start (not committed) |
| `.env` / `.env.example` | Your settings and secrets / an empty template |

## API

For reference; the web page uses these routes. "Admin" routes need you to be logged in.

| Method | Route             | Body / notes                                     |
|--------|-------------------|--------------------------------------------------|
| POST   | `/api/words`      | `{ "text": "..." }` – non-empty, max 50 chars    |
| GET    | `/api/words`      | List words (admin)                               |
| DELETE | `/api/words/:id`  | Delete a word (admin)                            |
| POST   | `/api/prompt`     | Same body as `/api/generate`; returns the prompt without generating (admin) |
| POST   | `/api/generate`   | `{ "ids": [1, 2], "photoIds": [3], "provider": "cloudflare" or "openai", "quality": "low"/"medium"/"high" }` – 1–20 words, 0–4 photos (admin) |
| GET    | `/api/providers`  | Which services are set up, and the OpenAI model (admin) |
| DELETE | `/api/images/:filename` | Delete a generated image (admin) |
| GET/PUT | `/api/context`   | Read / save the context `{ "context": "..." }` (admin) |
| GET/POST | `/api/photos`   | List / upload a photo `{ "image": "data:image/jpeg;base64,...", "caption": "..." }` (admin) |
| DELETE | `/api/photos/:id` | Delete a photo (admin)                           |
| GET    | `/api/images`     | List generated images, newest first (admin)      |
| POST   | `/api/login`      | `{ "password": "..." }` – logs in (sets a cookie) |
| POST   | `/api/logout`     | Logs out                                         |
| GET    | `/api/session`    | `{ "admin": true/false }`                        |
