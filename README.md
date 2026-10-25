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

The app is a single page with four tabs:

| Tab          | Who can use it          | What it does                                                          |
|--------------|-------------------------|-----------------------------------------------------------------------|
| **Words**    | Everyone                | Add a word or short phrase (max 50 characters).                       |
| **Woordweb** | Only you (password)     | A live word cloud of everything participants submitted; more often = bigger. Full-screen mode for a TV or projector, with a QR code to join. Click words (or **Top 10 kiezen**) and **Maak afbeelding** to tick them on the Generate tab. **Varianten samenvoegen** (`paarden = paard, horses`) counts variants as one word in the cloud. |
| **Generate** | Only you (password)     | See and delete words, select up to 20, add context and reference photos, generate an image, view the gallery. |
| **Share**    | Only you (password)     | QR code and link that open the Words tab. |

How it is built: a Python server (FastAPI) keeps all data in one folder, `data/` (configurable with `DATA_DIR`): the
SQLite database `words.db`, the generated images in `images/` and the reference photos in `photos/`. The web page is plain HTML, CSS and JavaScript (browsers only
run JavaScript, so that part is not Python). Your Cloudflare and OpenAI keys and the admin password stay on the server
and are never sent to the browser.

### Context and photos

On the Generate tab you can steer the image further:

- **Context** has two boxes:
  - **Altijd meesturen** (always): sent with every image – the style, who must always be in it, what is not allowed
    (*"A warm wedding illustration. Always include person x. No text in the image."*).
  - **Woordenlijst** (glossary): one line per name, `Name: description`, e.g. `Whisky: a small brown dog`.
    A line is only sent when its name appears (as a whole word) in the selected words or in the description of a
    ticked photo. Several names per line are allowed: `Paris, Dalwhinnie, paarden: two brown horses`.
    This keeps the image focused: characters that are not asked for are not described, so they are not drawn.
  - **Prompt bekijken** shows the exact prompt for the current selection without generating an image.
  The AI understands English best, but Dutch works too.
  - **`context.txt`**: put your "Altijd meesturen" text in a file called `context.txt` in the project folder. At
    every start, the app loads it into the box **when the file is new or changed** since the last start. Edits you
    make in the app are kept until you change the file again. Use `CONTEXT_FILE` in `.env` for another file name, or
    leave it empty to switch this off. `context.txt` is in `.gitignore`, so your personal details stay off GitHub.
  - **`woordenlijst.txt`**: the same for the **Woordenlijst** box: one line per name, loaded at every start when the
    file is new or changed. Use `GLOSSARY_FILE` in `.env` for another file name, or leave it empty to switch this off.
- **Photos**: upload photos of people, animals or places and tick up to 4 to use. You can give each photo a short
  description (*"Bram, our dog"*) so the AI knows who or what it shows. The browser shrinks photos to under
  512×512 pixels before uploading, as the model requires. Photos are stored in `data/photos/` and only you can see them.
- **`reference-photos/` folder**: put photos you always want to use in this folder (JPG, PNG or WebP). At every start
  the app adds them to **Foto's**, **ticked by default**, so they are sent with every image unless you untick them
  (at most 4 per image). The **file name is the description** (`personx.jpg` → "personx").
  Changed photos are replaced and removed ones disappear on the next start. These photos get an "Uit map" label and
  cannot be deleted in the app: remove them from the folder instead. The photos stay off GitHub (`.gitignore`).
  Note: ticked photos mean every image uses the photo model (Cloudflare: about 5 free images per day).

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
- **Tijdmachine**: type a year under the Generate button and click **Genereer in dit jaar** (or press Enter) to make
  one image of the same scene in that year: same people and animals, but clothing, buildings, vehicles and style of
  that time. Use a minus sign for BC (`-10000` = Stone Age); allowed years are -10000 to 10000.
  Tick **Leeftijd verandert mee** to also make everyone older or younger by the years between now and that year
  (e.g. 2080: everyone about 54 years older; anyone not yet born in that year becomes a baby). The model uses the
  ages from your context, so mention them there (e.g. "Laureanne, 30").

Only use photos of people who are okay with it.

## What you need

- **Python 3.11 or newer**: https://www.python.org/downloads/ (or via pyenv). Check it with `python --version`.
- **Poetry** to install the dependencies: https://python-poetry.org/docs/#installation. Check it with `poetry --version`.
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

**2. Install the dependencies.** Poetry creates a virtual environment (`.venv`) and installs everything in it:

