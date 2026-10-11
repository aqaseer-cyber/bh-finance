Attribute VB_Name = "modRibbon"
Option Explicit

' ============================================================================
' modRibbon - callbacks for ribbon/customUI14.xml
' ============================================================================

Private mRibbon As IRibbonUI

Public Sub Ribbon_OnLoad(ByVal ribbon As IRibbonUI)
    Set mRibbon = ribbon
End Sub

Public Sub Ribbon_Invalidate()
    On Error Resume Next
    If Not mRibbon Is Nothing Then mRibbon.Invalidate
    On Error GoTo 0
End Sub

' --- Apply group ---------------------------------------------------------
Public Sub Ribbon_ApplyDefault(ByVal control As IRibbonControl)
    Dim p As String
    p = DefaultProfilePath()
    If Len(p) = 0 Then
        MsgBox "No format profile found." & vbCrLf & vbCrLf & _
               "Expected: " & JoinPath(AddinFormatsFolder(), DEFAULT_PROFILE_FILE) & vbCrLf & _
               "or:       " & JoinPath(UserFormatsFolder(), DEFAULT_PROFILE_FILE), vbExclamation, APP_NAME
        Exit Sub
    End If
    ApplyProfileToActiveDocument p
End Sub

Public Sub Ribbon_ApplyFormat(ByVal control As IRibbonControl)
    ' the dynamic menu stores the profile path in the control's Tag
    If Len(control.Tag) = 0 Then Exit Sub
    ApplyProfileToActiveDocument control.Tag
End Sub

' Builds the "Other formats" menu from whatever .ini files exist.
Public Sub Ribbon_GetFormatsMenu(ByVal control As IRibbonControl, ByRef content As Variant)
    Dim xml As String, lst As Collection, i As Long, prof As clsProfile, label As String, tip As String
    xml = "<menu xmlns=""http://schemas.microsoft.com/office/2009/07/customui"" itemSize=""normal"">"
    Set lst = ListProfiles()
    If lst.Count = 0 Then
        xml = xml & "<button id=""fmtNone"" label=""(no formats found)"" enabled=""false""/>"
    Else
        For i = 1 To lst.Count
            Set prof = LoadProfile(lst.Item(i))
            If prof Is Nothing Then
                label = "(unreadable) " & lst.Item(i)
                tip = ""
            Else
                label = prof.Name
                If Len(prof.Version) > 0 Then label = label & "  v" & prof.Version
                tip = prof.Description
            End If
            xml = xml & "<button id=""fmt" & i & """ label=""" & XmlEscape(label) & """" & _
                        " tag=""" & XmlEscape(lst.Item(i)) & """" & _
                        " imageMso=""FormatPainter""" & _
                        IIf(Len(tip) > 0, " screentip=""" & XmlEscape(tip) & """", "") & _
                        " onAction=""Ribbon_ApplyFormat""/>"
        Next
    End If
    xml = xml & "<menuSeparator id=""fmtSep""/>" & _
          "<button id=""fmtRefresh"" label=""Refresh list"" imageMso=""Refresh"" onAction=""Ribbon_Refresh""/>" & _
          "<button id=""fmtOpen"" label=""Open formats folder..."" imageMso=""FileOpen"" onAction=""Ribbon_OpenFolder""/>" & _
          "</menu>"
    content = xml
End Sub

Private Function XmlEscape(ByVal s As String) As String
    s = Replace(s, "&", "&amp;")
    s = Replace(s, "<", "&lt;")
    s = Replace(s, ">", "&gt;")
    s = Replace(s, """", "&quot;")
    s = Replace(s, "'", "&apos;")
    XmlEscape = s
End Function

' --- Mark as group --------------------------------------------------------
Public Sub Ribbon_MarkTitle(ByVal control As IRibbonControl): MarkSelectionAs pkTitle: End Sub
Public Sub Ribbon_MarkSubtitle(ByVal control As IRibbonControl): MarkSelectionAs pkSubtitle: End Sub
Public Sub Ribbon_MarkRecital(ByVal control As IRibbonControl): MarkSelectionAs pkRecital: End Sub
Public Sub Ribbon_MarkHeading(ByVal control As IRibbonControl): MarkSelectionAs pkHeading: End Sub
Public Sub Ribbon_MarkArticle(ByVal control As IRibbonControl): MarkSelectionAs pkArticle: End Sub
Public Sub Ribbon_MarkClause(ByVal control As IRibbonControl): MarkSelectionAs pkClause: End Sub
Public Sub Ribbon_MarkSubClause(ByVal control As IRibbonControl): MarkSelectionAs pkSubClause: End Sub
Public Sub Ribbon_MarkQuote(ByVal control As IRibbonControl): MarkSelectionAs pkQuote: End Sub
Public Sub Ribbon_MarkBody(ByVal control As IRibbonControl): MarkSelectionAs pkBody: End Sub
Public Sub Ribbon_MarkSignature(ByVal control As IRibbonControl): MarkSelectionAs pkSignature: End Sub
Public Sub Ribbon_MarkScheduleHeading(ByVal control As IRibbonControl): MarkSelectionAs pkScheduleHeading: End Sub

' --- Tools group ------------------------------------------------------------
Public Sub Ribbon_Refresh(ByVal control As IRibbonControl)
    Ribbon_Invalidate
    MsgBox "Format list refreshed.", vbInformation, APP_NAME
End Sub

Public Sub Ribbon_OpenFolder(ByVal control As IRibbonControl)
    Dim f As String
    f = UserFormatsFolder()
    If Not FolderExists(f) Then f = AddinFormatsFolder()
    If Not FolderExists(f) Then
        MsgBox "Formats folder not found:" & vbCrLf & AddinFormatsFolder(), vbExclamation, APP_NAME
        Exit Sub
    End If
    ShellOpenFolder f
End Sub

Public Sub Ribbon_About(ByVal control As IRibbonControl)
    Dim doc As Document, cur As String
    If Documents.Count > 0 Then
        Set doc = ActiveDocument
        cur = GetDocVar(doc, DOCVAR_PROFILE_NAME)
    End If
    MsgBox APP_NAME & " " & APP_VERSION & vbCrLf & vbCrLf & _
           "Add-in folder:   " & ThisDocument.Path & vbCrLf & _
           "Shipped formats: " & AddinFormatsFolder() & vbCrLf & _
           "Your formats:    " & UserFormatsFolder() & vbCrLf & vbCrLf & _
           IIf(Len(cur) > 0, "This document was last formatted with: " & cur, "This document has not been formatted with this add-in yet.") & vbCrLf & vbCrLf & _
           "Apply:   formats the whole active document in place (one Undo step)." & vbCrLf & _
           "Mark as: re-classifies only the selected paragraphs." & vbCrLf & _
           "Add a format: drop a new .ini file into the formats folder and click Refresh.", _
           vbInformation, APP_NAME
End Sub
