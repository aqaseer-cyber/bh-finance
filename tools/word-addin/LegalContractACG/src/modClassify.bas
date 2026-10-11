Attribute VB_Name = "modClassify"
Option Explicit

' ============================================================================
' modClassify - decides what each paragraph of a draft is (title, article,
' clause, sub-clause, recital, signature line ...).
'
' Order of evidence:
'   1. Existing styles (Heading 1/2/3, Title, or styles this add-in created).
'   2. Existing Word list numbering (level + number text).
'   3. Typed prefixes:  "1."  "1.1"  "(a)"  "a)"  "(1)"  "ARTICLE 3".
'   4. Shape of the text: ALL CAPS short line, "Name:" labels, indents.
'   5. Context: before the first article, inside the signature block,
'      inside a schedule.
'
' No RegExp (VBScript.RegExp is Windows-only), so prefixes are parsed by hand.
' ============================================================================

' What a typed prefix looks like.
Public Enum PrefixKind
    pxNone = 0
    pxSingleNumber = 1      ' "1."  "1)"  "ARTICLE 1"
    pxMultiNumber = 2       ' "1.1" "1.1." "2.3.4"
    pxParenNumber = 3       ' "(1)"
    pxLowerLetter = 4       ' "(a)" "a)" "a."
    pxUpperLetter = 5       ' "(A)" "A."
    pxRoman = 6             ' "(i)" "iv)"
End Enum

Public Type PrefixInfo
    Kind As PrefixKind
    Length As Long          ' characters to delete from the start of the raw text (incl. trailing space)
    Depth As Long           ' number groups for pxMultiNumber
End Type

' ---------------------------------------------------------------------------
' Prefix parsing on the RAW paragraph text (leading whitespace included so
' the caller can delete exactly Length characters).
' ---------------------------------------------------------------------------
Public Function ParsePrefix(ByVal raw As String) As PrefixInfo
    Dim r As PrefixInfo, i As Long, n As Long, c As String, start As Long
    Dim token As String, groups As Long, j As Long
    n = Len(raw)
    i = 1
    Do While i <= n
        If IsSpaceChar(Mid$(raw, i, 1)) Then i = i + 1 Else Exit Do
    Loop
    start = i
    If i > n Then ParsePrefix = r: Exit Function
    c = Mid$(raw, i, 1)

    ' --- "(x)" forms ---------------------------------------------------
    If c = "(" Then
        j = InStr(i + 1, raw, ")")
        If j > i + 1 And j - i <= 6 Then
            token = Mid$(raw, i + 1, j - i - 1)
            If IsAllDigits(token) Then
                r.Kind = pxParenNumber
            ElseIf Len(token) = 1 And IsLowerChar(token) Then
                r.Kind = pxLowerLetter
            ElseIf Len(token) = 1 And IsUpperChar(token) Then
                r.Kind = pxUpperLetter
            ElseIf IsRomanLower(token) Then
                r.Kind = pxRoman
            End If
            If r.Kind <> pxNone Then
                If EndsPrefix(raw, j + 1) Then
                    r.Length = SkipSpaces(raw, j + 1) - 1
                    ParsePrefix = r
                    Exit Function
                End If
                r.Kind = pxNone
            End If
        End If
        ParsePrefix = r
        Exit Function
    End If

    ' --- "ARTICLE 3" / "CLAUSE 3" / "SECTION 3" -------------------------
    If IsUpperChar(c) Then
        Dim w As Variant
        For Each w In Array("ARTICLE", "CLAUSE", "SECTION")
            If StrComp(Mid$(raw, i, Len(w)), CStr(w), vbBinaryCompare) = 0 Then
                j = i + Len(w)
                If j <= n Then
                    If IsSpaceChar(Mid$(raw, j, 1)) Then
                        j = SkipSpaces(raw, j)
                        If j <= n Then
                            If IsDigitChar(Mid$(raw, j, 1)) Then
                                Do While j <= n
                                    If IsDigitChar(Mid$(raw, j, 1)) Then j = j + 1 Else Exit Do
                                Loop
                                ' optional "." ":" "-" after the number
                                If j <= n Then
                                    If InStr(".:-", Mid$(raw, j, 1)) > 0 Then j = j + 1
                                End If
                                If EndsPrefix(raw, j) Then
                                    r.Kind = pxSingleNumber
                                    r.Length = SkipSpaces(raw, j) - 1
                                    ParsePrefix = r
                                    Exit Function
                                End If
                            End If
                        End If
                    End If
                End If
            End If
        Next
    End If

    ' --- digit forms:  1.   1)   1.1   1.1.   1.2.3 ----------------------
    If IsDigitChar(c) Then
        j = i
        groups = 0
        Do
            If j > n Then Exit Do
            If Not IsDigitChar(Mid$(raw, j, 1)) Then Exit Do
            Do While j <= n
                If IsDigitChar(Mid$(raw, j, 1)) Then j = j + 1 Else Exit Do
            Loop
            groups = groups + 1
            If j <= n Then
                If Mid$(raw, j, 1) = "." Then
                    If j + 1 <= n Then
                        If IsDigitChar(Mid$(raw, j + 1, 1)) Then
                            j = j + 1
                            GoTo NextGroup
                        End If
                    End If
                End If
            End If
            Exit Do
