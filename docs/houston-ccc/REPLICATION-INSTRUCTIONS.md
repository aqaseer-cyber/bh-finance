# HOUSTON CCC — Contractor In-House Contract Control System — Build Instructions (v2)

Source: Perplexity thread export "This is just a basic BOQ, I want a comprehensive…" (41 pages), plus v2 scope change.
Purpose: rebuild HOUSTON CCC as an **in-house main-contractor system** for Bahrain, with the lessons from v1 applied.

**What changed from v1 → v2**

| Area | v1 | v2 |
|---|---|---|
| Users | Contractor, consultant and employer perspectives; external stakeholder logins | **In-house only**: PM, QS, Tender & Estimation, Procurement, Contracts Manager (admin), Management |
| Contract forms | FIDIC, JCT and a generic "Ministry of Housing" | **Bahrain library**: MoW 2009 standard forms, Tender Board law, entity-specific (EWA, MoHUP, Bapco Energies group, etc.), FIDIC 1999/2017/MDB, subcontract forms |
| Finance | A vague "accounting API" | **Oracle ERP**: the ERP is the system of record for money, and four integration options are given in Section 7 |
| Hosting/auth | Public pplx.app link and a pilot password | Internal SSO (Microsoft Entra ID or Oracle IDCS). No public URL |
| Dropped | — | Telegram, a full HRMS build, client-facing videos, the multi-perspective toggle |

---

## 0. Read first

1. **Ask which Oracle you run before anything else.** [Certain] Oracle Fusion Cloud ERP, E-Business Suite R12, JD Edwards and NetSuite each integrate completely differently. The integration design in Section 7 forks on this one answer.
2. **I could not retrieve the Bahrain contract texts.** [Certain] works.gov.bh and the legal databases are blocked from this environment. Section 5 lists the forms with confidence tags, but **clause numbers and notice periods must be loaded from the contract PDFs you supply.** The build must never ship with clause periods typed from memory, whether mine or the build agent's.
3. **Do a build-vs-buy check before Phase 0.** [Likely] If the company already pays for Oracle Fusion, *Oracle Primavera Unifier / Aconex* cover maybe 60–70% of this scope natively and integrate with Fusion out of the box. A custom build is justified by three things: Bahrain-specific forms and Arabic correspondence, the tender-to-contract margin bridge, and licence cost. Write that justification down; if you can't, buy instead.
4. **v1 lessons still apply** (Section 1). The biggest ones: no spec, no real data, and login and hosting firefighting.

---

## 1. Lessons from v1 (carried forward)

| # | Rule |
|---|---|
| L1 | Freeze a one-page spec (Section 4) before building. One product, no perspective pivots |
| L2 | SSO from Phase 0 (Entra ID / Oracle IDCS). No shared, demo or passwordless logins. Never put a credential in chat |
| L3 | Host on the internal network or a private cloud tenant behind SSO. No static-only deploys and no sandbox ports |
| L4 | Postgres (or Oracle DB / Autonomous DB if IT prefers) with migrations and backups. No SQLite outside local development |
| L5 | Native parsers from the first build: xlsx/xlsm (SheetJS), P6 .xer/.xml, MS Project .xml |
| L6 | The workbook uses Excel Tables with structured references. No fixed 40-row ranges |
| L7 | Imports run dry-run → diff → commit → rollback. A bad file must change nothing |
| L8 | A server-side scheduler generates due reports and stores revisions |
| L9 | Every module is reachable on desktop and mobile. Each role gets a Playwright screenshot |
| L10 | Demo data must reconcile. A test asserts that the cockpit equals the register roll-ups |
| L11 | One EV source of truth. A second source only appears as a reconciliation variance |
| L12 | The app never invents legal periods. Clause data comes only from the loaded contract |
| L13 | Evidence links store a file hash and signed/dated metadata. "Reference only" and "verified" are shown separately |
| L14 | Sheet names use a code; the full title goes in B2 |
| L15 | The agent works autonomously within a phase and reports only at the gate |

---

## 2. Users and what each one needs (in-house)

