# Adopting NC Benefits Navigator at your organization

This guide is written for a director or program manager with **no IT staff**.
If you can follow a recipe, you can run this tool. Total setup time is about
an hour; ongoing effort is near zero.

## What you'll need

1. **An Anthropic API key** (the AI service the interviewer runs on) — free to
   create, pay-per-use.
2. **A place to run the app** — we recommend Fly.io, walked through below.
3. **A credit card** for both. Realistic total cost is **$5–25 per month**
   (the math is below).

## Step 1: Get an Anthropic API key

1. Go to <https://console.anthropic.com> and click **Sign up**. Use your
   organization email.
2. Once signed in, open **Billing** (left sidebar) and add a payment method.
   Add an initial credit of $5 — that alone covers roughly 45 screenings.
3. Open **API Keys** (left sidebar) and click **Create Key**. Name it
   `benefits-navigator`.
4. Copy the key — it starts with `sk-ant-`. **Save it somewhere private**
   (a password manager, not a shared document). You will paste it once in
   Step 2 and never need it again.

![Anthropic console screenshot](img/anthropic-console.png)

> **Treat the key like a debit card number.** Anyone who has it can spend
> your Anthropic credit. Don't email it or put it in a shared drive.

## Step 2: Put it online with Fly.io

Fly.io runs the app on a small server that **turns itself off when nobody is
using it**, which is why it costs so little.

1. Create an account at <https://fly.io> and add a payment method.
2. Open the **Terminal** app on your computer (on a Mac: press Cmd-Space,
   type "Terminal", press Return; on Windows: open "PowerShell").
3. Install the Fly command-line tool by pasting this line and pressing Return:
   - Mac: `curl -L https://fly.io/install.sh | sh`
   - Windows: `pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"`
4. Download the app's code (paste each line, press Return, wait for it to
   finish):

   ```
   git clone https://github.com/keeganburkart/nc-benefits-navigator.git
   cd nc-benefits-navigator
   ```

5. Sign in and create your copy of the app (pick your own app name — it
   becomes your web address):

   ```
   fly auth login
   fly apps create your-org-benefits-navigator
   ```

6. Open the file called `fly.toml` in the downloaded folder with any text
   editor and change the first line, `app = "..."`, to the app name you just
   created. Save it.
7. Give the app your API key from Step 1 (paste your real key in place of
   `sk-ant-...`). This stores it secretly on Fly's servers — it never appears
   in any file:

   ```
   fly secrets set ANTHROPIC_API_KEY=sk-ant-...
   ```

8. Launch it:

   ```
   fly deploy
   ```

   The first deploy takes a few minutes. When it finishes, your tool is live
   at `https://your-org-benefits-navigator.fly.dev`. Bookmark it, share it
   with your staff, and you're done.

To update to a newer version later: open Terminal in the same folder and run
`git pull` then `fly deploy`.

**Access note:** the app has no login screen by design (no accounts means no
stored credentials). Share the web address only with staff, the same way you
would a private phone number. If you need a login wall in front of it, ask
whoever manages your website — any standard reverse proxy works — or open a
GitHub issue and we'll point you in the right direction.

## What it costs per month

- **The AI**: a complete screening conversation costs about **$0.11** in API
  usage (measured, not estimated). At 50 screenings a month that's ~$6; at 200
  it's ~$22. The app also enforces a **daily spending cap** (default $10/day,
  set by `NAV_DAILY_BUDGET_USD`) so a runaway day can't surprise you.
- **The server**: with auto-stop enabled (it is, in the provided `fly.toml`),
  a small Fly.io machine typically costs **$2–4/month**.

So: **roughly $5–25/month** depending on volume, with a hard daily ceiling
you control.

## Privacy, in plain English

- **The tool stores nothing.** There is no database. A screening session
  lives in the server's memory and is erased when it ends, when it sits
  idle for an hour, or when anyone clicks "New screening." There is nothing
  to breach, subpoena, or back up.
- **What leaves your screen:** the household facts the caseworker types
  (ages, income amounts, expenses — the tool never asks for names, SSNs, or
  addresses) are sent to Anthropic's API to run the interview, the same way
  your email provider sees your email. Under Anthropic's
  [commercial terms](https://www.anthropic.com/legal/commercial-terms),
  API inputs are not used to train models by default.
- **Best practice:** keep clients' names out of the chat. The tool is
  designed so you never need them — "the mom," "the 7-year-old" work fine.
- This tool is a screening aid, **not** a system of record, and screening
  facts of this kind are generally not HIPAA-covered — but your own
  privacy policies apply. When in doubt, show this page to your compliance
  person; the "stores nothing" design usually ends the conversation.

## Keeping the numbers current

Benefit limits change every year (new poverty guidelines each January, new
SNAP figures each October). The tool **refuses to run with expired figures**
rather than quietly using stale ones, so you'll know. Updating is a small
data change described in [rules.md](rules.md) — watch the GitHub repository
(click **Watch** → **Releases**) and run `git pull` + `fly deploy` when an
update lands.