NextGroup:
        Loop
        ' j now points just after the last digit group
        If groups >= 2 Then
            If j <= n Then
                If Mid$(raw, j, 1) = "." Or Mid$(raw, j, 1) = ")" Then j = j + 1
            End If
            If EndsPrefix(raw, j) Then
                r.Kind = pxMultiNumber
                r.Depth = groups
                r.Length = SkipSpaces(raw, j) - 1
            End If
        ElseIf groups = 1 Then
            ' single number must be closed by "." or ")" to count (avoids years, amounts)
            If j <= n And j - start <= 3 Then
                If Mid$(raw, j, 1) = "." Or Mid$(raw, j, 1) = ")" Then
                    If EndsPrefix(raw, j + 1) Then
                        r.Kind = pxSingleNumber
                        r.Length = SkipSpaces(raw, j + 1) - 1
                    End If
                End If
            End If
        End If
        ParsePrefix = r
        Exit Function
    End If

    ' --- letter forms:  a)  a.  (a) handled above;  iv)  A. -------------
    If IsLowerChar(c) Or IsUpperChar(c) Then
        j = i
        Do While j <= n And j - i < 5
            If IsLowerChar(Mid$(raw, j, 1)) Or IsUpperChar(Mid$(raw, j, 1)) Then j = j + 1 Else Exit Do
        Loop
        token = Mid$(raw, i, j - i)
        If j <= n Then
            If Mid$(raw, j, 1) = ")" Or Mid$(raw, j, 1) = "." Then
                If EndsPrefix(raw, j + 1) Then
                    If Len(token) = 1 And IsLowerChar(token) Then
                        r.Kind = pxLowerLetter
                    ElseIf Len(token) = 1 And IsUpperChar(token) Then
                        ' "A." is a real risk of eating a sentence starting with "A." - only accept with ")"
                        If Mid$(raw, j, 1) = ")" Then r.Kind = pxUpperLetter
                    ElseIf IsRomanLower(token) Then
                        r.Kind = pxRoman
                    End If
                    If r.Kind <> pxNone Then r.Length = SkipSpaces(raw, j + 1) - 1
                End If
            End If
        End If
    End If
    ParsePrefix = r
End Function

Private Function IsAllDigits(ByVal s As String) As Boolean
    Dim i As Long
    If Len(s) = 0 Then Exit Function
    For i = 1 To Len(s)
        If Not IsDigitChar(Mid$(s, i, 1)) Then Exit Function
    Next
    IsAllDigits = True
End Function

' A prefix only counts when followed by whitespace or the end of the text.
Private Function EndsPrefix(ByVal raw As String, ByVal pos As Long) As Boolean
    If pos > Len(raw) Then EndsPrefix = True: Exit Function
    EndsPrefix = IsSpaceChar(Mid$(raw, pos, 1))
