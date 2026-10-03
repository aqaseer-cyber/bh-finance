# HAJ PM-CM-QS / HOUSTON CCC — Replication Instructions (v1)

Source: Perplexity thread export "This is just a basic BOQ, I want a comprehensive…" (41 pages).
Purpose: rebuild the same system in fewer turns, with fewer regressions and more honest outputs.

---

## 0. Read first — what the history actually shows

1. **The thread built three products without a spec.** It went from a HAJ PM-CM-QS consultant app to a Jordan Villa
   project instance to HOUSTON CCC (a main-contractor app). Each pivot reused code, but the master workbook,
   roles and data model were re-planned every time. Most rework traces back to having no frozen spec.
2. **About 40% of the turns were firefighting the login and deployment** (the `__Host-` cookie over HTTP, cookies
   blocked in the in-app browser, a hardcoded password, passwordless mode, the dead port 5003, a static deploy with
   no backend). None of that was product value. Decide on hosting and auth in Phase 0, not in Phase 6.
3. **"Import" meant pasting CSV/TSV for most of the thread.** Native `.xer` and `.xlsx` parsing arrived late, and
   the parse of the real HOUSTON workbook produced 98 rows read and 55 imported, because the workbook is still a
   blank template. **An app is only as real as the data you feed it.** Supply real project data early.
4. **The workbook has structural ceilings.** Registers use fixed ranges on rows 5–44 (40 rows), the time-bar clause
   references are blank placeholders, there are two earned-value sources (20_EV vs 33B P6) that will diverge, and
   the "evidence spine" proves a reference string exists, not that the document is valid.
5. **Security hygiene:** the exported PDF contains a live pilot password in plain text (p.7). Treat it as
   compromised and rotate it. Never paste credentials into a chat you will export.
6. **The export starts mid-thread.** The original BOQ request and the first workbook spec are missing, so the
   instructions below rebuild them from what was delivered.

---

## 1. Lessons converted into rules

| # | What went wrong in the thread | Rule for the rebuild |
|---|---|---|
| L1 | The scope was re-planned on every pivot (consultant → project → contractor) | Write one **spec sheet** (Section 4) before any build. Treat the consultant and contractor sides as *modes* of one product, not as separate apps |
| L2 | Login broke 4 times (`__Host-` cookie on HTTP, in-app browser, password leak, passwordless) | Phase 0 fixes HTTPS hosting and bearer-token plus cookie auth, with per-user passwords from env. No shared or demo passwords, ever |
| L3 | `deploy_website` on `dist/public` gave a shell with no data; the API was pinned to a sandbox port | The backend must be deployed with a managed DB (Supabase/Postgres) from day 1. A static-only deploy is banned |
| L4 | SQLite re-seeded on every fresh deploy, with no backups | Postgres plus migrations plus nightly backup. SQLite only for local dev |
| L5 | CSV paste stood in for real imports | Native parsers are required from first build: SheetJS for xlsx/xlsm, an XER parser for P6, MS Project XML |
| L6 | Workbook registers were capped at 40 rows by fixed SUM/COUNTIF ranges | Use Excel Tables (ListObjects) and structured references only. No fixed ranges |
| L7 | Import was replace-only, with no dry-run, diff or rollback | Every import gets a dry-run, then a diff preview, then a commit, with versioned batches and one-click rollback |
| L8 | Report generation only ran on page load, with no scheduler | A server-side cron generates due reports at period cut-off. Reports are stored with revisions |
| L9 | "Didn't see": the user couldn't find the reports and inputs that had been built | Every module must be reachable from the sidebar **and** the mobile nav, and shown in a QA screenshot per role |
| L10 | Seeded demo numbers were dishonest (negative savings, the 7720% bug, a fictitious 32.4m saving) | Demo data must reconcile across pages. Add a test asserting cockpit KPIs equal register roll-ups |
| L11 | Two EV sources were left unreconciled | One EV source of truth (P6 cost-loaded if available). A second source only appears as a reconciliation variance |
| L12 | Clause and notice periods were blank placeholders | The user supplies the contract form, its clause list and notice periods as input (Section 3). The app never invents legal periods |
| L13 | The evidence spine was only a string match | Each spine link stores a file hash plus signed/dated metadata. Show "reference only" vs "evidence verified" separately |
| L14 | Sheet names were truncated at the 31-character Excel limit | Name sheets with a code (`PC07`) and put the full title in B2 |
| L15 | The agent kept asking "should I proceed?" after every step | Give the agent phase-level authority with acceptance criteria (Section 5). It reports at phase gates, not at every step |

