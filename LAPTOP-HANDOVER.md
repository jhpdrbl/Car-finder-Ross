# Running the CPO SUV Finder with Claude Code on the laptop

You won't type commands. Claude Code on the laptop runs everything; you click **Allow** when it asks.
About 20 minutes the first time, then one sentence each time.

## Part 1: Install (one time, ~10 minutes)

1. **Install Git for Windows** (Claude uses it to download the project and upload results):
   go to <https://git-scm.com/downloads/win>, download, run it, and click **Next** through every
   screen (the defaults are fine).
2. **Install the Claude desktop app**: go to <https://claude.com/download>, download the Windows
   version, run it, and **sign in** with the same Claude account you use on the iPad.
   (Claude Code needs a Pro or Max plan, which you already use.)
3. In the app, switch to **Code** (Claude Code). When it asks which folder to work in, pick your
   **Documents** folder. If it offers a choice between running locally or in the cloud, choose
   **local / this computer**. That's what lets the dealer sites see your home connection.
4. **Turn off any VPN** on the laptop before running a search.

> If you'd rather use a terminal instead of the app: open PowerShell, paste
> `irm https://claude.ai/install.ps1 | iex`, open a new PowerShell window, type
> `cd $HOME\Documents` then `claude`, and sign in when the browser opens.

## Part 2: First session (paste this, ~15–30 minutes)

Paste this into Claude Code on the laptop:

> Please set up my car search project on this laptop and run it.
> 1. Clone https://github.com/jhpdrbl/Car-finder-Ross.git (branch `claude/la-cpo-suv-scraper-x0pl15`)
>    into my Documents folder, then work from that folder.
> 2. Read CLAUDE.md in the project; it explains everything. Follow its section
>    "If you are a Claude session ON THE LAPTOP", including first-time setup.
> 3. Ask me before installing the ~150 MB browser add-on (my answer will be yes).
> 4. Run the Audi diagnose first and fix the Audi scraper if the report shows it needs it.
> 5. Then run the full refresh, publish the results to my phone page, and tell me in plain
>    words: how many cars match, how many need a call, what's new, any price drops, and which
>    dealers failed and why. I'm not technical, so keep it simple.
> 6. Then set up the automatic daily search (CLAUDE.md, first-time step 7) for 6:30 am every day.

What to expect:
- **Permission prompts.** Claude asks before each command. Click **Allow**. If you see
  **"Allow always"** (or "don't ask again for this project"), you can choose it for this folder.
- **A GitHub sign-in window** may pop up the first time Claude uploads. Sign in and click **Authorize**.
- **Python** may get installed for you (Claude asks first).
- The search itself takes about 10–20 minutes the first time. Keep the laptop awake and plugged in.
- When it's done, your phone page <https://cpo-suv-finder.pages.dev> updates about 2 minutes later.

## Part 3: Every time after that (one sentence)

Open the Claude app → **Code** → the **Car-finder-Ross** folder (in Documents) and say:

> Run the refresh and publish it, then summarize the results for me.

That's it. Claude gets the latest version of the tool first (in case it was improved from your
iPad), runs the search, uploads the results, and gives you a summary.

## Automatic search every morning

After the first session, the laptop runs the search **by itself every morning** (6:30 am unless you
asked for another time) and updates your phone page. Keep it **plugged in**; it can be closed or asleep,
it wakes itself up. If it was off at that time, it runs the next time it's on.
To change the time or stop it, ask Claude on the laptop ("run the daily search at 7 instead" / "stop the
daily search"). You can also run the search from your iPad any time: see [IPAD.md](IPAD.md).

## Your phone page after a laptop search

- Same address, same tabs: **Cars**, **♥** (favorites), **Compare**, **Trims**, **Sold**. The laptop
  search simply adds the dealers your phone couldn't reach (Audi especially).
- **Favorites carry over.** They're saved online and tied to each car's VIN, so a new search never
  erases them. Sold favorites show at the top of the ♥ tab. Claude's summary will mention changes to them.
- On the laptop, look at favorites on the online page (<https://cpo-suv-finder.pages.dev>), not the
  copy that opens after a search (that copy can't sync).

## Handy things to ask Claude on the laptop

- "Why did <dealer> fail?" / "Why isn't this car on my list: <link>?"
- "Add the <model> to my search" / "Exclude <color>" / "Raise my price cap to $36,000"
- "Show me only the Audis that match" (it can read `data/listings.csv` for you)

## If something goes wrong

- Claude says lots of dealers are **blocked**: check that the VPN is off and the laptop is on home Wi-Fi.
- The phone page didn't update: ask Claude "did the publish to Cloudflare succeed?"
- Anything else: take a screenshot and show it to Claude on the laptop, or to Claude on your iPad.

## For Claude (handover note)

Everything you need is in `CLAUDE.md` (state, runbook, decisions, open items) and `README.md`
(technical reference). The user is non-technical and won't run commands; you run them. Don't run
the `.bat` files (they block on keypress prompts). First-time priority: the Audi diagnose and
adapter (`scrapers/audi_network.py`), because Audi is a top brand and was never testable from the cloud.
In every summary, start with the user's favorites (`curl -s https://cpo-suv-finder.pages.dev/api/favs`):
price drops, sold, or no longer matching. See CLAUDE.md, "Every refresh".
There are two buyers (Ross and Jenna, CLAUDE.md "Two buyers"): one run updates both. Summarize each separately;
Jenna's favorites are `curl -s "https://cpo-suv-finder.pages.dev/api/favs?p=jenna"`, her results `data/jenna/listings.csv`.
