Attribute VB_Name = "modEngine"
Option Explicit

' ============================================================================
' modEngine - builds styles / numbering / page setup from a profile and
' applies them to the active document, in place, as one Undo step.
' ============================================================================

Private Type ApplyStats
    Counts(0 To 12) As Long
    Tables As Long
    Stripped As Long
End Type

' ---------------------------------------------------------------------------
' Entry point used by the ribbon
' ---------------------------------------------------------------------------
Public Sub ApplyProfileToActiveDocument(ByVal profilePath As String)
    Dim doc As Document, prof As clsProfile, st As ApplyStats
    Dim undoStarted As Boolean, msg As String

    If Documents.Count = 0 Then
        MsgBox "Open the document you want to format first.", vbExclamation, APP_NAME
        Exit Sub
    End If
    Set doc = ActiveDocument
    If doc.ProtectionType <> wdNoProtection Then
        MsgBox "This document is protected. Remove the protection and try again.", vbExclamation, APP_NAME
        Exit Sub
    End If
    If doc.TrackRevisions Then
        If MsgBox("Track Changes is on. Formatting with Track Changes on creates hundreds of formatting revisions." & vbCrLf & vbCrLf & _
                  "Turn Track Changes off for this operation?", vbYesNo + vbQuestion, APP_NAME) = vbYes Then
            doc.TrackRevisions = False
        End If
    End If

    Set prof = LoadProfile(profilePath)
    If prof Is Nothing Then
        MsgBox "Could not read the format profile:" & vbCrLf & profilePath, vbCritical, APP_NAME
        Exit Sub
    End If

    On Error GoTo Fail
    undoStarted = BeginUndo("Apply " & prof.Name)
    Application.ScreenUpdating = False

    SetupPage doc, prof
    BuildStyles doc, prof
    BuildNumbering doc, prof
    ClassifyAndApply doc, prof, st
    FormatTables doc, prof, st
    SetupHeadersFooters doc, prof
    SetDocVar doc, DOCVAR_PROFILE, prof.Path
    SetDocVar doc, DOCVAR_PROFILE_NAME, prof.Name

    Application.ScreenUpdating = True
    If undoStarted Then EndUndo
    msg = SummaryText(prof, st)
    If prof.GetBool("Options", "ShowSummary", True) Then MsgBox msg, vbInformation, APP_NAME
    Exit Sub
Fail:
    msg = Err.Description
    Application.ScreenUpdating = True
    If undoStarted Then EndUndo
    MsgBox "Formatting stopped with an error:" & vbCrLf & msg & vbCrLf & vbCrLf & _
           "Use Undo (Ctrl+Z) to revert the partial change.", vbCritical, APP_NAME
End Sub

' Re-classify just the selected paragraphs as one kind (ribbon "Mark as ...").
Public Sub MarkSelectionAs(ByVal k As ParaKind)
    Dim doc As Document, prof As clsProfile, para As Paragraph, undoStarted As Boolean
    Dim px As PrefixInfo, raw As String
    If Documents.Count = 0 Then Exit Sub
    Set doc = ActiveDocument
    Set prof = LoadProfile(ActiveProfilePath(doc))
    If prof Is Nothing Then
        MsgBox "No format profile is available. Check the Formats folder.", vbExclamation, APP_NAME
        Exit Sub
    End If
    On Error GoTo Fail
    undoStarted = BeginUndo("Mark as " & KindLabel(k))
    Application.ScreenUpdating = False
    If Not StylesPresent(doc, prof) Then
        BuildStyles doc, prof
        BuildNumbering doc, prof
    End If
    For Each para In Selection.Paragraphs
        If para.Range.Information(wdWithInTable) And k <> pkTableHeading And k <> pkTableText Then
            ' allow body/other styles inside tables but skip number stripping
            ApplyKindToParagraph doc, para, k, prof, False, 0
        Else
            raw = ParaText(para)
            px = ParsePrefix(raw)
            If KindIsNumbered(k) And px.Kind <> pxNone Then
                ApplyKindToParagraph doc, para, k, prof, True, px.Length
            Else
                ApplyKindToParagraph doc, para, k, prof, False, 0
            End If
        End If
    Next
    Application.ScreenUpdating = True
    If undoStarted Then EndUndo
    Exit Sub
Fail:
    Dim errMsg As String
    errMsg = Err.Description
    Application.ScreenUpdating = True
    If undoStarted Then EndUndo
    MsgBox "Could not mark the selection: " & errMsg, vbCritical, APP_NAME
End Sub