End Function

Private Function SkipSpaces(ByVal raw As String, ByVal pos As Long) As Long
    Do While pos <= Len(raw)
        If IsSpaceChar(Mid$(raw, pos, 1)) Then pos = pos + 1 Else Exit Do
    Loop
    SkipSpaces = pos
End Function

' ---------------------------------------------------------------------------
' Classification of one paragraph.
'   ctx            in/out document context
'   seenTitle      in/out
'   stripPrefix    out: True when the typed prefix must be deleted
'   prefixLen      out: how many characters to delete
' ---------------------------------------------------------------------------
Public Function ClassifyParagraph(ByVal doc As Document, ByVal para As Paragraph, ByVal prof As clsProfile, _
                                  ByRef ctx As DocContext, ByRef seenTitle As Boolean, _
                                  ByRef stripPrefix As Boolean, ByRef prefixLen As Long) As ParaKind
    Dim raw As String, txt As String, k As ParaKind, px As PrefixInfo
    Dim maxHeading As Long, rest As String, styleName As String
    Dim inList As Boolean, listStr As String, listLvl As Long

    stripPrefix = False
    prefixLen = 0
    raw = ParaText(para)
    txt = CleanText(raw)
    maxHeading = CLng(prof.GetNum("Classify", "MaxHeadingLength", 80))

    If Len(txt) = 0 Then ClassifyParagraph = pkBody: Exit Function

    ' ---- 1. existing styles -------------------------------------------
    styleName = para.Style.NameLocal
    k = KindFromExistingStyle(doc, prof, styleName)
    If k <> -1 Then
        ' still let typed prefixes be removed for headings that carry them
        px = ParsePrefix(raw)
        If KindIsNumbered(k) And px.Kind <> pxNone Then stripPrefix = True: prefixLen = px.Length
        UpdateContext ctx, k, txt
        If k = pkTitle Then seenTitle = True
        ClassifyParagraph = k
        Exit Function
    End If

    ' ---- 2. existing Word numbering -----------------------------------
    inList = (para.Range.ListFormat.ListType <> wdListNoNumbering)
    If inList Then
        listStr = para.Range.ListFormat.ListString
        listLvl = para.Range.ListFormat.ListLevelNumber
        If para.Range.ListFormat.ListType = wdListBullet Then
            inList = False     ' bullets are left as body text; the style will carry them
        End If
    End If
    If inList Then
        If IsAllCaps(txt) And Len(txt) <= maxHeading Then
            k = pkArticle
        ElseIf IsLetterListString(listStr) Then
            k = pkSubClause
        ElseIf InStr(listStr, ".") > 0 And CountDigitGroups(listStr) >= 2 Then
            k = pkClause
        ElseIf listLvl = 1 Then
            k = pkClause
        Else
            k = pkSubClause
        End If
        UpdateContext ctx, k, txt
        ClassifyParagraph = k
        Exit Function
    End If

    ' ---- 3. front matter: title / subtitle ------------------------------
    px = ParsePrefix(raw)
    If ctx = dcFront Then
        If Not seenTitle Then
            If Len(txt) <= CLng(prof.GetNum("Classify", "MaxTitleLength", 120)) And px.Kind = pxNone Then
                seenTitle = True
                ClassifyParagraph = pkTitle
                Exit Function
            End If
        ElseIf IsSubtitleShape(txt, maxHeading) And px.Kind = pxNone And Not IsAllCaps(txt) Then
            ClassifyParagraph = pkSubtitle
            Exit Function
        End If
    End If

    ' ---- 4. schedule / annex headings ----------------------------------
    If StartsWithAny(txt, prof.GetStr("Classify", "ScheduleWords", "SCHEDULE|ANNEX|ANNEXURE|APPENDIX|EXHIBIT|ATTACHMENT")) _
       And Len(txt) <= maxHeading And (IsAllCaps(txt) Or Right$(txt, 1) <> ".") Then
        ctx = dcSchedule
        ClassifyParagraph = pkScheduleHeading
        Exit Function
    End If

    ' ---- 5. typed prefixes ---------------------------------------------
    If px.Kind <> pxNone Then
        rest = CleanText(Mid$(raw, px.Length + 1))
        Select Case px.Kind
            Case pxSingleNumber
                If IsAllCaps(rest) And Len(rest) <= maxHeading Then
                    k = pkArticle
                ElseIf ctx = dcFront And prof.GetBool("Classify", "FrontNumbersAreRecitals", True) Then
                    k = pkRecital: stripPrefix = False
                    GoTo Done
                Else
                    k = pkClause
                End If
                stripPrefix = True: prefixLen = px.Length
            Case pxMultiNumber
                If px.Depth >= 3 Then k = pkSubClause Else k = pkClause
                If IsAllCaps(rest) And Len(rest) <= maxHeading And px.Depth = 2 Then k = pkClause
                stripPrefix = True: prefixLen = px.Length
            Case pxParenNumber
                ' "(1)" party recitals keep their typed number (not a list)
                k = pkRecital
                If ctx <> dcFront Then
                    k = pkSubClause: stripPrefix = True: prefixLen = px.Length
                End If
            Case pxUpperLetter
                If ctx = dcFront Then
                    k = pkRecital
                Else
                    k = pkSubClause: stripPrefix = True: prefixLen = px.Length
                End If
            Case pxLowerLetter, pxRoman
                k = pkSubClause: stripPrefix = True: prefixLen = px.Length
        End Select
        GoTo Done
    End If

    ' ---- 6. signature block ----------------------------------------------
    If StartsWithAny(txt, prof.GetStr("Classify", "SignatureLabels", _
            "Name:|Title:|Position:|Signature:|Signed:|Date:|Email|E-mail|Telephone|Tel:|Company stamp|Stamp:|Witness|For and on behalf|For the|By:|Designation:")) Then
        k = pkSignature
        GoTo Done
    End If
    If StartsWithWord(txt, "IN WITNESS") Or StartsWithWord(txt, "SIGNED") Then
        ctx = dcSignature
        If Len(txt) <= maxHeading And IsAllCaps(txt) Then k = pkHeading Else k = pkBody
        GoTo Done
    End If

    ' ---- 7. capitals / bold headings -------------------------------------
    If IsAllCaps(txt) And Len(txt) <= maxHeading Then
        If Right$(txt, 1) = ":" Then
            k = pkBody                       ' "BETWEEN:" / "WHEREAS:"
        ElseIf ContainsAny(txt, prof.GetStr("Classify", "SignatureHeadingWords", "SIGNATURE|SIGNED|EXECUTION|WITNESS|EXECUTED")) Then
            k = pkHeading: ctx = dcSignature
        ElseIf ctx = dcFront And StartsWithAny(txt, prof.GetStr("Classify", "FrontHeadingWords", "BACKGROUND|RECITALS|WHEREAS|PRELIMINARY|INTRODUCTION|PARTIES")) Then
            k = pkHeading
        Else
            k = pkArticle
        End If
        GoTo Done
    End If
    If prof.GetBool("Classify", "BoldLineIsHeading", True) And ctx <> dcSignature Then
        If para.Range.Font.Bold = True And Len(txt) <= maxHeading And Right$(txt, 1) <> "." And Right$(txt, 1) <> ":" _
           And WordCount(txt) <= 8 Then
            If ctx = dcFront And Not seenTitle Then
                k = pkTitle: seenTitle = True
            Else
                k = pkArticle
            End If
            GoTo Done
        End If
    End If

    ' ---- 8. context defaults ---------------------------------------------
    If ctx = dcSignature Then
        If Len(txt) <= CLng(prof.GetNum("Classify", "MaxSignatureLineLength", 150)) Then k = pkSignature Else k = pkBody
        GoTo Done
    End If
    If para.LeftIndent > 1 And para.Alignment <> wdAlignParagraphCenter Then
        k = pkQuote
        GoTo Done
    End If
    k = pkBody

