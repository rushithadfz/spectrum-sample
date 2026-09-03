# Spectrum Incentive Portal

A working proof of concept for a sales incentive portal: agents log sales and
watch their commission, team leads approve those sales and draft incentive
plans, and managers fund the plans, clear exceptions and close the month.

Django 5.2 and SQLite, server-rendered templates, vanilla JavaScript. No build
step, no npm, no front-end framework.

---

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
source .venv/bin/activate        # macOS / Linux

pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo       # 23 people, 4 teams, offers, sales, disputes
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and pick a person. **There are no passwords** —
choosing a persona signs you in. That is deliberate for a demo, and it is the
first thing to replace before this goes anywhere real.

Settings are read from the environment; copy `.env.example` to `.env` to change
any of them. Every one has a working default.

## The three roles

The portal is not one screen with things hidden — each role gets its own
navigation, its own home page and its own permissions, enforced server-side.

| | Field agent | Team lead | Manager |
|---|---|---|---|
| Sign in as | `jliu` | `jmitchell` | `gchen` |
| Sees | own sales, incentives, XP | their squad | every team they own |
| Can | log sales, raise disputes | approve sales, draft plans, simulate | approve plans, set budgets, close the month |

Role checks live in `role_required` and in each model's `can_be_decided_by`.
Scope always comes from the signed-in person, never from the URL — asking for
another team's data returns a 403, not their data.

## What is in it

**Agent.** Log a sale and watch the payout calculate as you type. Daily quests,
XP, levels, streaks, a tier ladder and a once-a-day dice roll worth 10 XP per
pip. Disputes with a full decision trail.

**Team lead.** An approval queue for their squad's sales, market trends by
region, an incentive plan builder with versioning, and a simulator that models
two plans side by side against what the team already sells.

**Manager.** Budgets and spend, payout exceptions, a three-step month-end close
that refuses to calculate while exceptions are open and locks the period once
payroll has it. Five reports, each downloadable as CSV or PDF.

**Throughout.** An assistant that answers questions about your own records, a
character that reacts to the state of the page, and a command palette.

## Layout

```
agentportal/        settings, root urls
portal/
  models.py         36 models: people, offers, sales, plans, close, budgets
  views*.py         one module per area; every view is a function
  simulation.py     plan cost modelling — pure functions, no DB writes
  pdf.py            report rendering
  assistant.py      the rules-based question matcher
  templates/
  management/commands/seed_demo.py
static/css/         one sheet per concern, loaded in order
static/js/          progressive enhancement only; every page works without it
tools/              Playwright scripts used to audit the UI
```

## Tests

```bash
python manage.py test portal        # 256 tests
```

They cover permissions per role, the approval and close workflows, the
simulation arithmetic, PDF generation, and a set of regression guards for
mistakes that have actually happened here — a stylesheet linked but missing, a
multi-line `{# #}` comment printing into the page, colours drifting off the
Spectrum palette.

## The assistant

With `ANTHROPIC_API_KEY` set, questions are answered by Claude with the
person's own records as context. Without it — the default — the assistant falls
back to matching against the database and still answers, less fluently.

## Notes and limits

This is a proof of concept, and a few things are demo-shaped on purpose:

- **No authentication.** Picking a persona logs you in.
- **`DEBUG=1` by default**, and the bundled secret key is a placeholder.
- **Seeded data.** `seed_demo` is idempotent; re-run it to reset.
- **Fonts.** Spectrum's own typefaces are proprietary and are not bundled.
  Montserrat and Hanken Grotesk stand in for them.