' ---------------------------------------------------------------------------
' Undo wrapper (Word 2010+; silently ignored on older builds)
' ---------------------------------------------------------------------------
Private Function BeginUndo(ByVal label As String) As Boolean
    On Error Resume Next
    Application.UndoRecord.StartCustomRecord label
    BeginUndo = (Err.Number = 0)
    On Error GoTo 0
End Function

Private Sub EndUndo()
    On Error Resume Next
    Application.UndoRecord.EndCustomRecord
    On Error GoTo 0
End Sub

' ---------------------------------------------------------------------------
' Page setup
' ---------------------------------------------------------------------------
Private Sub SetupPage(ByVal doc As Document, ByVal prof As clsProfile)
    Dim sec As Section, paper As String
    If Not prof.GetBool("Page", "Enabled", True) Then Exit Sub
    paper = LCase$(prof.GetStr("Page", "PaperSize", "A4"))
    For Each sec In doc.Sections
        With sec.PageSetup
            On Error Resume Next
            Select Case paper
                Case "a4": .PaperSize = wdPaperA4
                Case "letter": .PaperSize = wdPaperLetter
                Case "legal": .PaperSize = wdPaperLegal
                Case "a3": .PaperSize = wdPaperA3
            End Select
            If LCase$(prof.GetStr("Page", "Orientation", "portrait")) = "landscape" Then
                .Orientation = wdOrientLandscape
            Else
                .Orientation = wdOrientPortrait
            End If
            .TopMargin = prof.GetLen("Page", "MarginTop", 72)
            .BottomMargin = prof.GetLen("Page", "MarginBottom", 72)
            .LeftMargin = prof.GetLen("Page", "MarginLeft", 72)
            .RightMargin = prof.GetLen("Page", "MarginRight", 72)
            .Gutter = prof.GetLen("Page", "Gutter", 0)
            .HeaderDistance = prof.GetLen("Page", "HeaderDistance", 35.4)
            .FooterDistance = prof.GetLen("Page", "FooterDistance", 35.4)
            On Error GoTo 0
        End With
    Next
End Sub

' ---------------------------------------------------------------------------
' Styles
' ---------------------------------------------------------------------------
Private Function StylesPresent(ByVal doc As Document, ByVal prof As clsProfile) As Boolean
    Dim s As Style
    On Error Resume Next
    Set s = doc.Styles(KindStyleName(prof, pkClause))
    StylesPresent = (Err.Number = 0) And Not (s Is Nothing)
    On Error GoTo 0
End Function

Private Function EnsureStyle(ByVal doc As Document, ByVal name As String) As Style
    Dim s As Style
    On Error Resume Next
    Set s = doc.Styles(name)
    On Error GoTo 0
    If s Is Nothing Then Set s = doc.Styles.Add(name, wdStyleTypeParagraph)
    Set EnsureStyle = s
End Function

Public Sub BuildStyles(ByVal doc As Document, ByVal prof As clsProfile)
    Dim k As Long, s As Style, bodyName As String

    ' Optionally pull Normal into line so stray paragraphs still look right.
    If prof.GetBool("Body", "ApplyToNormal", True) Then
        Set s = doc.Styles(wdStyleNormal)
        ApplyStyleProps s, prof, "Body", True
    End If

    bodyName = KindStyleName(prof, pkBody)
    Set s = EnsureStyle(doc, bodyName)
    s.BaseStyle = doc.Styles(wdStyleNormal)
    ApplyStyleProps s, prof, "Body", False

    ' pass 1: make sure every style exists (NextParagraphStyle needs targets)
    For k = 0 To KIND_COUNT - 1
        If k <> pkBody Then EnsureStyle doc, KindStyleName(prof, k)
    Next
    ' pass 2: properties
    For k = 0 To KIND_COUNT - 1
        If k <> pkBody Then
            Set s = doc.Styles(KindStyleName(prof, k))
            On Error Resume Next
            s.BaseStyle = doc.Styles(bodyName)
            On Error GoTo 0
            ApplyStyleProps s, prof, KindSection(k), False
            On Error Resume Next
            s.NextParagraphStyle = doc.Styles(NextStyleFor(prof, k))
            On Error GoTo 0
        End If
    Next

    ' header / footer built-in styles follow the body font
    On Error Resume Next
    With doc.Styles(wdStyleHeader).Font
        .Name = prof.StyleStr("Header", "Font", prof.StyleStr("Body", "Font", "Times New Roman"))
        .Size = prof.StyleNum("Header", "Size", 9)
    End With
    With doc.Styles(wdStyleFooter).Font
        .Name = prof.StyleStr("Footer", "Font", prof.StyleStr("Body", "Font", "Times New Roman"))
        .Size = prof.StyleNum("Footer", "Size", 9)
    End With
    On Error GoTo 0
End Sub