Done:
    UpdateContext ctx, k, txt
    ClassifyParagraph = k
End Function

Private Sub UpdateContext(ByRef ctx As DocContext, ByVal k As ParaKind, ByVal txt As String)
    Select Case k
        Case pkArticle
            If ctx = dcFront Then ctx = dcBody
            If ctx = dcSignature Then ctx = dcBody
            If ContainsAny(txt, "SIGNATURE|SIGNED|EXECUTION|WITNESS|EXECUTED") Then ctx = dcSignature
        Case pkClause, pkSubClause
            If ctx = dcFront Then ctx = dcBody
        Case pkScheduleHeading
            ctx = dcSchedule
        Case pkHeading
            If ContainsAny(txt, "SIGNATURE|SIGNED|EXECUTION|WITNESS|EXECUTED") Then ctx = dcSignature
    End Select
End Sub

' Returns -1 when the style gives no hint.
Private Function KindFromExistingStyle(ByVal doc As Document, ByVal prof As clsProfile, ByVal styleName As String) As Long
    Dim k As Long, pfx As String
    KindFromExistingStyle = -1
    pfx = prof.StylePrefix
    ' styles this add-in created (any profile sharing the prefix)
    If Len(pfx) > 0 And StrComp(Left$(styleName, Len(pfx)), pfx, vbTextCompare) = 0 Then
        For k = 0 To KIND_COUNT - 1
            If StrComp(styleName, KindStyleName(prof, k), vbTextCompare) = 0 Then
                KindFromExistingStyle = k
                Exit Function
            End If
        Next
    End If
    On Error Resume Next
    If StrComp(styleName, doc.Styles(wdStyleTitle).NameLocal, vbTextCompare) = 0 Then KindFromExistingStyle = pkTitle
    If StrComp(styleName, doc.Styles(wdStyleSubtitle).NameLocal, vbTextCompare) = 0 Then KindFromExistingStyle = pkSubtitle
    If StrComp(styleName, doc.Styles(wdStyleHeading1).NameLocal, vbTextCompare) = 0 Then KindFromExistingStyle = pkArticle
    If StrComp(styleName, doc.Styles(wdStyleHeading2).NameLocal, vbTextCompare) = 0 Then KindFromExistingStyle = pkClause
    If StrComp(styleName, doc.Styles(wdStyleHeading3).NameLocal, vbTextCompare) = 0 Then KindFromExistingStyle = pkSubClause
    If StrComp(styleName, doc.Styles(wdStyleQuote).NameLocal, vbTextCompare) = 0 Then KindFromExistingStyle = pkQuote
    On Error GoTo 0
