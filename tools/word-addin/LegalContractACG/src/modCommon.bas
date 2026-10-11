Attribute VB_Name = "modCommon"
Option Explicit

' ============================================================================
' modCommon - shared constants, paragraph kinds, profile discovery, helpers.
' ============================================================================

Public Const APP_NAME As String = "Legal Contract ACG"
Public Const APP_VERSION As String = "1.0.0"
Public Const DEFAULT_PROFILE_FILE As String = "LegalContractACG.ini"
Public Const FORMATS_SUBFOLDER As String = "LegalContractACG"
Public Const DOCVAR_PROFILE As String = "LCACG_ProfilePath"
Public Const DOCVAR_PROFILE_NAME As String = "LCACG_ProfileName"

' Paragraph kinds.  Each kind maps to one profile section and one style.
Public Enum ParaKind
    pkBody = 0
    pkTitle = 1
    pkSubtitle = 2
    pkRecital = 3
    pkHeading = 4          ' unnumbered heading (SIGNATURES, BACKGROUND ...)
    pkArticle = 5          ' numbered "1." article heading
    pkClause = 6           ' numbered "1.1"
    pkSubClause = 7        ' numbered "a)"
    pkQuote = 8            ' indented unnumbered paragraph
    pkSignature = 9
    pkScheduleHeading = 10
    pkTableHeading = 11
    pkTableText = 12
End Enum

Public Const KIND_COUNT As Long = 13

' Document context while classifying top-to-bottom.
Public Enum DocContext
    dcFront = 0      ' before the first article heading
    dcBody = 1
    dcSignature = 2
    dcSchedule = 3
End Enum

' ---------------------------------------------------------------------------
' Kind <-> section / style names
' ---------------------------------------------------------------------------
Public Function KindSection(ByVal k As ParaKind) As String
    Select Case k
        Case pkBody: KindSection = "Body"
        Case pkTitle: KindSection = "Title"
        Case pkSubtitle: KindSection = "Subtitle"
        Case pkRecital: KindSection = "Recital"
        Case pkHeading: KindSection = "Heading"
        Case pkArticle: KindSection = "Article"
        Case pkClause: KindSection = "Clause"
        Case pkSubClause: KindSection = "SubClause"
        Case pkQuote: KindSection = "Quote"
        Case pkSignature: KindSection = "Signature"
        Case pkScheduleHeading: KindSection = "ScheduleHeading"
        Case pkTableHeading: KindSection = "TableHeading"
        Case pkTableText: KindSection = "TableText"
        Case Else: KindSection = "Body"
    End Select
End Function

Public Function KindLabel(ByVal k As ParaKind) As String
    Select Case k
        Case pkBody: KindLabel = "Body"
        Case pkTitle: KindLabel = "Title"
        Case pkSubtitle: KindLabel = "Subtitle"
        Case pkRecital: KindLabel = "Recital"
        Case pkHeading: KindLabel = "Heading"
        Case pkArticle: KindLabel = "Article"
        Case pkClause: KindLabel = "Clause"
        Case pkSubClause: KindLabel = "Sub-clause"
        Case pkQuote: KindLabel = "Quote"
        Case pkSignature: KindLabel = "Signature"
        Case pkScheduleHeading: KindLabel = "Schedule Heading"
        Case pkTableHeading: KindLabel = "Table Heading"
        Case pkTableText: KindLabel = "Table Text"
        Case Else: KindLabel = "Body"
    End Select
End Function

Public Function KindStyleName(ByVal prof As clsProfile, ByVal k As ParaKind) As String
    ' A profile may rename a style with  StyleName=  inside its section.
    KindStyleName = prof.StylePrefix & prof.GetStr(KindSection(k), "StyleName", KindLabel(k))
End Function

Public Function KindIsNumbered(ByVal k As ParaKind) As Boolean
    KindIsNumbered = (k = pkArticle Or k = pkClause Or k = pkSubClause)
End Function

' List level (1-based) a numbered kind lives on.
Public Function KindListLevel(ByVal k As ParaKind) As Long
    Select Case k
        Case pkArticle: KindListLevel = 1
        Case pkClause: KindListLevel = 2
        Case pkSubClause: KindListLevel = 3
        Case Else: KindListLevel = 0
    End Select
End Function

' ---------------------------------------------------------------------------
' Profile discovery
' ---------------------------------------------------------------------------
Public Function PathSep() As String
    PathSep = Application.PathSeparator
End Function

Public Function JoinPath(ByVal a As String, ByVal b As String) As String
    If Len(a) = 0 Then JoinPath = b: Exit Function
    If Right$(a, 1) = PathSep() Then JoinPath = a & b Else JoinPath = a & PathSep() & b