Private Function NextStyleFor(ByVal prof As clsProfile, ByVal k As ParaKind) As String
    Dim nx As String
    nx = prof.GetStr(KindSection(k), "NextStyle", "")
    Select Case LCase$(nx)
        Case "": ' defaults
            Select Case k
                Case pkTitle: NextStyleFor = KindStyleName(prof, pkSubtitle)
                Case pkArticle: NextStyleFor = KindStyleName(prof, pkClause)
                Case pkClause: NextStyleFor = KindStyleName(prof, pkClause)
                Case pkSubClause: NextStyleFor = KindStyleName(prof, pkSubClause)
                Case pkRecital: NextStyleFor = KindStyleName(prof, pkRecital)
                Case pkSignature: NextStyleFor = KindStyleName(prof, pkSignature)
                Case pkTableText: NextStyleFor = KindStyleName(prof, pkTableText)
                Case Else: NextStyleFor = KindStyleName(prof, pkBody)
            End Select
        Case "same": NextStyleFor = KindStyleName(prof, k)
        Case Else
            Dim j As Long
            NextStyleFor = KindStyleName(prof, pkBody)
            For j = 0 To KIND_COUNT - 1
                If StrComp(nx, KindLabel(j), vbTextCompare) = 0 Or StrComp(nx, KindSection(j), vbTextCompare) = 0 Then
                    NextStyleFor = KindStyleName(prof, j)
                End If
            Next
    End Select
End Function

' Pushes the profile section's font + paragraph settings onto a style.
Private Sub ApplyStyleProps(ByVal s As Style, ByVal prof As clsProfile, ByVal section As String, ByVal isNormal As Boolean)
    Dim hanging As Double, leftInd As Double, firstLine As Double, ls As Double

    With s.Font
        .Name = prof.StyleStr(section, "Font", "Times New Roman")
        On Error Resume Next
        .NameBi = prof.StyleStr(section, "FontBi", .Name)
        On Error GoTo 0
        .Size = prof.StyleNum(section, "Size", 12)
        .Bold = prof.StyleBool(section, "Bold", False)
        .Italic = prof.StyleBool(section, "Italic", False)
        .AllCaps = prof.StyleBool(section, "AllCaps", False)
        .Underline = IIf(prof.StyleBool(section, "Underline", False), wdUnderlineSingle, wdUnderlineNone)
        .Color = prof.StyleColor(section, "Color", wdColorAutomatic)
    End With

    With s.ParagraphFormat
        Select Case LCase$(prof.StyleStr(section, "Alignment", "justify"))
            Case "left": .Alignment = wdAlignParagraphLeft
            Case "center", "centre": .Alignment = wdAlignParagraphCenter
            Case "right": .Alignment = wdAlignParagraphRight
            Case Else: .Alignment = wdAlignParagraphJustify
        End Select
        ls = prof.StyleNum(section, "LineSpacing", 1.15)
        If ls >= 5 Then
            .LineSpacingRule = wdLineSpaceExactly
            .LineSpacing = ls
        Else
            .LineSpacingRule = wdLineSpaceMultiple
            .LineSpacing = LinesToPoints(ls)
        End If
        .SpaceBefore = prof.StyleLen(section, "SpaceBefore", 0)
        .SpaceAfter = prof.StyleLen(section, "SpaceAfter", 7)
        .SpaceBeforeAuto = False
        .SpaceAfterAuto = False
        leftInd = prof.StyleLen(section, "LeftIndent", 0)
        hanging = prof.StyleLen(section, "HangingIndent", 0)
        firstLine = prof.StyleLen(section, "FirstLineIndent", 0)
        .LeftIndent = leftInd
        .RightIndent = prof.StyleLen(section, "RightIndent", 0)
        If hanging > 0 Then .FirstLineIndent = -hanging Else .FirstLineIndent = firstLine
        .KeepWithNext = prof.StyleBool(section, "KeepWithNext", False)
        .KeepTogether = prof.StyleBool(section, "KeepTogether", False)
        .WidowControl = True
        .PageBreakBefore = prof.StyleBool(section, "PageBreakBefore", False)
        Select Case CLng(prof.GetNum(section, "OutlineLevel", 0))
            Case 1: .OutlineLevel = wdOutlineLevel1
            Case 2: .OutlineLevel = wdOutlineLevel2
            Case 3: .OutlineLevel = wdOutlineLevel3
            Case Else: If Not isNormal Then .OutlineLevel = wdOutlineLevelBodyText
        End Select
    End With
    On Error Resume Next
    s.NoSpaceBetweenParagraphsOfSameStyle = prof.StyleBool(section, "ContextualSpacing", False)
    If Not isNormal Then
        s.AutomaticallyUpdate = False
        s.Priority = 1
    End If
    On Error GoTo 0