```powershell
poetry install
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

## Quick start: app + public link in one go (Windows)

Once everything is set up (see [Set up](#set-up-once) above and `cloudflared` below), **double-click `start.cmd`** in the project folder, or run `.\start.ps1` in
PowerShell. It:

1. starts the app,
2. starts a Cloudflare tunnel (needs `cloudflared`, see [Share it over the internet](#share-it-over-the-internet)),
3. shows the public link in a big box, **copies it to your clipboard** (just press Ctrl+V) and saves it in
   `tunnel-link.txt`,
4. opens the **Share** tab in your browser, with the QR code ready.

Keep the window open while the app is in use; **Ctrl+C** stops the app and the tunnel together. Logs go to `logs/`.
Options: `.\start.ps1 -NoBrowser` (do not open the browser) and `.\start.ps1 -Port 3001` (another port).

## Run the app

**1. Start the server** in the project folder:

```powershell
poetry run image-generator
```

(`poetry run python -m image_generator` does the same.) You should see something like:

```
OpenAI image generation enabled (model: gpt-image-2.5-sunburst).
Open http://localhost:3000 once the server is running.
INFO:     Uvicorn running on http://127.0.0.1:3000 (Press CTRL+C to quit)
```

The terminal stays busy (no new prompt) while the app is running. That is correct: keep this terminal open.

**2. Open the app** in your browser: http://localhost:3000

- The **Words** tab opens first. Add a few words.
- Click the **Generate** tab, log in with your `ADMIN_PASSWORD`, select words and click **Generate image**.
  You can go straight to this tab with http://localhost:3000/#generate.

**3. Stop the server** by pressing **Ctrl+C** in that terminal.

After changing `.env`, stop the server and run `poetry run image-generator` again so it picks up the new values.

The server only listens on your own computer (`127.0.0.1`); the tunnel below makes it reachable from outside.
Set `PORT` in `.env` to use another port.

## Share it over the internet

By default only you can open the app. To give others a link that works from anywhere, use a free Cloudflare tunnel.
The easiest way is the [Quick start](#quick-start-app--public-link-in-one-go-windows) script (`start.cmd`), which does
steps 2 and 3 for you. Below are the manual steps.

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

- The link only works while your computer is on and **both** terminals (`poetry run image-generator` and
  `cloudflared`) are running.
- Every time you restart `cloudflared` you get a **new** link; the old one stops working.
  Restarting only the app keeps the same link.
- To stop sharing, press **Ctrl+C** in the `cloudflared` terminal.
- A red `ERR Failed to initialize DNS local resolver` line in the output is harmless.
- Running a public tunnel from a work laptop may be against company policy. Check first.

## Limits and security

- Words must not be empty and can be at most 50 characters. You can select at most 20 words per image.
- Words are optional when generating: the text in **Altijd meesturen** and/or ticked photos are enough.
  With no words, no photos and an empty **Altijd meesturen**, the app asks you to add something first.
- **Alle woorden verwijderen** (on the Generate and Woordweb tabs) deletes every word after a confirmation.
  This cannot be undone; context, photos and images are kept.
- After 5 wrong passwords, that visitor is locked out of the Generate tab for 15 minutes.
- A login lasts 12 hours and ends when the server restarts.
- Context: max 1,000 characters. Photos: max 20 stored, max 4 per image, description max 100 characters.
- The Workers AI free tier has a daily limit (10,000 neurons, resets at 00:00 UTC). When it is reached,
  the app says so; try again the next day.
- There is no limit on how many words visitors can add. Delete unwanted ones on the Generate tab.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `poetry : The term 'poetry' is not recognized` | Poetry is not installed, or the terminal was opened before installing it. Close VS Code completely and open it again. |
| `error while attempting to bind on address ... 3000` | Another program is using port 3000. Close the other server, or add `PORT=3001` to `.env` and open http://localhost:3001. |
| "Missing Cloudflare credentials" | `CLOUDFLARE_ACCOUNT_ID` or `CLOUDFLARE_API_TOKEN` is empty in `.env`. Fill it in, save, and restart the server. |
| "Cloudflare rejected the credentials" | The account ID or token is wrong, or the token lacks the Workers AI permission. Create a new token with the **Workers AI** template. |
| "OpenAI heeft de API-sleutel geweigerd" | `OPENAI_API_KEY` in `.env` is wrong. Create a new key on platform.openai.com and restart the server. |
| "OpenAI-tegoed of budgetlimiet is bereikt" | Add credit or raise your budget limit on platform.openai.com. |
| "geen toegang tot gpt-image-…" | Verify your organization on platform.openai.com, or set `OPENAI_IMAGE_MODEL` to a model you can use. |
| "Daily free Workers AI limit reached" | You used up today's free generations. Try again after 00:00 UTC. |
| "ADMIN_PASSWORD is not set" | Add `ADMIN_PASSWORD=…` to `.env` and restart the server. |
| "Too many wrong passwords" | Wait 15 minutes, or restart the server. |
| `start.ps1 cannot be loaded because running scripts is disabled` | Double-click `start.cmd` instead; it runs the script without changing your settings. |
| Start script: "The app is not installed yet" | Run `poetry install` once in the project folder. |
| Start script: "cloudflared is not installed" | Run `winget install Cloudflare.cloudflared` once. |
| Start script: "Port 3000 is already in use" | The app is probably still running somewhere: close that window, or use `.\start.ps1 -Port 3001`. |
| Start script stops with an error | Look in `logs/app-errors.log` (the app) or `logs/cloudflared.log` (the tunnel). |

## Project files

| File / folder | What it is |
|---------------|------------|
| `image_generator/app.py` | Builds the app: routers, error handlers, the static page |
| `image_generator/routers/` | The API routes, one file per part: `session`, `words`, `context`, `photos`, `images`, `share`, `generate` |
| `image_generator/schemas.py` | Pydantic models for the request bodies, with the Dutch error messages |
| `image_generator/deps.py` | FastAPI dependencies: settings, a database connection per request, the admin check |
| `image_generator/providers.py` | Calls to Cloudflare Workers AI and OpenAI, and their error messages |
| `image_generator/prompt.py` | Building the prompt from words, context, glossary and photos |
| `image_generator/auth.py` | Admin login, sessions and the lock after wrong passwords |
| `image_generator/db.py` | The SQLite database |
| `image_generator/storage.py` | Image and photo files, and loading `context.txt`, `woordenlijst.txt` and `reference-photos/` at startup |
| `image_generator/errors.py` | How errors are sent to the page (`{"error": "..."}`) |
| `image_generator/config.py` | Settings from `.env`, paths and limits |
| `image_generator/__main__.py` | Starts the server (`poetry run image-generator`) |
| `tests/` | The tests (pytest) |
| `start.cmd`, `start.ps1` | Start the app and a Cloudflare tunnel in one go, and copy the public link (Windows) |
| `public/index.html`, `public/app.js`, `public/style.css` | The web page with all tabs |
| `data/` | All data: `words.db`, `images/` (generated) and `photos/` (uploaded); created on first start, not committed |
| `.env` / `.env.example` | Your settings and secrets / an empty template |
| `context.txt` | Optional: your "Altijd meesturen" text, loaded at startup when changed (not committed: personal) |
| `woordenlijst.txt` | Optional: your "Woordenlijst" (glossary), loaded at startup when changed (not committed: personal) |
| `reference-photos/` | Optional: photos added to "Foto's" at startup and ticked by default (only its README is committed) |
| `logs/`, `tunnel-link.txt` | Created by the start script: logs, and the latest public link (not committed) |

## Development

```powershell
poetry run pytest          # all tests, with a coverage report (must stay at 100%)
pre-commit install         # once: run black, isort, flake8 and the secret scan before every commit
pre-commit run --all-files # run those checks now
```

The tests use temporary folders and a fake Cloudflare/OpenAI, so they never touch your data and cost nothing.

How the code is organised:

- Routes are plain `def` functions; FastAPI runs them in a thread pool, so slow disk or database work never blocks
  other requests. Only `/api/generate` is `async`, because it waits up to a minute for the AI service; its database
  and file work goes through `run_in_threadpool`.
- Every request gets its own database connection via `Depends(get_db)`; settings and the admin check come in via
  `Depends` too.
- Request bodies are Pydantic models (`schemas.py`). Their Dutch messages are sent to the page as `{"error": ...}`.

## API

For reference; the web page uses these routes. "Admin" routes need you to be logged in.

| Method | Route             | Body / notes                                     |
|--------|-------------------|--------------------------------------------------|
| POST   | `/api/words`      | `{ "text": "..." }` – non-empty, max 50 chars    |
| GET    | `/api/words`      | List words (admin)                               |
| DELETE | `/api/words`      | Delete all words (admin)                         |
| DELETE | `/api/words/:id`  | Delete a word (admin)                            |
| POST   | `/api/prompt`     | Same body as `/api/generate`; returns the prompt without generating (admin) |
| POST   | `/api/generate`   | `{ "ids": [1, 2], "photoIds": [3], "provider": "cloudflare" or "openai", "quality": "low"/"medium"/"high" }` – 0–20 words, 0–4 photos (admin) |
| GET/PUT | `/api/merges`    | Read / save the word cloud variants `{ "merges": "paarden = paard, horses" }` (admin) |
| GET    | `/api/providers`  | Which services are set up, and the OpenAI model (admin) |
| DELETE | `/api/images/:filename` | Delete a generated image (admin) |
| GET/PUT | `/api/context`   | Read / save the context `{ "context": "...", "glossary": "..." }` (admin) |
| GET    | `/api/qr.svg?url=…` | QR code (SVG) for a share link (admin)          |
| GET/POST | `/api/photos`   | List / upload a photo `{ "image": "data:image/jpeg;base64,...", "caption": "..." }` (admin) |
| DELETE | `/api/photos/:id` | Delete a photo (admin)                           |
| GET    | `/api/images`     | List generated images, newest first (admin)      |
| POST   | `/api/login`      | `{ "password": "..." }` – logs in (sets a cookie) |
| POST   | `/api/logout`     | Logs out                                         |
| GET    | `/api/session`    | `{ "admin": true/false }`                        |
