' ============================================================================
'  DJ Tracks — silent launcher (no console window)
'  For end users. Double-click to start the app with NO CMD window.
'  (Developers can still use iniciar.bat to see the console / tracebacks.)
' ============================================================================

Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' Folder this .vbs lives in.
appDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Prefer pythonw.exe (no console) from the codex runtime; fall back to the
' system "pythonw" on PATH if that exact path doesn't exist.
pyw = "C:\Users\thiba\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
If Not fso.FileExists(pyw) Then
    py = "C:\Users\thiba\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    If fso.FileExists(py) Then
        pyw = py
    Else
        pyw = "pythonw"
    End If
End If

shell.CurrentDirectory = appDir
' 0 = hidden window, False = don't wait for it to finish.
shell.Run """" & pyw & """ -B main.py", 0, False
