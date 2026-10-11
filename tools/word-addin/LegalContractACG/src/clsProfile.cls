VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "clsProfile"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = False
Option Explicit

' ============================================================================
' clsProfile - loads a format profile (.ini) into memory and answers typed
' lookups with defaults.  A profile is plain text:
'
'   ; comment
'   [Section]
'   Key = Value
'
' Keys are case-insensitive.  Every style section falls back to [Body] and
' then to the hard-coded default passed by the caller, so a profile only has
' to list what differs.
' ============================================================================

Private mKeys As Collection      ' "section|key" -> value (String)
Private mSections As Collection  ' ordered list of section names
Private mPath As String
Private mLoaded As Boolean

Private Sub Class_Initialize()
    Set mKeys = New Collection
    Set mSections = New Collection
End Sub

Public Property Get Path() As String
    Path = mPath
End Property

Public Property Get IsLoaded() As Boolean
    IsLoaded = mLoaded
End Property

Public Property Get Name() As String
    Name = GetStr("Format", "Name", FileBaseName(mPath))
End Property

Public Property Get Version() As String
    Version = GetStr("Format", "Version", "")
End Property

Public Property Get Description() As String
    Description = GetStr("Format", "Description", "")
End Property

' Prefix put in front of every style the engine creates, e.g. "ACG ".
Public Property Get StylePrefix() As String
    Dim p As String
    p = GetStr("Format", "StylePrefix", "ACG")
    ' values are trimmed on load, so re-add the separating space
    If Len(p) > 0 And Right$(p, 1) <> " " Then p = p & " "
    StylePrefix = p
End Property

' ---------------------------------------------------------------------------
' Loading
' ---------------------------------------------------------------------------
Public Function Load(ByVal filePath As String) As Boolean
    Dim f As Integer, lineText As String, section As String
    Dim p As Long, k As String, v As String, firstLine As Boolean

    Set mKeys = New Collection
    Set mSections = New Collection
    mPath = filePath
    mLoaded = False
    section = "Format"

    On Error GoTo Fail
    f = FreeFile
    Open filePath For Input As #f
    firstLine = True
    Do While Not EOF(f)
        Line Input #f, lineText
        If firstLine Then
            ' strip UTF-8 byte order mark if the file was saved with one
            If Len(lineText) >= 3 Then
                If Left$(lineText, 3) = Chr$(239) & Chr$(187) & Chr$(191) Then lineText = Mid$(lineText, 4)
            End If
            firstLine = False
        End If
        lineText = Trim$(lineText)
        If Len(lineText) = 0 Then GoTo NextLine
        If Left$(lineText, 1) = ";" Or Left$(lineText, 1) = "#" Then GoTo NextLine
        If Left$(lineText, 1) = "[" Then
            p = InStr(lineText, "]")
            If p > 2 Then
                section = Trim$(Mid$(lineText, 2, p - 2))
                AddSection section
            End If
            GoTo NextLine
        End If
        p = InStr(lineText, "=")
        If p > 1 Then
            k = Trim$(Left$(lineText, p - 1))
            v = Trim$(Mid$(lineText, p + 1))
            ' allow trailing comments after a value:  Key = Value  ; note
            v = StripTrailingComment(v)
            SetValue section, k, v
        End If
NextLine:
    Loop
    Close #f
    mLoaded = True
    Load = True
    Exit Function
Fail:
    On Error Resume Next
    Close #f
    Load = False
End Function

Private Function StripTrailingComment(ByVal v As String) As String
    Dim p As Long
    p = InStr(v, " ;")
    If p > 0 Then v = Left$(v, p - 1)
    p = InStr(v, Chr$(9) & ";")
    If p > 0 Then v = Left$(v, p - 1)
    StripTrailingComment = Trim$(v)
End Function

Private Sub AddSection(ByVal section As String)
    Dim s As Variant
    For Each s In mSections
        If StrComp(s, section, vbTextCompare) = 0 Then Exit Sub
    Next
    mSections.Add section
End Sub

Private Function KeyOf(ByVal section As String, ByVal key As String) As String
    KeyOf = LCase$(section) & "|" & LCase$(key)
