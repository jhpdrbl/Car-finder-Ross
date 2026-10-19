# Setting up the CPO SUV Finder on your Windows computer

About 15 minutes the first time. After that, it's one double-click.

Why your home computer: many dealer websites (all Audi dealers, plus every site
on the "Dealer Inspire" platform) block cloud servers but load normally from a
home internet connection.

---

## Step 1: Install Python and Git (one time)

1. Click the **Start** button, type **PowerShell**, and open **Windows PowerShell**.
2. Copy this line, paste it into the blue window (right-click pastes), and press **Enter**:

   ```
   winget install -e --id Python.Python.3.13
   ```

   Say **Y** if it asks to agree to terms.
3. Then paste this line and press **Enter**:

   ```
   winget install -e --id Git.Git
   ```

4. **Close PowerShell** and open it again (so it notices the new programs).

> If `winget` isn't recognized: install Python from <https://www.python.org/downloads/>
> (tick **"Add python.exe to PATH"** on the first screen) and Git from
> <https://git-scm.com/download/win> (accept all the defaults).

## Step 2: Download the tool (one time)

In PowerShell, paste these three lines one at a time, pressing **Enter** after each:

```
cd $HOME\Documents
git clone -b claude/la-cpo-suv-scraper-x0pl15 https://github.com/jhpdrbl/Car-finder-Ross.git
cd Car-finder-Ross
```

A browser window may pop up asking you to sign in to GitHub. Sign in and click
**Authorize**. This happens once.

The tool is now in **Documents → Car-finder-Ross**.

## Step 3: Set it up (one time)

