Option Explicit

Dim application, shell, fileSystem, scriptDirectory, command, arguments, argument, quote, message

Set application = CreateObject("Shell.Application")
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
scriptDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)

quote = Chr(34)
command = "set WINDOW_AUTO_HIDDEN=1&& call " & quote & scriptDirectory & "\start.bat" & quote
For Each argument In WScript.Arguments
    command = command & " " & quote & Replace(argument, quote, quote & quote) & quote
Next
arguments = "/d /s /c " & quote & command & quote

If WScript.Arguments.Count = 1 Then
    If WScript.Arguments(0) = "--validate-only" Then
        WScript.Echo arguments
        WScript.Quit 0
    End If
End If

On Error Resume Next
application.ShellExecute shell.ExpandEnvironmentStrings("%ComSpec%"), _
                         arguments, scriptDirectory, "runas", 0
If Err.Number <> 0 Then
    message = "Unable to start Window Auto with administrator privileges." & vbCrLf
    message = message & "Allow the UAC prompt when the target application requires elevation." & vbCrLf
    message = message & "Error: " & Err.Description
    Call MsgBox(message, vbCritical, "Window Auto startup failed")
End If
On Error GoTo 0
WScript.Quit 0