End Function

Public Sub SetValue(ByVal section As String, ByVal key As String, ByVal value As String)
    Dim kk As String
    kk = KeyOf(section, key)
    On Error Resume Next
    mKeys.Remove kk
    On Error GoTo 0
    mKeys.Add value, kk
    AddSection section
End Sub

Public Function HasKey(ByVal section As String, ByVal key As String) As Boolean
    Dim v As String
    On Error Resume Next
    v = mKeys.Item(KeyOf(section, key))
    HasKey = (Err.Number = 0)
    On Error GoTo 0
End Function

Public Function HasSection(ByVal section As String) As Boolean
    Dim s As Variant
    For Each s In mSections
        If StrComp(s, section, vbTextCompare) = 0 Then HasSection = True: Exit Function
    Next
End Function

' ---------------------------------------------------------------------------
' Raw lookup: section first, then [Body] (for style sections), then default.
' ---------------------------------------------------------------------------
Private Function Raw(ByVal section As String, ByVal key As String, ByVal fallbackToBody As Boolean, ByVal defaultValue As String) As String
    Dim v As String
    On Error Resume Next
    v = mKeys.Item(KeyOf(section, key))
    If Err.Number = 0 Then Raw = v: Exit Function
    Err.Clear
    If fallbackToBody And StrComp(section, "Body", vbTextCompare) <> 0 Then
        v = mKeys.Item(KeyOf("Body", key))
        If Err.Number = 0 Then Raw = v: Exit Function
        Err.Clear
    End If
    On Error GoTo 0
    Raw = defaultValue
End Function

' ---------------------------------------------------------------------------
' Typed getters.  The "Style*" variants inherit from [Body].
' ---------------------------------------------------------------------------
Public Function GetStr(ByVal section As String, ByVal key As String, Optional ByVal defaultValue As String = "") As String
    GetStr = Raw(section, key, False, defaultValue)
End Function

Public Function GetNum(ByVal section As String, ByVal key As String, Optional ByVal defaultValue As Double = 0) As Double
    Dim v As String
    v = Raw(section, key, False, "")
    If Len(v) = 0 Then GetNum = defaultValue Else GetNum = ParseNumber(v, defaultValue)
End Function

Public Function GetBool(ByVal section As String, ByVal key As String, Optional ByVal defaultValue As Boolean = False) As Boolean
    GetBool = ParseBool(Raw(section, key, False, ""), defaultValue)
End Function

' Length with optional unit: "72", "72pt", "1in", "2.54cm", "25.4mm".  Result in points.
Public Function GetLen(ByVal section As String, ByVal key As String, Optional ByVal defaultPoints As Double = 0) As Double
    GetLen = ParseLength(Raw(section, key, False, ""), defaultPoints)
End Function

Public Function StyleStr(ByVal section As String, ByVal key As String, Optional ByVal defaultValue As String = "") As String
    StyleStr = Raw(section, key, True, defaultValue)
End Function

Public Function StyleNum(ByVal section As String, ByVal key As String, Optional ByVal defaultValue As Double = 0) As Double
    Dim v As String
    v = Raw(section, key, True, "")
    If Len(v) = 0 Then StyleNum = defaultValue Else StyleNum = ParseNumber(v, defaultValue)
End Function

Public Function StyleBool(ByVal section As String, ByVal key As String, Optional ByVal defaultValue As Boolean = False) As Boolean
    StyleBool = ParseBool(Raw(section, key, True, ""), defaultValue)
End Function

Public Function StyleLen(ByVal section As String, ByVal key As String, Optional ByVal defaultPoints As Double = 0) As Double
    StyleLen = ParseLength(Raw(section, key, True, ""), defaultPoints)
End Function

' Colour as a Word RGB Long.  Accepts "auto", "black", "E7E6E6", "#C00000", "rgb(192,0,0)".
Public Function StyleColor(ByVal section As String, ByVal key As String, Optional ByVal defaultValue As Long = wdColorAutomatic) As Long
    StyleColor = ParseColor(Raw(section, key, True, ""), defaultValue)