---

## 2. Master prompt (copy-paste into a new thread)

> Replace the `{…}` fields. Attach the inputs from Section 3 **in the same message**.

```
ROLE: You are the lead architect and builder for HOUSTON CCC (Control Command Centre),
a construction project-control system that has ONE master Excel workbook as its input
source and ONE web app as its output/control surface.

OPERATING MODE (toggle at project setup, stored per project):
  - Perspective: {Main Contractor | Consultant PM/CM/QS | Employer}
  - Contract form: {FIDIC Red 1999/2017 | Yellow | Silver | JCT {variant} | Ministry of Housing {country}}
  - Measurement standard: {NRM2 | SMM7 | CESMM4 | POMI | CSI}
  - Currency: {BHD | AED | JOD | SAR}
The contract form drives notice templates, time-bar periods, claim formats and payment cycle.
Clause numbers and notice periods come ONLY from the attached contract clause table.
Never invent or "assume" a legal period. If one is missing, mark it BLANK-REQUIRED.

NON-NEGOTIABLES (learned from the previous build):
 1. Hosting: HTTPS from day 1 on {Vercel + Supabase | Azure + Azure SQL | own domain {x}}.
    No static-only deploy, no sandbox ports, no SQLite in any shared environment.
 2. Auth: per-user accounts, passwords or SSO from env/secrets, server-side role checks on
    every route, bearer + cookie transport, login rate limiting. No shared or demo passwords.
    Never print a credential in chat.
 3. Multi-project from day 1: every record carries project_id + import_batch_id.
 4. Workbook: Excel Tables with structured refs only (no fixed row ranges), a code-named sheet
    with the full title in B2, a data dictionary sheet mapping every column to a DB table.column,
    and dropdowns from a Lists sheet.
 5. Import: native .xlsx/.xlsm (SheetJS), P6 .xer and .xml, MS Project .xml, then
    dry-run → validation report → diff → commit → rollback. Never wipe data on a bad file.
 6. Reports: a server-side scheduler generates due reports at cut-off. Each report is stored
    with a revision, Download (PDF + DOCX), Print, and a source-completeness score.
 7. Numbers must reconcile: one EV source of truth, and automated tests assert the cockpit
    equals the register roll-ups.
 8. Every module is reachable on desktop and mobile, with a Playwright screenshot per role.
 9. Do not fabricate. Inferred values are tagged [Guessing] in the UI and the workbook.

MODULES (build in this order — see phase plan):
 A. Setup & Owner Sheet (Contracts Manager owns it): project, parties, contract mode, toggles
 B. Roles & access: CEO/Owner, Contracts Manager, PM, QS, CM, Planner, Document Controller,
    Procurement, Accounts, HR, each Subcontractor (scoped to own package), Engineer/Employer
    (read-only views when perspective = Contractor)
 C. Pre-contract: tender strategy, PQ, tender issue, queries/addenda, returns, technical
    and commercial evaluation, recommendation, LOI/LOA, contract gate
 D. Document Control: incoming/outgoing register with unique ID {project}-{trade}-{type}-{seq},
    classified under Tender | IFC | Change | Engineer Instruction | RFI | Notice
 E. Notices & Claims engine: each incoming instruction triggers a time-bar clock, a notice
    draft in the contract-form format, a backup/breakdown checklist, a reminder schedule,
    and a claim vs earned-value view
 F. Commercial: rate books per trade, actual cost + markup, BOQ line P&L, target margin,
    subcontractor packages (scope, value, payments, retention, advance recovery, performance)
 G. Programme: P6 resource- and cost-loaded import, WBS↔BOQ↔CBS mapping, PV/EV/AC,
    SPI/CPI, EAC/VAC, critical-float alerts
 H. HRMS & Plant: manpower/plant planned vs actual, cost vs tender allowance, productivity
 I. Reports: daily/weekly/monthly contractor reports, weekly progress agenda, cost report,
    claims brief, CEO health report, subcontractor performance, all auto-generated
 J. Lifecycle close-out: T&C register, asset register/tagging, handover, O&M, as-built
 K. Cockpit: project health (cost, time, value, profit vs target) plus a portfolio view
 L. Integrations (Phase 5 only, design now): accounting/ERP API, HRMS/payroll API,
    Telegram alerts (notifications only, never the system of record)

PHASES: follow docs/houston-ccc/REPLICATION-INSTRUCTIONS.md Section 5. Work autonomously
inside a phase. Stop ONLY at the phase gate and report against its acceptance criteria.

REPORTING STYLE: start with the uncomfortable truth, tag claims [Certain]/[Likely]/[Guessing],
list what was NOT done, and give the files delivered with sizes and counts. No "waiting for…" narration.
```

