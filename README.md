# Bills — deploy to Fly.io

## 1. Install flyctl (one-time, on your machine)
```bash
curl -L https://fly.io/install.sh | sh
fly auth signup      # or: fly auth login
```

## 2. Deploy
From inside this folder:
```bash
fly launch --no-deploy --copy-config --name shantry-bills
fly volumes create bills_data --region ord --size 1
fly secrets set APP_PASSWORD='pick-a-real-password' SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(16))')"
fly deploy
```
`fly launch` will ask a few setup questions — say no to Postgres/Redis, you don't need them.

## 3. Get the URL
```bash
fly status
```
It'll be `https://shantry-bills.fly.dev` (or whatever name wasn't taken).

## 4. On Jon's phone
- Open the URL in Safari (iOS) or Chrome (Android)
- Log in with the password you set
- Share button → "Add to Home Screen" — it'll behave like a real app icon, no App Store needed

## Notes
- SQLite file lives at `/data/bills.db` on the Fly volume — survives deploys and restarts.
- Free allowance covers this easily: 1 shared-cpu-1x-256mb VM + 3GB volume storage is well under Fly's monthly free usage for a single low-traffic app. You may need a card on file even if you stay under the free tier.
- Back up the db anytime: `fly ssh sftp get /data/bills.db ./bills-backup.db`
- To change the password later: `fly secrets set APP_PASSWORD='new-password'`

## 5. SMS reminders (free, via email-to-SMS gateway)

Every US carrier will turn an email sent to a special address into a text on that number. No third-party account, no per-message cost — just a Gmail account to send from.

**Find Jon's gateway address** — `<his 10-digit number>@<carrier domain>`:

| Carrier | Domain |
|---|---|
| Verizon | `vtext.com` |
| AT&T | `txt.att.net` |
| T-Mobile | `tmomail.net` |
| Sprint (now T-Mobile) | `messaging.sprintpcs.com` |
| Boost Mobile | `sms.myboostmobile.com` |
| Cricket | `sms.cricketwireless.net` |
| US Cellular | `email.uscc.net` |

Example: a Verizon number `5551234567` → `5551234567@vtext.com`

**Get a Gmail app password** (needed since Gmail blocks plain-password SMTP login):
1. Turn on 2-Step Verification on the sending Gmail account, if not already on: myaccount.google.com/security
2. Go to myaccount.google.com/apppasswords, create one named "bills", copy the 16-character password.

**Wire it up:**
```bash
fly secrets set \
  CRON_SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(16))')" \
  SMTP_USER='cwicomputers@gmail.com' \
  SMTP_PASS='your-16-char-app-password' \
  JON_SMS_GATEWAY='5551234567@vtext.com' \
  REMINDER_DAYS_BEFORE='3'
fly deploy
```

**Schedule the daily check** — push this repo to GitHub, then add the same `CRON_SECRET` value as a repo secret:
- GitHub repo → Settings → Secrets and variables → Actions → New repository secret → name it `CRON_SECRET`, paste the same value you set on Fly.

`.github/workflows/reminders.yml` is already in this project and fires daily at ~9am Eastern via `curl` to `/cron/reminders`. Test it manually from the repo's Actions tab ("Run workflow") or with:
```bash
curl -X POST https://shantry-bills.fly.dev/cron/reminders -H "X-Cron-Secret: your-cron-secret"
```

**Caveat:** carrier gateways are free but not guaranteed — delivery can lag a few minutes, and carriers occasionally throttle or silently drop these if Gmail's sending IP gets flagged as spammy. Fine for a daily nudge; not something to rely on for anything time-critical.

## Local testing before deploy
```bash
pip install -r requirements.txt
APP_PASSWORD=test python3 app.py
```
Open http://localhost:8080
