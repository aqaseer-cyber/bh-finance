# Legal Contract ACG — Word add-in

A Microsoft Word add-in (VBA global template with its own ribbon tab) that
reformats a contract draft, in place and as a single Undo step, to the
**Legal Contract ACG** layout extracted from `Format for AGREEMENT.docx`.
Formats are data files, so new layouts can be added later without touching
the code.

```
LegalContractACG/
├── src/                 VBA sources (imported into the .dotm by the build)
│   ├── clsProfile.cls   reads a format profile (.ini) with typed lookups
│   ├── modCommon.bas    constants, paragraph kinds, folder discovery, helpers
│   ├── modClassify.bas  decides what each paragraph is (title, article, clause ...)
│   ├── modEngine.bas    builds styles/numbering/page setup and applies them
│   └── modRibbon.bas    ribbon callbacks
├── ribbon/customUI14.xml   the "Legal Contract ACG" ribbon tab
├── Formats/
│   ├── LegalContractACG.ini   the format shipped with the add-in
│   └── _TEMPLATE.ini          every key documented; copy it to make a new format
├── installer/
│   ├── Build-AddIn.ps1    Windows: build the .dotm and install it (one command)
│   └── inject-ribbon.sh   Mac/Linux: add the ribbon to a .dotm saved from the VBA editor
├── docs/INSTALL-MAC.md
└── test/
    ├── sample-draft.docx      messy draft (Calibri, typed numbers, no styles) to try it on
    ├── make_sample_draft.py   regenerates the draft
    └── reference/             the source document and renders of its pages 1 and 7
```

## What it does

Click **Legal Contract ACG** on the new ribbon tab. The add-in:

1. Sets A4, 1 inch margins, header/footer distance.
2. Creates (or refreshes) a family of named styles, prefixed `ACG` — `ACG Body`,
   `ACG Title`, `ACG Article`, `ACG Clause`, `ACG SubClause`, `ACG Recital`,
   `ACG Signature`, `ACG Schedule Heading`, `ACG Table Heading`, `ACG Table Text`,
   and a few more — all Times New Roman 12, justified, 1.15 line spacing.
3. Builds one multilevel list (`1.` / `1.1.` / `a)`) and links it to the
   Article, Clause and Sub-clause styles, so numbering is automatic and
   restarts correctly.
4. Walks every paragraph, decides what it is, strips typed numbers such as
   `1.1` or `(a)`, applies the style, flattens stray font/size/colour
   formatting (bold and italic the author applied are kept), and bolds the
   lead-in phrase of each clause (`**Engagement.** The Client engages…`), the
   party name in each recital and the `Name:` / `Title:` labels in the
   signature block.
5. Formats every table: 0.5 pt borders, shaded and repeated header row,
   cell padding.
6. Replaces the footer with a centred `Page X of Y` in 9 pt.
7. Shows a summary of what it classified. Ctrl+Z reverts everything.

Headings use outline levels, so the Navigation pane and a Table of Contents
work on the result.

### How paragraphs are recognised

Evidence is used in this order; the first match wins.

| Evidence | Result |
|---|---|
| Existing style `Heading 1` / `Heading 2` / `Heading 3` / `Title` / an `ACG …` style | Article / Clause / Sub-clause / Title / same kind (safe to re-run) |
| Existing Word numbering | ALL CAPS → Article; lettered → Sub-clause; `1.1` or level 1 → Clause |
| First paragraph of the document | Title; a short following line → Subtitle |
| Line starts with SCHEDULE / ANNEX / APPENDIX / EXHIBIT | Schedule heading (new page, centred) |
| Typed `1.` + ALL CAPS, or `ARTICLE 3` | Article (number stripped) |
| Typed `1.1`, `2.3.` | Clause (number stripped); `1.1.1` → Sub-clause |
| Typed `(a)`, `a)`, `(i)`, `iv)` | Sub-clause (prefix stripped) |
| Typed `(1)` or `(A)` before the first article | Party recital (prefix kept, name bolded) |
| Starts with `Name:`, `Title:`, `Signature:`, `Date:`, `For the` … | Signature line |
| Short ALL CAPS line | Article; `SIGNATURES` / `IN WITNESS` switch to signature mode; `BACKGROUND` / `WHEREAS` before the first article stay unnumbered |
| Short, fully bold line | Article |
| Indented, unnumbered paragraph | Quote (indented body) |
| Anything else | Body (or Signature line inside the signature block) |

No heuristic survives every draft. When a paragraph lands in the wrong kind,
put the cursor in it (or select several) and use **Mark Paragraph As** on the
ribbon. That applies the same pipeline to just those paragraphs and is also
one Undo step.

### Known limits

- Cross-references typed as text (`Clause 3.1`) are **not** renumbered. Check
  them after the numbering settles.