---

## 3. INPUTS — what to supply (ranked by impact)

### ★ Must-have before Phase 1 (these were missing or late in the thread, and caused most of the rework)

| Input | Format | Why it matters (evidence from the thread) |
|---|---|---|
| **Real BOQ of one live tender/project** | .xlsx as received from the consultant | The import showed 55 clean rows because the workbook was a template. Real data exposes the mapping gaps on day 1 |
| **Real P6 programme, resource- and cost-loaded** | .xer (plus .xml export) | The CSV-paste workaround happened because no real XER was in hand |
| **Contract clause table per form** (clause no., trigger, notice period, recipient, format) | .xlsx | The time-bar matrix was left blank by design. The engine is useless without it |
| **Role list with named people/companies and what each may see/edit** | Table | The roles were re-planned 3 times (6 roles, then 9 roles, plus document controller and subcontractors) |
| **Hosting and auth decision** (domain, SSO provider, DB) | 1 line each | It drove the login and deployment loops |
| **Report templates you actually issue today** (daily/weekly/monthly, agenda, cost report) | PDF/DOCX samples | "Didn't see" reports happened because the agent guessed the layouts |
| **Logo and brand colours** | SVG/PNG plus hex | It was needed later for the video. Use it in the app from the start |

### ◆ Should-have

- Subcontractor list with package scope, value, retention % and advance %.
- Company target margin per project, plus markup rules per trade.
- Sample incoming letters/instructions from the Engineer (to train the notice classifier and format).
- Existing rate books per trade.
- HR roster export (names may be anonymised) and the plant register.
- Accounting/ERP and HRMS product names (for the Phase 5 API design).

### ○ Nice-to-have

- The previous HAJ workbook (26 sheets) and HOUSTON workbook Rev 3/81 sheets, to be used as the **schema reference only**.
- Previous source zip, used as a reference, not as a base to patch (it carries the SQLite and port debt).
- Ethics quote and company narrative (30 years, "Honest Diligent Services") for the presentation phase.

### ✗ Do not supply

- Passwords, API keys or tokens in chat. Put them in the hosting secrets manager.
- Confidential client documents before Phase 0 auth is live. In the thread, Jordan Villa files were briefly public.

---

## 4. Spec sheet to fill before building (one page)

```
Product name:            HOUSTON CCC
Owner (app admin):       Contracts Manager — {name}
Perspectives enabled:    [ ] Contractor  [ ] Consultant  [ ] Employer
Contract forms enabled:  [ ] FIDIC Red [ ] Yellow [ ] Silver [ ] JCT [ ] MoH
First pilot project:     {name, value, currency, start, finish}
Roles (name → scope):    {…}
Reports + due rule:      Daily {time}, Weekly {day}, Monthly {cut-off day}, issue to {roles}
Notice channels:         email | Telegram | in-app
Hosting / DB / SSO:      {…}
Out of scope this round: {…}
```

---

## 5. Phase plan with gates (the agent reports only at these gates)

| Phase | Build | Acceptance criteria (all must be true to pass the gate) |
|---|---|---|
| **0. Foundation** | Repo, HTTPS hosting, Postgres, auth, roles, multi-project skeleton, CI | Login works in Chrome, Safari, mobile and the in-app browser. 401/403 tests pass for every role. Zero secrets in the repo. Backups on |
| **1. Workbook v1** | Master workbook (Tables, Lists, Data Dictionary, Owner sheet, all registers) | 0 formula errors after recalc. Every column is in the dictionary with a DB target. Registers accept 1,000+ rows |
| **2. Import engine** | xlsx/xer/xml parsers, dry-run, diff, commit, rollback, mapping UI | The real BOQ and the real XER import with a written list of unmapped fields. A bad file changes nothing |
| **3. Core modules** | Doc control, notices/claims engine, commercial, subcontractors, programme/EV, HRMS & plant | The cockpit reconciles with registers (automated test). The time-bar clock fires on a test instruction |
| **4. Reports & lifecycle** | Scheduler, all reports with PDF/DOCX/Print, pre-contract, T&C, assets, handover | Reports generate unattended at cut-off. Each role sees only its own reports. Playwright screenshots per role, desktop and mobile |
| **5. Integrations** | ERP/accounting, HRMS/payroll, Telegram (notify only) | The field sign-off matrix is approved before any live connection |
| **6. Showcase** | Video (10 min plus 3 min CEO cut plus 90 s), roadmap HTML/PDF | The voiceover script is approved **before** rendering. Subtitles (.srt) match the VO |