End Sub

' ---------------------------------------------------------------------------
' Multilevel numbering:  level 1 = Article "1.", level 2 = Clause "1.1",
' level 3 = Sub-clause "a)".  One list template per profile, linked to the
' three styles, so numbering follows the style and restarts automatically.
' ---------------------------------------------------------------------------
Public Sub BuildNumbering(ByVal doc As Document, ByVal prof As clsProfile)
    Dim lt As ListTemplate, ltName As String, i As Long, lvl As ListLevel
    Dim k As ParaKind, section As String

    ltName = prof.StylePrefix & "Numbering"
    For i = 1 To doc.ListTemplates.Count
        If StrComp(doc.ListTemplates(i).Name, ltName, vbTextCompare) = 0 Then
            Set lt = doc.ListTemplates(i)
            Exit For
        End If
    Next
    If lt Is Nothing Then Set lt = doc.ListTemplates.Add(OutlineNumbered:=True, Name:=ltName)

    For i = 1 To 3
        Select Case i
            Case 1: k = pkArticle
            Case 2: k = pkClause
            Case 3: k = pkSubClause
        End Select
        section = KindSection(k)
        Set lvl = lt.ListLevels(i)
        With lvl
            .NumberFormat = prof.GetStr(section, "NumberFormat", DefaultNumberFormat(i))
            .NumberStyle = NumberStyleFromName(prof.GetStr(section, "NumberStyle", DefaultNumberStyle(i)))
            .StartAt = CLng(prof.GetNum(section, "StartAt", 1))
            .Alignment = wdListLevelAlignLeft
            .TrailingCharacter = wdTrailingTab
            .NumberPosition = prof.StyleLen(section, "LeftIndent", 0) - prof.StyleLen(section, "HangingIndent", 0)
            .TextPosition = prof.StyleLen(section, "LeftIndent", 0)
            .TabPosition = .TextPosition
            .Font.Bold = prof.GetBool(section, "NumberBold", (i < 3))
            .Font.Italic = prof.GetBool(section, "NumberItalic", False)
            On Error Resume Next
            .Font.Name = prof.StyleStr(section, "Font", "Times New Roman")
            .Font.Size = prof.StyleNum(section, "Size", 12)
            .Font.Color = prof.StyleColor(section, "Color", wdColorAutomatic)
            On Error GoTo 0
        End With
    Next
    ' levels 4-9 are left at Word defaults but given sensible indents
    For i = 4 To 9
        With lt.ListLevels(i)
            .NumberPosition = 36 + (i - 3) * 18
            .TextPosition = 54 + (i - 3) * 18
            .TabPosition = .TextPosition
        End With
    Next

    doc.Styles(KindStyleName(prof, pkArticle)).LinkToListTemplate ListTemplate:=lt, ListLevelNumber:=1
    doc.Styles(KindStyleName(prof, pkClause)).LinkToListTemplate ListTemplate:=lt, ListLevelNumber:=2
    doc.Styles(KindStyleName(prof, pkSubClause)).LinkToListTemplate ListTemplate:=lt, ListLevelNumber:=3
End Sub

Private Function DefaultNumberFormat(ByVal level As Long) As String
    Select Case level
        Case 1: DefaultNumberFormat = "%1."
        Case 2: DefaultNumberFormat = "%1.%2"
        Case Else: DefaultNumberFormat = "%3)"
    End Select
End Function

Private Function DefaultNumberStyle(ByVal level As Long) As String
    If level = 3 Then DefaultNumberStyle = "lowerletter" Else DefaultNumberStyle = "arabic"
End Function

Private Function NumberStyleFromName(ByVal n As String) As WdListNumberStyle
    Select Case LCase$(Replace(n, " ", ""))
        Case "arabic", "decimal", "number": NumberStyleFromName = wdListNumberStyleArabic
        Case "lowerletter", "lowercaseletter": NumberStyleFromName = wdListNumberStyleLowercaseLetter
        Case "upperletter", "uppercaseletter": NumberStyleFromName = wdListNumberStyleUppercaseLetter
        Case "lowerroman", "lowercaseroman": NumberStyleFromName = wdListNumberStyleLowercaseRoman
        Case "upperroman", "uppercaseroman": NumberStyleFromName = wdListNumberStyleUppercaseRoman
        Case "none": NumberStyleFromName = wdListNumberStyleNone
        Case Else: NumberStyleFromName = wdListNumberStyleArabic
    End Select
End Function