- Numbering levels deeper than three (`1.1.1.1`) fall back to Sub-clause.
- Article numbering continues into a Schedule. If a schedule has its own
  `1.` / `2.` articles, right-click the first one → *Restart at 1* after
  formatting.
- A short line such as `1) The Consultant shall deliver the report` with no
  full stop is read as an article heading. Mark it as Clause if that is wrong.
- The VBA has been desk-checked but not executed in this environment. Run it
  on `test/sample-draft.docx` before using it on a live contract and report
  anything that misbehaves.
- Bullets on body paragraphs are kept but not restyled.
- Fields other than a TOC are treated as ordinary text.
- Word Online cannot run VBA. Desktop Word 2016 or later on Windows or Mac.

## Install — Windows

One-time preparation, needed only while building:

1. Word → **File → Options → Trust Center → Trust Center Settings → Macro
   Settings** → tick **Trust access to the VBA project object model** → OK.
2. Close every Word window.

Then, in PowerShell, from this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\Build-AddIn.ps1 -Install
```

The script starts Word invisibly, imports `src\*`, saves
`installer\out\LegalContractACG.dotm`, injects the ribbon, and copies:

| What | Where |
|---|---|
| `LegalContractACG.dotm` | `%APPDATA%\Microsoft\Word\STARTUP\` |
| shipped formats | `%APPDATA%\Microsoft\Word\STARTUP\LegalContractACG\Formats\` |
| your own formats (empty at first) | `%APPDATA%\LegalContractACG\Formats\` |

Untick the VBA-project trust option again if you prefer. Start Word: the
**Legal Contract ACG** tab sits after Home.

### Macro security

Word's user STARTUP folder is one of its default Trusted Locations, so the
add-in normally loads without a prompt. If your Word shows a security banner
or the tab does not appear:

- **File → Options → Trust Center → Trust Center Settings → Trusted Locations**
  → check that `%APPDATA%\Microsoft\Word\STARTUP` is listed; add it if not.
- If **Macro Settings** is set to *Disable all macros without notification*
  by group policy, VBA add-ins cannot run at all. Ask IT to allow this one
  location, or to sign the template with the company certificate
  (`selfcert.exe` works for a single machine).
- **File → Options → Add-ins → Manage: Word Add-ins → Go** shows whether
  `LegalContractACG.dotm` is loaded and ticked.

### Manual install (no PowerShell)

1. Open Word, press Alt+F11, **File → Import File…** and import the five files
   in `src\` one by one.
2. Back in Word, **File → Save As** → type *Word Macro-Enabled Template
   (.dotm)* → name `LegalContractACG.dotm`.
3. Run `installer\inject-ribbon.sh` on it (Git Bash works), or add
   `customUI/customUI14.xml` with the Office Custom UI Editor.
4. Copy the `.dotm` to `%APPDATA%\Microsoft\Word\STARTUP\` and the `Formats`
   folder to `%APPDATA%\Microsoft\Word\STARTUP\LegalContractACG\Formats\`.

## Install — Mac

See [docs/INSTALL-MAC.md](docs/INSTALL-MAC.md). Same VBA, imported through
the VBA editor, ribbon injected with `installer/inject-ribbon.sh`, template copied
to Word's startup folder.

## Using it

1. Open the draft. Turn Track Changes off (the add-in offers to).
2. **Legal Contract ACG tab → Legal Contract ACG**. Read the summary.
3. Scroll through. Fix any misclassified paragraph with **Mark Paragraph As**.
4. Check typed cross-references against the new numbering.
5. Save. The profile used is remembered in the document, so **Mark Paragraph
   As** keeps using it later.

**Other Formats** lists every profile found in the two formats folders.
**Refresh** re-reads the folders. **Formats Folder** opens the per-user
folder. **About** shows versions and paths.

Try it on `test/sample-draft.docx` first and compare with
`test/reference/reference-page-1.jpg`.

## Adding a new format

1. Copy `Formats/_TEMPLATE.ini` to `%APPDATA%\LegalContractACG\Formats\MyFormat.ini`
   (Mac: `~/Library/Application Support/LegalContractACG/Formats/`).
2. Set `[Format] Name` and a distinct `StylePrefix` (styles of two formats
   can then coexist in one document).
3. Change the keys you need. Lengths take `pt`, `in`, `cm`, `mm`; colours take
   hex. Every style section inherits from `[Body]`.
4. Ribbon → **Refresh**. The format appears under **Other Formats**.

A file in the per-user folder with the same name as a shipped file overrides
it, so a corrected `LegalContractACG.ini` can be dropped there without
reinstalling. Files whose name starts with `_` are hidden from the menu.

Behaviour that is logic rather than data (a new paragraph kind, a different
lead-in rule) is a code change: add the kind to `modCommon.bas`, its
detection to `modClassify.bas`, and rebuild.

## Versioning

`APP_VERSION` in `modCommon.bas` is the add-in version; `[Format] Version`
in each `.ini` is the format version. Both show under **About**.