| Role | Primary jobs in HOUSTON CCC | Edits | Sees |
|---|---|---|---|
| **Contracts Manager (Admin / owner)** | Contract setup, clause library, notices and claims, variations, DoA, user admin | Everything contractual. Owns the Owner Sheet | All projects |
| **Project Manager** | Progress, programme, delay events, site diary, weekly/monthly reports, subcontractor coordination | Progress, diary, delay events, report narrative | Own projects. Cost at summary level only |
| **Quantity Surveyor** | Measurement, IPC/payment applications, variation pricing, subcontract valuations, final account | BOQ quantities, valuations, VO pricing | Own projects, full cost |
| **Tender & Estimation** | Tender register, BOQ pricing import, tender risk/query log, go/no-go, handover pack to the project team | Pre-contract records | Pre-contract records plus read-only post-contract actuals for completed jobs (feedback loop) |
| **Procurement** | Subcontract and supply packages, RFQ comparison, PO commitments, supplier performance | Packages, commitments (read-only from Oracle once integrated) | Packages across projects |
| **Management (MD/GM/CEO)** | Portfolio health, margin bridge, cash, risk exposure, approvals above DoA limits | Approvals only | All. Read-only dashboards |
| *Planner* (recommended addition) | P6 updates, delay analysis input | Programme imports | Own projects |
| *Document Controller* (recommended addition) | Incoming/outgoing log, classification, transmittals | Doc registers | Own projects |
| *Finance/Accounts* (recommended addition) | Cash receipts, bonds, retention, VAT reconciliation with Oracle | Read-only plus reconciliation flags | All |

---

## 3. Inputs to supply

### ★ Must-have before Phase 1
| Input | Format | Why |
|---|---|---|
| **Oracle product, version and modules** (e.g. Fusion 25D: Projects, Procurement, AP/AR, GL) plus an IT contact | 1 page | Section 7 depends on it |
| **Contract PDFs for 2–3 live projects**, including Particular Conditions, Appendix to Tender / Contract Data | PDF | This is the clause library source. Particular Conditions override the standard form |
| **The standard forms you actually sign** (MoW 2009 set, entity GCCs, FIDIC editions) | PDF | Section 5 can't be verified without them |
| **Real tender BOQ plus the priced estimate** for one won job | xlsx | Seeds the tender → budget → actual margin bridge |
| **P6 programme, cost- and resource-loaded** | .xer | Programme and EV |
| **Delegation of Authority matrix** | xlsx/PDF | Approval routing has to mirror Oracle approvals |
| **Current report templates and letter templates (EN + AR)** | DOCX/PDF | Government correspondence is often in Arabic |
| **Role list with named users** | Table | Access design |