' ---------------------------------------------------------------------------
' Main pass over the body
' ---------------------------------------------------------------------------
Private Sub ClassifyAndApply(ByVal doc As Document, ByVal prof As clsProfile, ByRef st As ApplyStats)
    Dim para As Paragraph, k As ParaKind, ctx As DocContext, seenTitle As Boolean, lastKind As ParaKind
    Dim stripIt As Boolean, plen As Long

    ctx = dcFront
    seenTitle = False
    lastKind = pkBody
    ' The paragraph count never changes during the walk: only characters
    ' inside paragraphs are deleted, so For Each is safe here.
    For Each para In doc.Content.Paragraphs
        If para.Range.Information(wdWithInTable) Then GoTo NextPara
        If para.Range.StoryType <> wdMainTextStory Then GoTo NextPara
        If IsContentControlOrField(para) Then GoTo NextPara
        k = ClassifyParagraph(doc, para, prof, ctx, seenTitle, lastKind, stripIt, plen)
        ApplyKindToParagraph doc, para, k, prof, stripIt, plen
        st.Counts(k) = st.Counts(k) + 1
        If stripIt Then st.Stripped = st.Stripped + 1
NextPara:
    Next
End Sub

Private Function IsContentControlOrField(ByVal para As Paragraph) As Boolean
    ' Leave TOC fields and similar alone.
    On Error Resume Next
    If para.Range.Fields.Count > 0 Then
        If para.Range.Fields(1).Type = wdFieldTOC Then IsContentControlOrField = True
    End If
    On Error GoTo 0
End Function

' Applies one kind to one paragraph: strip typed number, drop old list
' numbering, set the style, flatten direct formatting, bold the lead-in.
Public Sub ApplyKindToParagraph(ByVal doc As Document, ByVal para As Paragraph, ByVal k As ParaKind, _
                                ByVal prof As clsProfile, ByVal stripIt As Boolean, ByVal plen As Long)
    Dim r As Range, section As String, styleName As String
    section = KindSection(k)
    styleName = KindStyleName(prof, k)

    ' 1. remove typed prefix (within the paragraph's own story: body, text box, header ...)
    If stripIt And plen > 0 Then
        Set r = para.Range.Duplicate
        r.End = r.Start + plen
        If Len(r.Text) = plen Then
            On Error Resume Next          ' locked content control: leave the number in place
            r.Delete
            On Error GoTo 0
        End If
    End If

    ' 2. old Word numbering (bullets are kept on unnumbered kinds)
    Dim keepBullets As Boolean
    If para.Range.ListFormat.ListType <> wdListNoNumbering Then
        If KindIsNumbered(k) Or para.Range.ListFormat.ListType <> wdListBullet Then
            para.Range.ListFormat.RemoveNumbers
        Else
            keepBullets = True
        End If
    End If

    ' 3. style, then clear manual paragraph formatting left by the draft
    para.Style = doc.Styles(styleName)
    If Not keepBullets Then
        On Error Resume Next
        para.Reset
        On Error GoTo 0
    End If
    If para.Range.ListFormat.ListType = wdListNoNumbering And KindIsNumbered(k) Then
        ' the style should have brought its list; re-assert in case Reset dropped it
        para.Style = doc.Styles(styleName)
    End If

    ' 4. flatten direct character formatting that fights the style, keep emphasis
    If prof.GetBool("Options", "ClearDirectFontFormatting", True) Then
        ' Only touch what differs from the style (a mixed value reads as "" / 9999999),
        ' so a clean paragraph keeps following the style when the style is edited later.
        Dim wantFont As String, wantSize As Double, wantColor As Long
        wantFont = prof.StyleStr(section, "Font", "Times New Roman")
        wantSize = prof.StyleNum(section, "Size", 12)
        wantColor = prof.StyleColor(section, "Color", wdColorAutomatic)
        With para.Range.Font
            If StrComp(.Name, wantFont, vbTextCompare) <> 0 Then .Name = wantFont
            If .Size <> wantSize Then .Size = wantSize
            If .Color <> wantColor Then .Color = wantColor
            If prof.GetBool("Options", "ClearHighlight", False) Then para.Range.HighlightColorIndex = wdNoHighlight
        End With
        If prof.StyleBool(section, "Bold", False) Then para.Range.Font.Bold = True
        If prof.StyleBool(section, "Italic", False) Then para.Range.Font.Italic = True
    End If

    ' 5. lead-in emphasis
    Select Case k
        Case pkClause, pkSubClause, pkArticle
            If prof.GetBool(section, "BoldLeadIn", k = pkClause) Then BoldLeadIn para, prof, section
        Case pkRecital
            If prof.GetBool(section, "BoldLeadIn", True) Then BoldRecitalName para, prof
        Case pkSignature
            If prof.GetBool(section, "BoldLabels", True) Then BoldSignatureLabel para, prof
    End Select
End Sub

