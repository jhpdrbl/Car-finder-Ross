# Running the search from your iPad

This runs the full search on your iPad, on your home Wi-Fi (dealer sites don't block home internet),
and updates your phone page when it's done. It uses a free terminal app called **a-Shell**.

**Good to know first**
- The search takes about 15–30 minutes. **a-Shell must stay open on screen** the whole time:
  iPadOS stops apps that are in the background or when the screen locks.
- Be on **home Wi-Fi with any VPN off**. (iCloud Private Relay only affects Safari, so it's fine.)
- A few dealer sites only work with a full web browser, which can't run on an iPad. Those show as
  "failed" in the coverage report. The laptop can read them (that matters most for Audi).
- This is new: if anything looks wrong, take a screenshot and show it to Claude.

## Step 1: Install a-Shell (once)

1. Open the **App Store**, search for **a-Shell** (by Nicolas Holzschuch, free), and install it.
   Get **a-Shell**, not "a-Shell mini" (the mini version doesn't include Python).
2. Open it. You'll see a text screen with a `$` prompt. You type (or paste) a command and press **return**.

Tip: open this guide in Safari, press and hold a command to copy it, then in a-Shell tap and hold → **Paste**.

## Step 2: Download the project (once)

Paste each line and press **return**, one at a time:

```
cd ~/Documents
```
```
python -c "import urllib.request as u,zipfile,io,os;z=zipfile.ZipFile(io.BytesIO(u.urlopen('https://codeload.github.com/jhpdrbl/Car-finder-Ross/zip/refs/heads/claude/la-cpo-suv-scraper-x0pl15').read()));z.extractall();os.rename(z.namelist()[0].rstrip('/'),'Car-finder-Ross')"
```
```
cd Car-finder-Ross
```
```
pip install requests requests-cache beautifulsoup4 pyyaml markdown
```

The last one takes a minute and prints a lot of text. If it ends with an error in red, send Claude a screenshot.

## Step 3: Make an upload key on GitHub (once, about 3 minutes)

This lets the iPad put the results on your phone page. It only works for this one project.

1. In Safari, go to **github.com/settings/personal-access-tokens/new** and sign in.
2. **Token name:** `iPad car finder`. **Expiration:** pick the longest offered (or "No expiration").
3. **Repository access:** **Only select repositories** → choose **Car-finder-Ross**.
4. **Permissions** → **Repository permissions** → **Contents** → **Read and write**.
5. Tap **Generate token**, then **copy** the long code it shows (it starts with `github_pat_`).
   GitHub shows it only once; the next step saves it on the iPad.

## Step 4: Run the search

In a-Shell (if you just did steps 1–3, you're already in the right folder):

```
cd ~/Documents/Car-finder-Ross
```
```
python ipad.py
```

- The first time, it asks you to **paste the GitHub key** from step 3. Paste it and press return.
  It's saved on the iPad (never uploaded), so it won't ask again.
- It then gets the latest version, runs the search (you'll see 6 stages and a coverage report), and
  uploads the results. **Leave a-Shell on screen until it says "Uploaded."**
- About 2 minutes later, refresh <https://cpo-suv-finder.pages.dev>.

## Every time after that

Open a-Shell, then:

```
cd ~/Documents/Car-finder-Ross
```
```
python ipad.py
```

Keep the iPad plugged in, and set **Settings → Display & Brightness → Auto-Lock → Never** while
it runs (set it back afterwards if you like).

## If something goes wrong

- **It stopped halfway** (the screen locked, or you switched apps): just run `python ipad.py` again.
- **"Upload refused"**: the key is wrong or missing the Contents permission. Type `rm .github_token`,
  make a new key (step 3), and run `python ipad.py` again (it asks for the new key).
- **Upload failed for another reason** (e.g. Wi-Fi dropped): run `python ipad.py upload` to retry
  just the upload.
- **Anything else**: screenshot a-Shell and show it to Claude.