1. Open **File Explorer** → **Documents** → **Car-finder-Ross**.
2. Double-click **`setup.bat`**.
   - If Windows shows "Windows protected your PC", click **More info** → **Run anyway**.
     (It's a plain text script; you can open it in Notepad to read it.)
3. When it asks **"Install the browser add-on now [Y,N]?"**, press **Y**. It's about
   150 MB and some dealer sites need it.
4. Wait for **"Setup finished"**, then press any key.

## Step 4: Run the search (every time)

Double-click **`refresh.bat`**.

- The first run takes roughly 10–20 minutes, because it politely waits 2–3 seconds between
  requests to each dealer site. Later runs are faster (cars already ruled out aren't re-read).
- When it finishes, your **dashboard opens in your browser** automatically, and the window
  asks **"Publish these results to your phone page?"** Press **Y**. About 2 minutes later your
  phone page (cpo-suv-finder.pages.dev) shows the new results.
- Everything it made is in the **`output`** folder:
  - `dashboard.html`: the sortable table (NEW bubbles, green ▼ on price drops, original prices, filters)
  - `digest_<date>.md`: the newsletter-style summary (open with Notepad and paste into Apple Notes)
- The data is in the **`data`** folder: `listings.csv`, `price_history.csv` and `coverage.csv` (which dealers worked).

You can leave the window alone while it runs. Your computer needs to stay awake
and online.

---

## Sending Claude what it needs

**The first time, please do this before your first full run:**

1. Double-click **`diagnose.bat`**. It checks the Audi dealer sites (takes a few minutes).
2. It writes a file `output\diagnose_<date>.md`. Attach that file in the Claude chat.
   It contains only how the websites are built (no personal information).

Claude uses it to tune the Audi part, because Audi's sites can't be seen from Claude's side.

**After a run**, to show Claude your results, either:

- attach `output\digest_<date>.md` and `data\coverage.csv` in the chat, **or**
- double-click **`share-results.bat`**, which uploads the `data` and `output`
  folders to GitHub so Claude can read them directly.

---

# Part 2: See your results on your phone (one time)

> ✅ **Already done** (October 2026, from the iPad): Cloudflare key, GitHub secrets, first
> publish, and favorites sync. You don't need to repeat it. It's kept here for reference
> or in case you ever need to redo it.

After each laptop run, `refresh.bat` asks **"Publish these results to your phone page?"**
Press **Y** and about 2 minutes later your phone page shows the new results.
It always shows the last laptop run; the search itself only runs on the laptop.

The published copy leaves out your down payment and pre-approval details.

**You can do all of Part 2 from your iPad right now, in Safari.**

### 2a. Cloudflare: make a key GitHub can use

1. Go to <https://dash.cloudflare.com> and sign in (or create a free account).
2. Top right: your profile icon → **My Profile** → **API Tokens** → **Create Token**.
3. Scroll to **Custom token** → **Get started**.
   - Token name: `car finder`
   - Permissions: **Account** · **Cloudflare Pages** · **Edit**
   - Click **Continue to summary** → **Create Token**.
4. **Copy the token** it shows (you only see it once). Keep this tab open.
5. Your **Account ID**: go back to the dashboard home, open **Workers & Pages**. The
   Account ID is on the right side (or it's the long code in the address bar after
   `dash.cloudflare.com/`). Copy it too.

### 2b. GitHub: store the key

1. Go to <https://github.com/jhpdrbl/Car-finder-Ross> → **Settings** → **Secrets and variables** → **Actions**.
2. **New repository secret**: Name `CLOUDFLARE_API_TOKEN`, Secret = the token. Save.
3. **New repository secret**: Name `CLOUDFLARE_ACCOUNT_ID`, Secret = the Account ID. Save.

### 2c. Publish once to test

1. In the repo, open the **Actions** tab → **Publish dashboard** (left side).
2. **Run workflow** → choose branch `claude/la-cpo-suv-scraper-x0pl15` → **Run workflow**.
3. After about 2 minutes it shows a green check. Your page is at
   **<https://cpo-suv-finder.pages.dev>**. Add it to your phone's home screen
   (Share → Add to Home Screen).

If it shows a red X, tap it and send Claude a screenshot. (If the name
`cpo-suv-finder` is taken, Claude will pick another.)

### 2d. Make the page private (optional; skipped)

You decided (Oct 2026) not to do this: nothing on the page is sensitive. Without it, anyone who
guesses the address could see the page, and favorites are one shared list. Steps, if you ever want it:

1. Cloudflare → **Workers & Pages** → **cpo-suv-finder** → **Settings** → **General** →
   **Access policy** → **Enable access policy**. (If asked: pick a team name and the **Free** plan.)
2. Next to Access policy tap **Manage** (or **Zero Trust** → **Access** → **Applications**) and open
   the application named like **cpo-suv-finder - Cloudflare Pages** → **Edit**.
3. Its addresses should include **both** `*.cpo-suv-finder.pages.dev` (already there) and
   `cpo-suv-finder.pages.dev` (add it).
4. Policy: Action **Allow**; Include → **Emails** → your email. Remove other Include rules. Save.
5. Test in a Private Safari tab: the page should ask for your email and send a code.

---

## Getting updates

When Claude says there's a new version, double-click **`update.bat`**, then run
**`refresh.bat`** as usual.

---

## Using Claude on the laptop (optional)

If you open Claude Code on the laptop in the `Car-finder-Ross` folder, it reads `CLAUDE.md`
automatically and knows how to run the search and publish. You can just say
"run the full refresh and publish it".

---

## Handy extras (optional)

Open PowerShell in the folder (in File Explorer, click the address bar, type
`powershell`, press Enter), then:

| What | Command |
|---|---|
| Only some brands | `.venv\Scripts\python run.py refresh --brands Audi,Subaru` |
| Only one dealer | `.venv\Scripts\python run.py refresh --dealers "McKenna"` |
| Diagnose another brand | `.venv\Scripts\python run.py diagnose --brand BMW` |
| Diagnose one dealer | `.venv\Scripts\python run.py diagnose --dealer "Audi Pasadena"` |

Your settings (price caps, colors, models, scoring) are in **`config.yaml`**; open
it with Notepad. Cars you want hidden go in **`data\exclusions.csv`** (VIN, reason).

## If something goes wrong

| You see | Do this |
|---|---|
| `Python was not found` | Redo Step 1, then close and reopen PowerShell. |
| `'git' is not recognized` | Redo the Git part of Step 1, close and reopen PowerShell. |
| "Windows protected your PC" | Click **More info** → **Run anyway**. |
| A dealer shows "blocked" in the coverage report | Normal for a few sites; send Claude the coverage report. |
| `share-results.bat` says "Upload failed" or mentions a conflict | Send Claude a screenshot. Don't delete anything; your results are still in the folder. |
| Phone page didn't update | On github.com → repo → **Actions** → "Publish dashboard": green check = done (refresh the page); red X = send Claude a screenshot. |
| Anything else | Take a screenshot of the window and send it to Claude. |
