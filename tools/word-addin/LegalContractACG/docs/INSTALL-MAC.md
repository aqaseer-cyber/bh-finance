# Install on Word for Mac (2016 / 2019 / 2021 / Microsoft 365)

The add-in is pure VBA and uses no Windows-only objects (no `Scripting.*`,
no `VBScript.RegExp`), so the same sources run on Mac. There is no COM on
Mac, so the template is assembled by hand once.

## 1. Build the template

1. Open Word, create a blank document.
2. **Tools → Macro → Visual Basic Editor**.
3. In the Project pane select the new document's project, then
   **File → Import File…** and import, one at a time:
   `src/clsProfile.cls`, `src/modCommon.bas`, `src/modClassify.bas`,
   `src/modEngine.bas`, `src/modRibbon.bas`.
4. **Debug → Compile Project**. It must compile with no error.
5. Close the editor. **File → Save As…**, format **Word Macro-Enabled
   Template (.dotm)**, name `LegalContractACG.dotm`, save to your Desktop.
6. Close the document.

## 2. Add the ribbon tab

In Terminal, from the add-in folder:

```bash
./build/inject-ribbon.sh ~/Desktop/LegalContractACG.dotm
```

Needs `unzip`, `zip` and `python3`, which macOS ships.

## 3. Install

Word for Mac loads global templates from:

```
~/Library/Group Containers/UBF8T346G9.Office/User Content/Startup/Word/
```

Copy the template there, and the formats beside it:

```bash
S="$HOME/Library/Group Containers/UBF8T346G9.Office/User Content/Startup/Word"
mkdir -p "$S/LegalContractACG/Formats"
cp ~/Desktop/LegalContractACG.dotm "$S/"
cp Formats/*.ini "$S/LegalContractACG/Formats/"
mkdir -p "$HOME/Library/Application Support/LegalContractACG/Formats"
```

Restart Word. If the tab does not appear, check **Word → Preferences →
Security → Macro Security**: *Disable all macros with notification* or
better is needed, and **Tools → Templates and Add-ins** must list
`LegalContractACG.dotm` as loaded.

## Updating

Repeat step 1 after any change to `src/`, re-inject the ribbon, overwrite the
template in the startup folder while Word is closed. Formats update by
copying the `.ini` file only.
