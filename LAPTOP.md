# Running the search from your Windows laptop

Same idea as the iPad: open a window, go to the folder, run one command. The laptop does better than
the iPad because it can use a real browser for the dealer sites that need one (Audi especially).

**Good to know first**
- Be on **home Wi-Fi with any VPN off** (a VPN makes dealer sites block you).
- Keep the laptop **plugged in and awake** while it runs. The first search takes 20–40 minutes because
  it re-checks every car; later ones are faster.
- If anything looks wrong, take a screenshot and show it to Claude on the iPad.

## Step 1: Install Python (once)

1. Go to <https://www.python.org/downloads/> and click the yellow **Download Python** button.
2. Open the downloaded file. On the first screen, **tick "Add python.exe to PATH"** (at the bottom),
   then click **Install Now**. Click **Close** when it's done.

## Step 2: Download the project (once)

1. Click **Start**, type **PowerShell**, and open **Windows PowerShell** (a blue window).
2. Paste each line (right-click pastes) and press **Enter**, one at a time:

```
cd $HOME
```
```
python -c "import urllib.request as u,zipfile,io,os;z=zipfile.ZipFile(io.BytesIO(u.urlopen('https://codeload.github.com/jhpdrbl/Car-finder-Ross/zip/refs/heads/claude/la-cpo-suv-scraper-x0pl15').read()));z.extractall();os.rename(z.namelist()[0].rstrip('/'),'Car-finder-Ross')"
```
```
cd Car-finder-Ross
```
```
python -m pip install -r requirements.txt
```

If `python` "is not recognized" or opens the Microsoft Store: redo step 1 and make sure the PATH box is
ticked, then close PowerShell and open it again.

## Step 3: The browser add-on and an upload key (once)

1. Still in PowerShell, paste these two lines one at a time (about 150 MB, a few minutes):

```
python -m pip install "playwright>=1.48"
```
```
python -m playwright install chromium
```

2. Make an upload key, same as on the iPad (your iPad's key stays on the iPad, so make a new one):
   go to **github.com/settings/personal-access-tokens/new** → Token name `Laptop car finder` →
   Expiration: the longest offered → **Only select repositories** → **Car-finder-Ross** →
   **Repository permissions** → **Contents** → **Read and write** → **Generate token** → copy the code
   (starts with `github_pat_`).

## Step 4: Run the search

```
cd $HOME\Car-finder-Ross
```
```
python search.py
```

(It's the same script as on the iPad, but on the laptop it does more: it uses the browser add-on for the
dealer sites that need one, reads twice as many dealers at once, and keeps a page cache so later runs are faster.)

- The first time, it asks you to **paste the GitHub key** from step 3 (right-click pastes; you won't
  see it, that's on purpose). Press **Enter**. It won't ask again.
- It gets the latest version, runs the search (6 stages and a coverage report), and uploads the results.
  Leave the window open until it says **"Uploaded."**
- About 2 minutes later, refresh <https://cpo-suv-finder.pages.dev>.

## Every time after that

Open PowerShell, then:

```
cd $HOME\Car-finder-Ross
```
```
python search.py
```

## Automatic search every morning (optional)

After your first successful run, paste this in PowerShell (in the `Car-finder-Ross` folder) to run the
search by itself every day at 6:30 am (change the time if you like):

```
powershell -ExecutionPolicy Bypass -File setup-schedule.ps1 -Time 06:30
```

Keep the laptop plugged in; it wakes itself up. If Windows asks, allow wake timers (Control Panel →
Power Options → Change plan settings → Change advanced power settings → Sleep → Allow wake timers →
Enable). Each run writes a log in the `logs` folder. To turn it off:
`powershell -ExecutionPolicy Bypass -File setup-schedule.ps1 -Remove`

## If something goes wrong

- **Lots of dealers "blocked"**: check the VPN is off and you're on home Wi-Fi.
- **"Upload refused"**: the key is wrong or missing the Contents permission. Type `del .github_token`,
  make a new key (step 3), and run `python search.py` again.
- **Upload failed for another reason** (Wi-Fi dropped): `python search.py upload` retries just the upload.
- **It stopped halfway** (the laptop slept): run `python search.py` again.
- **Anything else**: screenshot the window and show it to Claude.