End Function

Public Function IsMac() As Boolean
    #If Mac Then
        IsMac = True
    #Else
        IsMac = False
    #End If
End Function

Public Function FolderExists(ByVal p As String) As Boolean
    On Error Resume Next
    FolderExists = (Len(Dir(p, vbDirectory)) > 0)
    On Error GoTo 0
End Function

Public Function FileExists(ByVal p As String) As Boolean
    On Error Resume Next
    FileExists = (Len(Dir(p, vbNormal)) > 0)
    On Error GoTo 0
End Function

' Folder that ships with the add-in:  <STARTUP>\LegalContractACG\Formats
Public Function AddinFormatsFolder() As String
    AddinFormatsFolder = JoinPath(JoinPath(ThisDocument.Path, FORMATS_SUBFOLDER), "Formats")
End Function

' Optional per-user folder for formats installed later without touching STARTUP.
'   Windows:  %APPDATA%\LegalContractACG\Formats
'   Mac:      ~/Library/Application Support/LegalContractACG/Formats
Public Function UserFormatsFolder() As String
    Dim base As String
    #If Mac Then
        base = Environ$("HOME") & "/Library/Application Support"
    #Else
        base = Environ$("APPDATA")
    #End If
    If Len(base) = 0 Then Exit Function
    UserFormatsFolder = JoinPath(JoinPath(base, FORMATS_SUBFOLDER), "Formats")
End Function

' Returns a Collection of full paths of every *.ini profile found, add-in
' folder first, then user folder.  A user file with the same name as an
' add-in file overrides it.
Public Function ListProfiles() As Collection
    Dim result As New Collection, names As New Collection
    Dim folders(1) As String, i As Long, f As String, fullPath As String, key As String
    folders(0) = UserFormatsFolder()
    folders(1) = AddinFormatsFolder()
    For i = 0 To 1
        If Len(folders(i)) > 0 Then
            If FolderExists(folders(i)) Then
                f = Dir(JoinPath(folders(i), "*.ini"))
                Do While Len(f) > 0
                    If Left$(f, 1) <> "_" Then       ' _TEMPLATE.ini etc. are hidden from the menu
                        key = LCase$(f)
                        If Not CollectionHasKey(names, key) Then
                            names.Add f, key
                            fullPath = JoinPath(folders(i), f)
                            result.Add fullPath, key
                        End If
                    End If
                    f = Dir()
                Loop
            End If
        End If
    Next
    Set ListProfiles = result
End Function

Public Function CollectionHasKey(ByVal c As Collection, ByVal key As String) As Boolean
    Dim v As Variant
    On Error Resume Next
    v = c.Item(key)
    CollectionHasKey = (Err.Number = 0)
    On Error GoTo 0
End Function

' Full path of the default profile (the one the big ribbon button applies).
Public Function DefaultProfilePath() As String
    Dim p As String
    p = JoinPath(UserFormatsFolder(), DEFAULT_PROFILE_FILE)
    If FileExists(p) Then DefaultProfilePath = p: Exit Function
    p = JoinPath(AddinFormatsFolder(), DEFAULT_PROFILE_FILE)
    If FileExists(p) Then DefaultProfilePath = p: Exit Function
    ' fall back to the first profile found
    Dim lst As Collection
    Set lst = ListProfiles()
    If lst.Count > 0 Then DefaultProfilePath = lst.Item(1)
End Function

' Profile the active document was last formatted with, else the default.
Public Function ActiveProfilePath(ByVal doc As Document) As String
    Dim p As String
    p = GetDocVar(doc, DOCVAR_PROFILE)
    If Len(p) > 0 Then
        If FileExists(p) Then ActiveProfilePath = p: Exit Function
    End If
    ActiveProfilePath = DefaultProfilePath()
End Function

Public Function LoadProfile(ByVal filePath As String) As clsProfile
    Dim prof As New clsProfile
    If Len(filePath) = 0 Then Set LoadProfile = Nothing: Exit Function
    If Not prof.Load(filePath) Then Set LoadProfile = Nothing: Exit Function
    Set LoadProfile = prof
End Function

' ---------------------------------------------------------------------------
' Document variables
' ---------------------------------------------------------------------------
Public Function GetDocVar(ByVal doc As Document, ByVal name As String) As String
    On Error Resume Next
    GetDocVar = doc.Variables(name).Value
    On Error GoTo 0
End Function