End Function

Public Function GetColor(ByVal section As String, ByVal key As String, Optional ByVal defaultValue As Long = wdColorAutomatic) As Long
    GetColor = ParseColor(Raw(section, key, False, ""), defaultValue)
End Function

' ---------------------------------------------------------------------------
' Parsers (public so the engine can reuse them)
' ---------------------------------------------------------------------------
Public Function ParseNumber(ByVal v As String, ByVal defaultValue As Double) As Double
    v = Trim$(v)
    If Len(v) = 0 Then ParseNumber = defaultValue: Exit Function
    If Not IsNumeric(v) Then ParseNumber = defaultValue: Exit Function
    ParseNumber = CDbl(Val(v))
End Function

Public Function ParseBool(ByVal v As String, ByVal defaultValue As Boolean) As Boolean
    v = LCase$(Trim$(v))
    Select Case v
        Case "1", "true", "yes", "on", "y": ParseBool = True
        Case "0", "false", "no", "off", "n": ParseBool = False
        Case Else: ParseBool = defaultValue
    End Select
End Function

Public Function ParseLength(ByVal v As String, ByVal defaultPoints As Double) As Double
    Dim n As String, u As String, i As Long, c As String
    v = LCase$(Trim$(v))
    If Len(v) = 0 Then ParseLength = defaultPoints: Exit Function
    For i = 1 To Len(v)
        c = Mid$(v, i, 1)
        If (c >= "0" And c <= "9") Or c = "." Or c = "-" Then n = n & c Else u = u & c
    Next
    u = Trim$(u)
    If Not IsNumeric(n) Then ParseLength = defaultPoints: Exit Function
    Select Case u
        Case "", "pt": ParseLength = Val(n)
        Case "in", """": ParseLength = Val(n) * 72
        Case "cm": ParseLength = Val(n) * 72 / 2.54
        Case "mm": ParseLength = Val(n) * 72 / 25.4
        Case "tw", "twip", "twips": ParseLength = Val(n) / 20
        Case Else: ParseLength = defaultPoints
    End Select
End Function

Public Function ParseColor(ByVal v As String, ByVal defaultValue As Long) As Long
    Dim h As String, r As Long, g As Long, b As Long, parts() As String
    v = Trim$(v)
    If Len(v) = 0 Then ParseColor = defaultValue: Exit Function
    Select Case LCase$(v)
        Case "auto", "automatic": ParseColor = wdColorAutomatic: Exit Function
        Case "black": ParseColor = RGB(0, 0, 0): Exit Function
        Case "white": ParseColor = RGB(255, 255, 255): Exit Function
        Case "red": ParseColor = RGB(192, 0, 0): Exit Function
        Case "grey", "gray": ParseColor = RGB(128, 128, 128): Exit Function
        Case "none", "nofill": ParseColor = wdColorAutomatic: Exit Function
    End Select
    If LCase$(Left$(v, 4)) = "rgb(" Then
        parts = Split(Mid$(v, 5, Len(v) - 5), ",")
        If UBound(parts) = 2 Then
            ParseColor = RGB(CLng(Val(parts(0))), CLng(Val(parts(1))), CLng(Val(parts(2))))
            Exit Function
        End If
    End If
    h = v
    If Left$(h, 1) = "#" Then h = Mid$(h, 2)
    If Len(h) = 6 Then
        On Error GoTo Bad
        r = CLng("&H" & Mid$(h, 1, 2))
        g = CLng("&H" & Mid$(h, 3, 2))
        b = CLng("&H" & Mid$(h, 5, 2))
        ParseColor = RGB(r, g, b)
        Exit Function
    End If
Bad:
    ParseColor = defaultValue
End Function

Private Function FileBaseName(ByVal p As String) As String
    Dim i As Long, s As String
    s = p
    i = InStrRev(s, Application.PathSeparator)
    If i > 0 Then s = Mid$(s, i + 1)
    i = InStrRev(s, ".")
    If i > 1 Then s = Left$(s, i - 1)
    FileBaseName = s
End Function