### ◆ Should-have
- Subcontract templates and back-to-back clause positions.
- Bond and insurance register (PB, APG, retention bond, CAR, third-party, workmen's compensation) with expiry dates.
- Oracle cost code / project task structure (WBS ↔ CBS mapping).
- Historical won/lost tender list with margins.

### ✗ Do not supply
- Credentials or API keys in chat. Use the secrets vault.
- Production Oracle access before Phase 4. Use a test instance or exported extracts first.

---

## 4. Spec sheet (one page, frozen before Phase 0)

```
Product:                 HOUSTON CCC — in-house contract control
Owner/admin:             Contracts Manager — {name}
Users:                   PM, QS, Tender & Estimation, Procurement, Management (+ Planner, DocCon, Finance?)
Oracle:                  {Fusion Cloud | EBS R12.x | JDE | NetSuite} — modules {…}
Identity:                {Entra ID | Oracle IDCS}
Hosting:                 {on-prem | Azure | OCI} — internal only
Languages:               English + Arabic (letters/RTL)   Currency: BHD (+ multi-currency?)   VAT: 10%
Contract forms enabled:  (tick from Section 5)
Pilot projects:          {2–3 names, client entity, form, value}
Out of scope this round: {…}
```

---

## 5. Bahrain contract-form library

> Every row becomes a **form profile** in the app: clause map, notice/time-bar table, payment cycle, retention, bonds, LDs, defects period, dispute route, letter templates.
> **All periods are BLANK until loaded from the supplied PDF.** Confidence tags describe what the form *is*, not its clause content.

### 5a. Government — Bahrain
| # | Form / regime | Used by | Confidence | Notes for the build |
|---|---|---|---|---|
| G1 | **MoW Standard Contract Agreement & Conditions of Contract (2009): Part 1, Building & Engineering Works** | Ministry of Works; adopted by many ministries for public construction | [Certain] it exists and was launched 9 Nov 2009. It is mandatory for government-entity projects | Core profile. [Likely] FIDIC-derived structure; confirm the clause numbering against the PDF |
| G2 | MoW 2009 Part 4: **Minor Works, Supply of Materials/Equipment, Supply of Human Resources, Maintenance & Repair** | MoW and other ministries, small works and maintenance | [Certain] part of the set | A separate light profile, often lump-sum or schedule-of-rates |
| G3 | MoW 2009 Parts 2 & 3: Engineering / QS Consultancy Services | When the contractor is design-build, or in a JV with a consultant | [Certain] part of the set | Low priority. Only for D&B subconsultant flow-down |
| G4 | **Tender Board regime**: Legislative Decree 36/2002 (Government Tenders, Bids, Purchases & Sales) and its Implementing Regulations (Decree 37/2002), as amended | All ministries, authorities and wholly government-owned companies | [Certain] | A pre-contract overlay, not a contract form. Drives the initial bond (≈1% of tender value, min BD 100 [Likely], per recent notices), PQ grade, e-tendering ID, award/appeal steps |
| G5 | **Ministry of Housing & Urban Planning** housing projects | MoHUP | [Likely] MoW 2009 conditions for conventional builds; developer/PPP agreements for the newer social-housing programmes | Two profiles: "MoW-based" and "Developer/PPP", the latter mostly via a developer as your client |
| G6 | **Electricity & Water Authority (EWA)** | EWA networks, substations, distribution, water works | [Likely] tendered through the Tender Board with EWA's own GCC/Special Conditions (often FIDIC-based); IWPP/IPP plants run as BOO concessions | For a building contractor, EWA mostly appears as (a) direct network/civil contracts and (b) **authority approvals and stub-outs on your projects**. Model both |
| G7 | Ministry of Works: Roads & Sewerage | MoW roads, sanitary engineering | [Certain] uses the MoW framework; [Certain] PQ grade AA/A required for major sewerage | Same profile as G1, plus a utilities diversion/permit register |
| G8 | Ministry of Municipalities Affairs & Agriculture / Governorates | Municipal works | [Guessing] MoW-based conditions | Confirm with a sample contract |
| G9 | **Government-owned companies**: Bapco Energies group (Bapco Refining, Tatweer, Banagas, etc.), Alba, GPIC, Bahrain Airport Company, Gulf Air group, BAC | Bespoke corporate T&Cs, frequently FIDIC Red/Yellow/Silver with heavy amendments | [Likely] | One profile per client, built from the actual contract. Oil & gas EPC terms (Silver-like) carry very different risk |
| G10 | **Fund-financed projects**: GCC Development Programme (Saudi Fund, Kuwait Fund, Abu Dhabi Fund, Qatar Fund), IsDB, Arab Fund | Large infrastructure, housing, airport, hospitals | [Likely] FIDIC MDB Harmonised Edition (Pink Book) or Red 1999/2017 plus fund procurement rules | Adds fund no-objection steps and fund-specific payment routing. These steps often cause payment delays, so track them |

### 5b. International / private
| # | Form | Confidence | Notes |
|---|---|---|---|
| F1 | FIDIC Red 1999 / 2017 (Employer-designed) | [Certain] widely used in Bahrain | 1999: 28-day notice (SC 20.1). 2017: notice plus fully detailed claim within 84 days. **Load from the PDF anyway** |
| F2 | FIDIC Yellow 1999 / 2017 (Plant & Design-Build) | [Certain] | Adds design submittals and the fitness-for-purpose risk register |
| F3 | FIDIC Silver 1999 / 2017 (EPC/Turnkey) | [Certain] | Oil & gas and utilities. Fewer contractor entitlement routes |
| F4 | FIDIC Short Form (Green) | [Likely] occasional use | Light profile |
| F5 | FIDIC Subcontract 2011 (for Red 1999) / 2019 (for 2017 forms) | [Certain] they exist | **Critical for back-to-back flow-down** (Section 8) |
| F6 | JCT / NEC | [Likely] rare in Bahrain | Configurable, not seeded |
| F7 | Bespoke private developer contracts | [Certain] common | Built from the PDF |

### 5c. Bahrain law overlay (applies to every profile)
| Item | Confidence | Build implication |
|---|---|---|
| Civil Code (Muqawala) Arts. 615–620: joint liability of contractor and engineer for collapse/structural defects; public policy, cannot be excluded | [Certain] the articles exist and cannot be excluded. [Conflicting sources] on the period: commonly cited as 10 years, but some commentators say Bahrain's article specifies 5 | Post-handover liability register with an expiry date **entered by legal**, not defaulted |
| VAT 10% | [Certain] | VAT on IPCs and on subcontractor and supplier invoices. Reconcile with Oracle tax |
| Labour Law (Law 36/2012), LMRA work permits, WPS salary transfers | [Likely] | Manpower cost comes from Oracle HCM/payroll. The app keeps only allocation |
| Disputes: BCDR (Bahrain Chamber for Dispute Resolution), the courts, or the contract's DAB/DAAB | [Likely] | Dispute route field per profile, plus escalation timelines |
| Arabic-language governing text in some government contracts | [Likely] | Letters in AR/EN. Record which text prevails |

---

## 6. Modules (contractor, in-house)

| Code | Module | Main users | Notes |
|---|---|---|---|
| A | **Contract Setup & Owner Sheet**: project, client entity, form profile (Section 5), Particular Conditions overrides, key dates, bonds, insurances | Contracts Manager | One wizard per project. Locks once approved |
| B | **Obligations & Time-Bar Register**: every notice, submittal, insurance, bond and reporting obligation extracted from the contract, each with a clock | CM, PM | AI-assisted extraction from the PDF, **human-verified** before activation |
| C | **Tender & Estimation**: tender register (Tender Board ID), go/no-go, query log, BOQ import, priced estimate, risk/opportunity, tender margin, win/loss | T&E | Do **not** build an estimating engine. Import from CostX/Candy/Excel |
| D | **Tender → Contract Handover**: frozen tender budget → contract budget → Oracle project budget | T&E → QS → Finance | This is where margin leakage starts |
| E | **Document Control**: incoming/outgoing with ID `{proj}-{party}-{type}-{seq}`, classified as Instruction / RFI / Drawing (IFC, rev) / Letter / Notice / Minutes | DocCon, PM | Ingest from Outlook/Exchange. AI suggests classification and flags possible notice triggers |
| F | **Notices, Claims & EOT**: trigger → clock → notice draft (form-specific, AR/EN) → particulars → contemporaneous records → claim valuation → status | CM, QS, PM | Linked to delay events in P6 |
| G | **Variations**: instructed → priced → submitted → agreed → certified → paid, with ageing at each stage | QS, CM | The contractor's biggest cash leak. Ageing dashboard is a priority |
| H | **Payments & Cash**: IPC submitted / certified / paid ageing, retention held and release dates, advance recovery, VAT, client payment-delay tracking | QS, Finance | Actuals read from Oracle AR |
| I | **Subcontracts & Procurement**: packages, RFQ comparison, award, back-to-back clause map, sub valuations, sub notices/claims, performance score | Procurement, QS | Commitments read from Oracle PO |
| J | **Programme & Progress**: P6 import, % complete, PV/EV/AC, SPI/CPI, critical float, look-aheads, site diary (mobile, photos) | PM, Planner | The site diary is claims evidence. Make it fast on a phone |
| K | **Cost & Margin**: BOQ-line P&L, forecast to complete, **margin bridge** (tender → contract → current → forecast) | QS, Management | Actuals from Oracle Project Costing |
| L | **Bonds & Insurances**: PB, APG, retention bonds, CAR/TPL/WC policies, expiry alerts, release triggers | CM, Finance | Bank-charge saving by releasing on time |
| M | **Authority Approvals**: building permit, EWA connections/stub-outs, civil defence, municipality, wayleaves | PM | Often the critical path on Bahrain projects |
| N | **Reports**: daily/weekly/monthly internal reports, client monthly report, claims brief, management portfolio report, auto-generated | All | PDF/DOCX/Print with revisions |
| O | **Management Cockpit**: portfolio RAG, margin, cash, unapproved VOs, open notices at risk, bond exposure, approvals inbox | Management | Read-only. Built last, from real data |
| P | **Close-out**: final account, defects period, retention release, decennial/latent-defect register, lessons learned → feeds Tender & Estimation | CM, QS, T&E | Closes the loop |

**Removed from v1:** consultant/employer perspectives; external logins; Telegram (use Outlook/Teams, which are auditable); a full HRMS build (use Oracle HCM data); the asset register and detailed T&C (keep a handover checklist unless you do MEP-heavy work); client-facing videos.

---

## 7. Oracle ERP integration options

**Principle:** Oracle is the system of record for **money** (budgets, commitments, actual costs, invoices, receipts, GL). HOUSTON CCC is the system of record for **contract administration** (notices, claims, variations, progress, documents). Never let both own the same number.

| Option | How | Fits | Pros | Cons | Verdict |
|---|---|---|---|---|---|
| **O1. Scheduled file exchange** | Nightly Oracle BI/OTBI extracts → SFTP → HOUSTON import. Upload back via FBDI (Fusion) or open interface tables (EBS) | Any Oracle | Cheapest and fastest. IT-friendly. No API licence | Up to a day of latency. No real-time | **Phase 4 start: recommended** |
| **O2. Direct REST APIs** | Fusion REST: projects, project costs, budgets, purchase orders, AP invoices, receipts. Read-only first | Fusion Cloud | Near-real-time. Well documented | Needs an integration user and OAuth. API version changes | Phase 5 for live cost and commitments |
| **O3. Oracle Integration Cloud (OIC) middleware** | OIC orchestrates Fusion ↔ HOUSTON flows, retries, monitoring, and later the Primavera/Unifier connectors | Fusion (+ OCI) | Oracle-supported. Pre-built adapters. Audit trail | OIC licence cost. Needs specialist skills | **Best long-term if on Fusion** |
| **O4. EBS-specific** | Integrated SOA Gateway REST/SOAP, or the PA/AP/PO open interface tables | EBS R12 | Uses what you own | Older stack. DBA dependency | The only sensible route if on EBS |
| **O5. Buy instead of build for parts** | Oracle Primavera Unifier (contracts/cost/changes) + Aconex (documents), with native Fusion integration. HOUSTON CCC keeps the Bahrain forms, tender bridge and cockpit | Fusion | Less custom code. Vendor support | Licences. Less tailored. Arabic letters still custom | Evaluate honestly in Phase 0 |

**Data flows, in this order:**
1. Oracle → HOUSTON (read): project/task structure, budgets, PO commitments, AP actuals, AR receipts, GL period close.
2. HOUSTON → Oracle (write, after approval): certified IPC amounts (AR invoice), agreed variations (budget revision), subcontract valuations (AP invoice support).
3. Never write: GL journals, supplier masters, payments.

**Control:** a field sign-off matrix maps each Oracle field to a HOUSTON field, its owner and its refresh rate. Finance approves it before any write-back.

---

## 8. Feedback on the v2 change, and recommended additions and omissions

### Feedback on what you asked for
- **In-house only: correct.** [Certain] It removes v1's biggest risk (public passwordless access) and lets SSO plus internal hosting replace the login saga.
- **Putting Tender & Estimation in the same system: correct, with one limit.** [Likely] The tender-to-contract handover is where contractors lose margin silently, so link them. But don't rebuild estimating software; import the priced BOQ.
- **"All Bahrain ministry forms": the wrong unit.** [Likely] Your contracts are governed by *standard form plus Particular Conditions*, and the Particular Conditions change the time bars. Build the library **per signed contract**, with the standard form as a starting template only. Otherwise the clock fires on the wrong day.
- **The role list is missing three operators.** [Likely] Document Controller, Planner and Finance. Without the Document Controller nobody feeds the notice engine; without Finance nobody reconciles with Oracle. Their work then falls on PMs and QSs, and the data goes stale.
- **"Management progress tracking" needs a definition.** [Likely] Agree the 8–10 KPIs management will act on: margin vs tender, cash position, overdue VOs, notices at risk, SPI, bond exposure, safety. Then build only those. v1 shipped 49 cockpit KPIs.

### Recommended additions (ranked by efficiency gain for contract administration)
1. **Contract digest at award.** AI extracts obligations, notices, LDs, caps, bonds and insurances from the contract PDF into the Obligations Register. A Contracts Manager verifies each row. This replaces days of manual reading per contract.
2. **Variation ageing pipeline** (instructed → paid, days at each stage). Unpriced and uncertified VOs are usually the contractor's largest working-capital drain.
3. **Back-to-back flow-down.** When a client instruction or notice arrives, the app proposes the matching notice to affected subcontractors inside *their* (shorter) time bar.
4. **Outlook/Exchange ingestion into Document Control**, with AI classification and notice-trigger flags. This removes manual logging, the main reason registers go stale.
5. **Mobile site diary with geotagged photos.** These are contemporaneous records, the evidence most claims fail for lack of.
6. **Margin bridge waterfall** (tender → contract → current → forecast), explained by VO, claims, buy-out savings and overruns. It is the single best management view.
7. **Bond & insurance expiry and release tracker.** Releasing bonds on time directly saves bank charges and credit lines.
8. **Authority approvals tracker** (EWA, municipality, civil defence). These are frequently the real critical path in Bahrain.
9. **Bilingual (AR/EN) letter templates** per form profile, generated as drafts for CM review.
10. **Tender win/loss and as-built cost feedback** into estimating, so the next price uses real productivity.

### Recommended omissions
- **Telegram.** It is not auditable for contractual communications. Use Outlook and Teams.
- **A full HRMS/payroll build.** Read manpower cost from Oracle HCM/payroll; keep only site allocation and productivity.
- **The multi-perspective (consultant/employer) toggle.** It doubled v1's complexity for no in-house value.
- **A detailed asset register and T&C module**, unless MEP is core to your work. A handover checklist is enough.
- **Videos and showcase material.** This is an internal tool.
- **JCT/NEC seeding.** Keep them configurable, but don't spend build time on forms you rarely sign.
- **An EV module that recomputes Oracle actuals.** Read actual cost; compute only EV and forecast.

---

## 9. Phase plan with gates

| Phase | Build | Gate (all must be true to pass) |
|---|---|---|
| **0. Decide & found** | Oracle product confirmed, build-vs-buy note, SSO, internal hosting, DB, roles, CI | SSO login works for all roles. 401/403 tests pass. Build-vs-buy signed by management |
| **1. Contract library** | Form profiles G1, G2, F1–F3, F5 from the supplied PDFs; Obligations Register; contract digest | 2 live contracts loaded. Every clock traced to a clause and page. Contracts Manager has signed off the rows |
| **2. Workbook & import** | Master workbook (Tables, Lists, Dictionary); xlsx/xer import with dry-run/diff/rollback | Real BOQ and XER imported. Unmapped-fields list produced. A bad file changes nothing |
| **3. Core administration** | Doc control (with Outlook ingestion), notices/claims, variations, subcontracts, bonds, authority approvals, site diary | A test instruction triggers a notice draft and a sub flow-down. VO ageing is correct on test data |
| **4. Oracle O1 + cost** | Nightly extracts in; margin bridge; payments & cash | HOUSTON totals reconcile with Oracle to 0.00 BHD on the pilot projects |
| **5. Reports & cockpit** | Scheduled reports (PDF/DOCX, AR/EN letters), management cockpit (agreed KPIs only) | Reports generate unattended. Management signs off the KPI list |
| **6. Oracle O2/O3 & write-back** | Live read APIs, approved write-backs (IPC, VO budget revisions) | Field sign-off matrix approved by Finance. Write-back tested on a non-production instance |

Security review runs once per gate.

---

## 10. Master prompt (paste into a new build thread with the Section 3 inputs)

```
ROLE: Lead architect/builder for HOUSTON CCC, an IN-HOUSE contract administration and
control system for a Bahrain main contractor. Users: Contracts Manager (admin/owner), PM,
QS, Tender & Estimation, Procurement, Management (+ Planner, Document Controller, Finance).

SCOPE: build per docs/houston-ccc/REPLICATION-INSTRUCTIONS.md v2, Sections 2, 5, 6, 7 and 9.

NON-NEGOTIABLES:
 1. Internal hosting behind SSO ({Entra ID | Oracle IDCS}). No public URL, no shared passwords,
    no credentials in chat.
 2. Postgres/Oracle DB with migrations and backups. Every record carries project_id + batch_id.
 3. Contract form profiles: clause numbers and periods come ONLY from the uploaded contract
    PDFs (standard form + Particular Conditions). Unknown = BLANK-REQUIRED. Never from memory.
    AI-extracted obligations stay inactive until the Contracts Manager verifies them.
 4. Oracle {product/version} is the system of record for money. Phase 4 = nightly file
    exchange (read). Write-back only in Phase 6 after Finance signs the field matrix.
 5. Workbook: Excel Tables only, code-named sheets, data dictionary → DB table.column.
 6. Imports: native xlsx/xer/xml, dry-run → diff → commit → rollback.
 7. Reports: scheduled, stored with revisions, PDF/DOCX/Print. Letters in Arabic and English.
 8. Numbers reconcile (tests). Inferred values are tagged [Guessing] in the UI.
 9. Work autonomously inside a phase. Stop only at the gate and report against its criteria.

REPORTING STYLE: uncomfortable truth first; [Certain]/[Likely]/[Guessing] tags; list what
was NOT done; files delivered with counts. No "waiting for…" narration.
```

---

## 11. Outputs to demand

**Preferred:** the git repo with commits, the master workbook (0-error recalc), a phase handoff .md (shipped / not done / limits), the form-profile sheets with a clause-and-page trace, the Oracle field sign-off matrix, the reconciliation report against Oracle, Playwright screenshots per role, and a security review per gate.
**Discard:** progress narration, "should I proceed?" inside a phase, seeded numbers presented as results, and files without `REVn` and a date.

---

### Sources consulted (v2)
- MoW Standard Contract Agreement & Conditions of Contract: https://www.works.gov.bh/English/Tenders/Pages/standardcontract.aspx
- MoW standard contract 2009 (supply contracts PDF): https://www.works.gov.bh/English/Publications/standards/Documents/SUPPLY%20CONTRACTS/DO_NOT_UPLOAD/pdf/SUPPLY%20CONTRACTS.pdf
- Tender Board, Decree 37/2002 implementing regulations: https://www.tenderboard.gov.bh/MediaHandler/GenericHandler/Pdf/laws/Tender%20Law%2037%20NewT.pdf
- Legislative Decree 36/2002: https://www.mola.gov.bh/MediaManager/Media/Documents/Laws/Batch3/L3602.pdf
- Bahrain Government Tender Law summary: https://bahrainbusinesslaws.com/laws/Government-Tender-Law
- Tender Board advertisement sample (bond and PQ grade): https://etendering.tenderboard.gov.bh/Tenders/template/TenderAdvertisement1899.pdf
- FIDIC claims and time bars (Gowling WLG): https://gowlingwlg.com/en/insights-resources/articles/2024/fidic-claims-for-time
- Decennial liability (Charles Russell Speechlys): https://www.charlesrussellspeechlys.com/en/insights/expert-insights/construction-engineering-and-projects/2020/decennial-liability-in-the-middle-east-what-is-it-and-does-insurance-cover-it/
- Muqawala in Bahrain (Mondaq): https://admin.mondaq.com/construction-planning/1324884/understanding-the-contract-of-muqawala-in-the-bahrain-construction-industry
- Oracle Project Costing, how project costs are imported: https://docs.oracle.com/en/cloud/saas/project-management/24d/oapjc/how-project-costs-are-imported.html
- Oracle PPM Cloud integration white paper: https://www.oracle.com/ke/a/ocom/docs/applications/erp/erp-fusion-ppm-cloud-integration-wp.pdf
- Unifier and Oracle Primavera Cloud integration: https://docs.oracle.com/cd/F88969_01/English/unifier_general/10300128.htm