End Function

Private Function IsSubtitleShape(ByVal txt As String, ByVal maxHeading As Long) As Boolean
    If Len(txt) > maxHeading Then Exit Function
    If Right$(txt, 1) = "." Or Right$(txt, 1) = ":" Or Right$(txt, 1) = ";" Then Exit Function
    If WordCount(txt) > 10 Then Exit Function
    IsSubtitleShape = True
End Function

Private Function IsLetterListString(ByVal ls As String) As Boolean
    Dim s As String
    s = ls
    s = Replace(s, "(", ""): s = Replace(s, ")", ""): s = Replace(s, ".", ""): s = Trim$(s)
    If Len(s) = 0 Then Exit Function
    If Len(s) = 1 Then
        IsLetterListString = IsLowerChar(s) Or IsUpperChar(s)
    Else
        IsLetterListString = IsRomanLower(LCase$(s))
    End If
End Function

Private Function CountDigitGroups(ByVal s As String) As Long
    Dim i As Long, inDigits As Boolean, c As String
    For i = 1 To Len(s)
        c = Mid$(s, i, 1)
        If IsDigitChar(c) Then
            If Not inDigits Then CountDigitGroups = CountDigitGroups + 1: inDigits = True
        Else
            inDigits = False
        End If
    Next
End Function