Security review runs **once per phase gate**, not after every patch.

---

## 6. OUTPUTS — what to demand (and what to ignore)

### ★ Preferred outputs (these were the ones that carried value in the thread)

1. **Master workbook .xlsx**: the single source of truth. Report the sheet count, formula count and 0-error recalc.
2. **App source (git repo, not just a zip)** with commit hashes. The zips in the thread drifted from the deployed build.
3. **Permanent HTTPS link** with role logins, plus the visibility setting stated.
4. **Handoff .md per phase** listing what shipped, **what was NOT done**, limitations, and the next step.
5. **QA evidence**: Playwright screenshots per role and viewport, test counts (e.g. "auth 27/27, UI 67/67").
6. **Security review .md** with BLOCK/WARN/PASS per check, at phase gates.
7. **Data dictionary / field sign-off matrix**: workbook column → DB table.column → app screen.
8. **Generated report samples** (PDF + DOCX) from real data, not templates.
9. **"Uncomfortable truth first" summaries.** These were the most useful part of every agent reply (CSV-paste only, blank template, EV divergence, evidence-spine limits).

### ○ Keep, but low priority

- Builder scripts (`build_houston_ccc_*.py`), useful for regenerating the workbook.
- Contact sheets for the video.

### ✗ Discard / do not request

- "Waiting for…", "Running background task" narration.
- Repeated "Should I proceed?" questions inside an approved phase.
- Seeded demo numbers presented as results.
- Duplicate artefacts with unclear versions. Every file name carries `REVn` and a date.

---

## 7. Specialised prompt templates

### 7a. New project instance (as was done for Jordan Villa)
```
Create project {name} in HOUSTON CCC. Attached: {client workbook(s)}, {brief}, {concept report}.
Deliver: (1) client workbook converted into the app format with all original sheets UNALTERED plus
APP_ overlay sheets; (2) XLS-to-app conversion requirements DOCX (mapping table, controlled lists,
integrity rules, import sequence, missing-information register tied to gates, acceptance criteria);
(3) meeting agenda and project brief DOCX opening "{greeting}" covering: {topics}.
Any figure not stated in a source is tagged [Guessing] with a written "not a budget" firewall.
Import into the app under project code {code} and report rows imported/rejected.
```

### 7b. Showcase video
```
Produce a {10-min | 3-min CEO | 90-s WhatsApp} 1080p MP4 for HOUSTON CCC with the logo on every scene.
Step 1: send the VO script plus a scene list for approval (do not render yet).
Structure: organisation (30 yrs, "Honest Diligent Services") → PM/CM/QS integration concept →
stakeholders → admin walkthrough of each module → per-role login and what each role sees →
USP → ethics closing quote.
Step 2 after approval: render with professional VO, burned-in subtitles plus .srt, and a contact sheet.
Use real app screen captures from the live link, not mock-ups.
```

### 7c. Enterprise integration roadmap
```
Produce an interactive toggle-style HTML plus PDF explaining: workbook → import engine → DB →
app; multi-project portfolio; ERP/accounting API; HRMS/payroll; Telegram alerts (notify-only);
governance; build sequence from current state to production. State plainly what exists today
vs what is planned.
```

---

## 8. Agent behaviour settings (paste with the master prompt)

- Work through a whole phase without asking. Ask only when an input from Section 3 is missing, and name it.
- Lead each report with the biggest limitation. Tag every claim [Certain]/[Likely]/[Guessing].
- Never mark something "verified" unless it was executed, and quote the command and result.
- Never auto-publish publicly or change the access barrier without explicit approval.
- When a fix changes behaviour the user didn't ask for, list it under "changed on my own judgement" with the reason.