' "Engagement. The Client engages ..."  ->  bold "Engagement."
Private Sub BoldLeadIn(ByVal para As Paragraph, ByVal prof As clsProfile, ByVal section As String)
    Dim txt As String, maxLen As Long, maxWords As Long, p As Long, lead As String, r As Range
    Dim stopChars As String, i As Long, c As String, nxt As String
    If para.Range.Font.Bold <> False Then Exit Sub         ' already has bold somewhere -> author's choice
    txt = ParaText(para)
    maxLen = CLng(prof.GetNum(section, "LeadInMaxLength", 70))
    maxWords = CLng(prof.GetNum(section, "LeadInMaxWords", 5))
    stopChars = prof.GetStr(section, "LeadInStop", ".:")
    ' a clause that simply starts with a sentence ("The Consultant shall ...") has no lead-in
    If StartsWithAny(txt, prof.GetStr(section, "LeadInSkipStarts", _
            "The|A|An|This|Each|No|Any|All|If|Where|In|On|For|Subject|Notwithstanding|Neither|Either|Nothing|Unless|Except|Within|During|Upon")) Then Exit Sub
    For i = 1 To Len(txt)
        If i > maxLen Then Exit Sub
        c = Mid$(txt, i, 1)
        If InStr(stopChars, c) > 0 Then
            nxt = Mid$(txt, i + 1, 1)
            If Len(nxt) = 0 Or IsSpaceChar(nxt) Then
                lead = Left$(txt, i - 1)
                If c = "." And IsAbbreviation(lead) Then GoTo Continue
                If Not HasLetters(lead) Then Exit Sub
                If WordCount(lead) > maxWords Then Exit Sub
                If Not IsUpperChar(Left$(Trim$(lead), 1)) Then Exit Sub
                p = i
                Exit For
            End If
        End If
Continue:
    Next
    If p = 0 Then Exit Sub
    Set r = para.Range.Duplicate
    r.End = r.Start + p
    r.Font.Bold = True
End Sub

Private Function IsAbbreviation(ByVal lead As String) As Boolean
    Dim lastWord As String, p As Long
    lead = Trim$(lead)
    p = InStrRev(lead, " ")
    If p > 0 Then lastWord = Mid$(lead, p + 1) Else lastWord = lead
    Select Case LCase$(lastWord)
        Case "mr", "mrs", "ms", "dr", "no", "nos", "inc", "ltd", "co", "llc", "plc", "wll", "w.l.l", "e.g", "i.e", "etc", "vs", "cf", "para", "cl"
            IsAbbreviation = True
    End Select
    If Len(lastWord) = 1 Then IsAbbreviation = True       ' initials: "J. Smith"
End Function

' "(1) Almoayyed Contracting Group W.L.L., Commercial Registration ..." -> bold the name
Private Sub BoldRecitalName(ByVal para As Paragraph, ByVal prof As clsProfile)
    Dim txt As String, px As PrefixInfo, startPos As Long, p As Long, r As Range, maxLen As Long
    If para.Range.Font.Bold <> False Then Exit Sub
    txt = ParaText(para)
    px = ParsePrefix(txt)
    startPos = px.Length
    maxLen = CLng(prof.GetNum("Recital", "LeadInMaxLength", 90))
    p = InStr(startPos + 1, txt, prof.GetStr("Recital", "LeadInStop", ","))
    If p = 0 Or p - startPos > maxLen Then Exit Sub
    Set r = para.Range.Duplicate
    r.Start = r.Start + startPos
    r.End = para.Range.Start + p - 1
    If Len(Trim$(r.Text)) = 0 Then Exit Sub
    r.Font.Bold = True
End Sub

' "Name: Jane Doe" -> bold "Name:";  "For the Client" -> bold whole line
Private Sub BoldSignatureLabel(ByVal para As Paragraph, ByVal prof As clsProfile)
    Dim txt As String, p As Long, r As Range
    If para.Range.Font.Bold <> False Then Exit Sub
    txt = ParaText(para)
    If StartsWithAny(CleanText(txt), prof.GetStr("Signature", "WholeLineBold", "For the|For and on behalf|Signed for|Executed by")) _
       And Len(txt) <= 80 Then
        para.Range.Font.Bold = True
        Exit Sub
    End If
    p = InStr(txt, ":")
    If p = 0 Or p > 40 Then Exit Sub
    Set r = para.Range.Duplicate
    r.End = r.Start + p
    r.Font.Bold = True
End Sub