Public Sub SetDocVar(ByVal doc As Document, ByVal name As String, ByVal value As String)
    On Error Resume Next
    doc.Variables(name).Value = value
    If Err.Number <> 0 Then
        Err.Clear
        doc.Variables.Add name, value
    End If
    On Error GoTo 0
End Sub

' ---------------------------------------------------------------------------
' Text helpers (no RegExp: must run on Mac as well as Windows)
' ---------------------------------------------------------------------------
Public Function IsDigitChar(ByVal c As String) As Boolean
    IsDigitChar = (Len(c) = 1 And c >= "0" And c <= "9")
End Function

Public Function IsLowerChar(ByVal c As String) As Boolean
    IsLowerChar = (Len(c) = 1 And c >= "a" And c <= "z")
End Function

Public Function IsUpperChar(ByVal c As String) As Boolean
    IsUpperChar = (Len(c) = 1 And c >= "A" And c <= "Z")
End Function

Public Function IsSpaceChar(ByVal c As String) As Boolean
    IsSpaceChar = (c = " " Or c = vbTab Or c = Chr$(160))
End Function

Public Function HasLetters(ByVal s As String) As Boolean
    Dim i As Long, c As String
    For i = 1 To Len(s)
        c = Mid$(s, i, 1)
        If IsUpperChar(c) Or IsLowerChar(c) Then HasLetters = True: Exit Function
    Next
End Function

' True when every letter in the text is upper case (digits/punctuation ignored).
Public Function IsAllCaps(ByVal s As String) As Boolean
    If Not HasLetters(s) Then Exit Function
    IsAllCaps = (StrComp(s, UCase$(s), vbBinaryCompare) = 0)
End Function

Public Function IsRomanLower(ByVal s As String) As Boolean
    Dim i As Long, c As String
    If Len(s) = 0 Or Len(s) > 5 Then Exit Function
    For i = 1 To Len(s)
        c = Mid$(s, i, 1)
        If InStr("ivxl", c) = 0 Then Exit Function
    Next
    IsRomanLower = True
End Function

Public Function WordCount(ByVal s As String) As Long
    Dim parts() As String
    s = Trim$(Replace(s, vbTab, " "))
    If Len(s) = 0 Then Exit Function
    Do While InStr(s, "  ") > 0
        s = Replace(s, "  ", " ")
    Loop
    parts = Split(s, " ")
    WordCount = UBound(parts) + 1
End Function

Public Function StartsWithWord(ByVal s As String, ByVal w As String) As Boolean
    ' case-insensitive, and the match must end at a word boundary
    Dim n As Long, c As String
    n = Len(w)
    If Len(s) < n Then Exit Function
    If StrComp(Left$(s, n), w, vbTextCompare) <> 0 Then Exit Function
    If Len(s) = n Then StartsWithWord = True: Exit Function
    c = Mid$(s, n + 1, 1)
    StartsWithWord = Not (IsUpperChar(c) Or IsLowerChar(c) Or IsDigitChar(c))
End Function

Public Function StartsWithAny(ByVal s As String, ByVal pipeList As String) As Boolean
    Dim w As Variant
    For Each w In Split(pipeList, "|")
        If Len(w) > 0 Then
            If StartsWithWord(s, CStr(w)) Then StartsWithAny = True: Exit Function
        End If
    Next
End Function

Public Function ContainsAny(ByVal s As String, ByVal pipeList As String) As Boolean
    Dim w As Variant
    For Each w In Split(pipeList, "|")
        If Len(w) > 0 Then
            If InStr(1, s, CStr(w), vbTextCompare) > 0 Then ContainsAny = True: Exit Function
        End If
    Next
End Function

' Paragraph text without the paragraph mark / cell marker, tabs as spaces.
Public Function ParaText(ByVal para As Paragraph) As String
    Dim s As String
    s = para.Range.Text
    Do While Len(s) > 0
        Select Case Right$(s, 1)
            Case vbCr, vbLf, Chr$(7), Chr$(12): s = Left$(s, Len(s) - 1)
            Case Else: Exit Do
        End Select
    Loop
    ParaText = s
End Function

Public Function CleanText(ByVal s As String) As String
    s = Replace(s, vbTab, " ")
    s = Replace(s, Chr$(160), " ")
    s = Replace(s, Chr$(11), " ")   ' manual line break
    CleanText = Trim$(s)
End Function

Public Sub ShellOpenFolder(ByVal folder As String)
    On Error Resume Next
    #If Mac Then
        MacScript "do shell script ""open "" & quoted form of """ & folder & """"
    #Else
        Shell "explorer.exe """ & folder & """", vbNormalFocus
    #End If
End Sub