' ---------------------------------------------------------------------------
' Tables
' ---------------------------------------------------------------------------
Private Sub FormatTables(ByVal doc As Document, ByVal prof As clsProfile, ByRef st As ApplyStats)
    Dim t As Table, c As Cell, shade As Long, p As Paragraph
    Dim textStyle As String, headStyle As String, bw As Double
    If Not prof.GetBool("Table", "Enabled", True) Then Exit Sub
    textStyle = KindStyleName(prof, pkTableText)
    headStyle = KindStyleName(prof, pkTableHeading)
    shade = prof.GetColor("Table", "HeaderShade", RGB(231, 230, 230))
    bw = prof.GetNum("Table", "BorderWidth", 0.5)

    For Each t In doc.Tables
        On Error Resume Next
        If prof.GetBool("Table", "Borders", True) Then
            With t.Borders
                .Enable = True
                .InsideLineStyle = wdLineStyleSingle
                .OutsideLineStyle = wdLineStyleSingle
                .InsideLineWidth = LineWidthFor(bw)
                .OutsideLineWidth = LineWidthFor(bw)
                .InsideColor = wdColorAutomatic
                .OutsideColor = wdColorAutomatic
            End With
        End If
        t.TopPadding = prof.GetLen("Table", "CellPaddingTop", 3)
        t.BottomPadding = prof.GetLen("Table", "CellPaddingBottom", 3)
        t.LeftPadding = prof.GetLen("Table", "CellPaddingLeft", 5)
        t.RightPadding = prof.GetLen("Table", "CellPaddingRight", 5)
        On Error GoTo 0

        ' Header-row treatment: not for one-row tables or signature-block tables.
        Dim headerRow As Boolean, firstRowText As String
        headerRow = prof.GetBool("Table", "FirstRowIsHeader", True)
        On Error Resume Next
        If t.Rows.Count < 2 Then headerRow = False
        firstRowText = ""
        For Each c In t.Range.Cells
            If c.RowIndex = 1 Then firstRowText = firstRowText & " " & CleanText(c.Range.Text)
        Next
        On Error GoTo 0
        If ContainsAny(firstRowText, prof.GetStr("Table", "SignatureTableWords", "Signed|Signature|For and on behalf|For the|Name:|Witness")) Then headerRow = False

        ' Walk cells through t.Range.Cells: Rows/Row.Cells fail on vertically merged cells.
        For Each c In t.Range.Cells
            For Each p In c.Range.Paragraphs
                If headerRow And c.RowIndex = 1 Then
                    ApplyKindToParagraph doc, p, pkTableHeading, prof, False, 0
                Else
                    ApplyKindToParagraph doc, p, pkTableText, prof, False, 0
                End If
            Next
            If headerRow And c.RowIndex = 1 Then
                On Error Resume Next
                c.Shading.Texture = wdTextureNone
                c.Shading.BackgroundPatternColor = shade
                On Error GoTo 0
            End If
        Next
        If headerRow Then
            On Error Resume Next
            t.Rows(1).HeadingFormat = True
            On Error GoTo 0
        End If
        st.Tables = st.Tables + 1
    Next
End Sub

Private Function LineWidthFor(ByVal pts As Double) As WdLineWidth
    If pts <= 0.25 Then
        LineWidthFor = wdLineWidth025pt
    ElseIf pts <= 0.5 Then
        LineWidthFor = wdLineWidth050pt
    ElseIf pts <= 0.75 Then
        LineWidthFor = wdLineWidth075pt
    ElseIf pts <= 1 Then
        LineWidthFor = wdLineWidth100pt
    Else
        LineWidthFor = wdLineWidth150pt
    End If
End Function

' ---------------------------------------------------------------------------
' Headers and footers.  Text may contain {PAGE} {NUMPAGES} {DATE} {FILENAME}.
' ---------------------------------------------------------------------------
Private Sub SetupHeadersFooters(ByVal doc As Document, ByVal prof As clsProfile)
    Dim sec As Section
    For Each sec In doc.Sections
        If prof.GetBool("Footer", "Replace", True) Then
            WriteHeaderFooter sec.Footers(wdHeaderFooterPrimary), prof, "Footer"
            If sec.PageSetup.DifferentFirstPageHeaderFooter Then WriteHeaderFooter sec.Footers(wdHeaderFooterFirstPage), prof, "Footer"
            If sec.PageSetup.OddAndEvenPagesHeaderFooter Then WriteHeaderFooter sec.Footers(wdHeaderFooterEvenPages), prof, "Footer"
        End If
        If prof.GetBool("Header", "Replace", False) Then
            WriteHeaderFooter sec.Headers(wdHeaderFooterPrimary), prof, "Header"
            If sec.PageSetup.DifferentFirstPageHeaderFooter Then WriteHeaderFooter sec.Headers(wdHeaderFooterFirstPage), prof, "Header"
            If sec.PageSetup.OddAndEvenPagesHeaderFooter Then WriteHeaderFooter sec.Headers(wdHeaderFooterEvenPages), prof, "Header"
        End If
    Next
End Sub

Private Sub WriteHeaderFooter(ByVal hf As HeaderFooter, ByVal prof As clsProfile, ByVal section As String)
    Dim txt As String, parts() As String, i As Long, tok As String, closeP As Long, pos As Long
    txt = prof.GetStr(section, "Text", IIf(section = "Footer", "Page {PAGE} of {NUMPAGES}", ""))
    On Error Resume Next
    hf.LinkToPrevious = False
    On Error GoTo 0
    hf.Range.Text = ""
    pos = hf.Range.Start
    parts = Split(txt, "{")
    For i = 0 To UBound(parts)
        If i = 0 Then
            pos = AppendText(hf, pos, parts(i))
        Else
            closeP = InStr(parts(i), "}")
            If closeP > 0 Then
                tok = UCase$(Trim$(Left$(parts(i), closeP - 1)))
                pos = AppendField(hf, pos, tok)
                pos = AppendText(hf, pos, Mid$(parts(i), closeP + 1))
            Else
                pos = AppendText(hf, pos, "{" & parts(i))
            End If
        End If
    Next
    With hf.Range
        .Font.Name = prof.StyleStr(section, "Font", prof.StyleStr("Body", "Font", "Times New Roman"))
        .Font.Size = prof.StyleNum(section, "Size", 9)
        .Font.Bold = prof.GetBool(section, "Bold", False)
        .Font.Italic = prof.GetBool(section, "Italic", False)
        .Font.Color = prof.StyleColor(section, "Color", wdColorAutomatic)
        Select Case LCase$(prof.GetStr(section, "Alignment", "center"))
            Case "left": .ParagraphFormat.Alignment = wdAlignParagraphLeft
            Case "right": .ParagraphFormat.Alignment = wdAlignParagraphRight
            Case Else: .ParagraphFormat.Alignment = wdAlignParagraphCenter
        End Select
        .ParagraphFormat.SpaceBefore = 0
        .ParagraphFormat.SpaceAfter = 0
        .Fields.Update
    End With
End Sub

' Inserts literal text at pos; returns the position after it.
Private Function AppendText(ByVal hf As HeaderFooter, ByVal pos As Long, ByVal s As String) As Long
    Dim r As Range
    AppendText = pos
    If Len(s) = 0 Then Exit Function
    Set r = hf.Range
    r.SetRange pos, pos
    r.InsertAfter s
    AppendText = r.End
End Function

' Inserts a field at pos; returns the position after the field end mark.
Private Function AppendField(ByVal hf As HeaderFooter, ByVal pos As Long, ByVal tok As String) As Long
    Dim r As Range, code As String, f As Field
    Select Case tok
        Case "PAGE": code = "PAGE"
        Case "NUMPAGES", "PAGES": code = "NUMPAGES"
        Case "SECTIONPAGES": code = "SECTIONPAGES"
        Case "DATE": code = "DATE \@ ""d MMMM yyyy"""
        Case "FILENAME": code = "FILENAME"
        Case "TITLE": code = "TITLE"
        Case Else: code = tok
    End Select
    Set r = hf.Range
    r.SetRange pos, pos
    Set f = hf.Range.Fields.Add(Range:=r, Type:=wdFieldEmpty, Text:=code, PreserveFormatting:=False)
    f.Update
    AppendField = f.Result.End + 1
End Function

' ---------------------------------------------------------------------------
' Summary
' ---------------------------------------------------------------------------
Private Function SummaryText(ByVal prof As clsProfile, ByRef st As ApplyStats) As String
    Dim s As String, k As Long
    s = "Applied format: " & prof.Name
    If Len(prof.Version) > 0 Then s = s & "  (v" & prof.Version & ")"
    s = s & vbCrLf & vbCrLf
    For k = 0 To KIND_COUNT - 1
        If st.Counts(k) > 0 Then s = s & Format$(st.Counts(k), "@@@@") & "  " & KindLabel(k) & vbCrLf
    Next
    If st.Tables > 0 Then s = s & Format$(st.Tables, "@@@@") & "  Table(s)" & vbCrLf
    If st.Stripped > 0 Then s = s & vbCrLf & "Typed numbers removed and replaced by automatic numbering: " & st.Stripped & vbCrLf
    s = s & vbCrLf & "Check the result. If a paragraph was classified wrongly, put the cursor in it and use the " & _
            """Mark as"" buttons on the " & APP_NAME & " tab. Ctrl+Z undoes the whole operation." & vbCrLf & vbCrLf & _
            "Reminder: cross-references typed as text (""Clause 3.1"") are not updated automatically."
    SummaryText = s
End Function
