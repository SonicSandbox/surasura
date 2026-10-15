; Surasura's installer (S3.1 D1, D2, D8): Inno Setup 6.7.3, for the current user only, no admin prompt ever.
; Compiled by `python package_app.py --installer`, which passes every define below (a test build's own AppId, name,
; folder and data folder name, so a test install never meets a real one). Compiled by hand, the defaults below are
; the real program's; AppVersion must be given.
;
; It installs dist\Surasura as built into %LOCALAPPDATA%\Programs\<folder> (no folder page: the folder is always
; ours, so the uninstaller may name what it removes), asks one thing (the library folder) and writes the answer to
; %LOCALAPPDATA%\Houseki\<data name>\library.json; it never creates the library folder (Surasura does, at its first
; start). Uninstalling removes the program only: never the library, the settings or the Houseki folders.

#ifndef AppVersion
  #error Pass /DAppVersion=<version> (python package_app.py --installer does)
#endif
#ifndef AppGuid
  #define AppGuid "0EF53F4A-4995-48AA-A8EA-91649B265D82"
#endif
#ifndef AppName
  #define AppName "Surasura"
#endif
#ifndef AppFolder
  #define AppFolder "Surasura"
#endif
#ifndef DataName
  #define DataName "Surasura"
#endif
#ifndef ProgramDir
  #define ProgramDir AddBackslash(SourcePath) + "..\dist\Surasura"
#endif

[Setup]
; {{ is a literal brace: the AppId is {<GUID>}, the uninstall key <AppId>_is1.
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=SonicSandbox
AppPublisherURL=https://github.com/SonicSandbox/surasura
; The name in Windows' installed-apps list never carries a version (a one-click update moves only DisplayVersion).
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\Surasura.exe
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppFolder}
DisableDirPage=yes
UsePreviousAppDir=no
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Every Surasura program holds <data name>.Running while it runs; Setup and the uninstaller wait for it. Restart
; Manager never closes Surasura: it closes itself, on its own terms (D7).
AppMutex={#DataName}.Running
SetupMutex={#DataName}.Setup
CloseApplications=no
Compression=lzma2
SolidCompression=yes
OutputDir=..\dist
OutputBaseFilename=Surasura-{#AppVersion}-setup
SetupIconFile=..\app\assets\images\app_icon.ico
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; ignoreversion: a file a one-click update left newer than this installer's is still replaced (E3).
Source: "{#ProgramDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Surasura.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\Surasura.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: postinstall skipifsilent nowait

[UninstallDelete]
; What a one-click update may have added that Setup never logged: exactly these, never a wildcard on {app} (E2).
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\Surasura.exe"
Type: files; Name: "{app}\surasura-cli.exe"
Type: files; Name: "{app}\updater.exe"
Type: files; Name: "{app}\RELEASE_NOTES.md"
Type: files; Name: "{app}\LICENSE"

[Code]
const
  // The library's name in Documents when Documents\Surasura holds a program (a 2.x unzipped there; IK-1).
  // app/import_2x.py's LIBRARY_FALLBACK says the same.
  LibraryFallback = 'Surasura Library';

var
  LibraryPage: TInputDirWizardPage;
  KeepNote: Boolean;        { an upgrade with no /LIBRARY=: library.json stays as it is }
  NoteFailed: Boolean;

function LibraryNote: String;
begin
  Result := ExpandConstant('{localappdata}\Houseki\{#DataName}\library.json');
end;

function LibraryParam: String;
begin
  Result := Trim(ExpandConstant('{param:LIBRARY|}'));
end;

function HasLibraryNote: Boolean;
var
  Text: AnsiString;
begin
  Result := False;
  if FileExists(LibraryNote) then
    if LoadStringFromFile(LibraryNote, Text) then
      Result := Pos('"library"', String(Text)) > 0;
end;

{ The library named in library.json, for the uninstaller's last message ('' when it can't be read). }
function NoteLibrary: String;
var
  Text: AnsiString;
  S: String;
  I: Integer;
begin
  Result := '';
  if not LoadStringFromFile(LibraryNote, Text) then
    Exit;
  S := String(Text);
  I := Pos('"library"', S);
  if I = 0 then
    Exit;
  I := I + 9;
  while (I <= Length(S)) and (S[I] <> '"') do
    I := I + 1;
  I := I + 1;
  while (I <= Length(S)) and (S[I] <> '"') do begin
    if (S[I] = '\') and (I < Length(S)) then begin
      I := I + 1;
      if S[I] = 'u' then begin
        Result := Result + Chr(StrToIntDef('$' + Copy(S, I + 1, 4), 63));
        I := I + 4;
      end else
        Result := Result + S[I];
    end else
      Result := Result + S[I];
    I := I + 1;
  end;
end;

{ A JSON string, ASCII only (every other character as \uXXXX), so the file is UTF-8 with no BOM whatever the path. }
function JsonString(const S: String): String;
var
  I, C: Integer;
begin
  Result := '"';
  for I := 1 to Length(S) do begin
    C := Ord(S[I]);
    if (C = 34) or (C = 92) then
      Result := Result + '\' + S[I]
    else if (C < 32) or (C > 126) then
      Result := Result + '\u' + Lowercase(Format('%.4x', [C]))
    else
      Result := Result + S[I];
  end;
  Result := Result + '"';
end;

function LibraryFolder: String;
begin
  Result := RemoveBackslashUnlessRoot(ExpandFileName(Trim(LibraryPage.Values[0])));
end;

// A folder holding a Surasura program (Surasura.exe or _internal: a 2.x unzipped there, or an install) is never a
// library: 3.0 would work on that copy in place. app/import_2x.py's holds_program asks the same.
function HoldsProgram(const Folder: String): Boolean;
begin
  Result := FileExists(AddBackslash(Folder) + 'Surasura.exe') or DirExists(AddBackslash(Folder) + '_internal');
end;

{ '' when the folder can be the library; else why not. }
function LibraryProblem: String;
var
  Folder, Prog: String;
begin
  Result := '';
  if Trim(LibraryPage.Values[0]) = '' then begin
    Result := 'Choose a folder for your library.';
    Exit;
  end;
  Folder := Lowercase(AddBackslash(LibraryFolder));
  Prog := Lowercase(AddBackslash(WizardDirValue));
  if Copy(Folder, 1, Length(Prog)) = Prog then
    Result := 'Your library can''t be inside Surasura''s program folder (' + WizardDirValue + '): updating or ' +
      'uninstalling Surasura replaces that folder. Choose another folder, such as Documents\Surasura.'
  else if HoldsProgram(LibraryFolder) then
    Result := 'That folder holds a Surasura program, not a library. Choose another folder, such as Documents\' +
      LibraryFallback + '.';
end;

function InitializeSetup: Boolean;
begin
  KeepNote := (LibraryParam = '') and HasLibraryNote;
  Result := True;
end;

procedure InitializeWizard;
begin
  LibraryPage := CreateInputDirPage(wpSelectDir, 'Your library', 'Where should Surasura keep your library?',
    'Surasura keeps your books, subtitles, word lists and reports in this folder. It is created when Surasura ' +
    'first starts; a folder that already exists is fine too.' + #13#10#13#10 +
    'To keep using it, click Next. To choose another folder, click Browse.', False, '');
  LibraryPage.Add('');
  if LibraryParam <> '' then
    LibraryPage.Values[0] := LibraryParam
  else if HoldsProgram(ExpandConstant('{userdocs}\Surasura')) then
    LibraryPage.Values[0] := AddBackslash(ExpandConstant('{userdocs}')) + LibraryFallback
  else
    LibraryPage.Values[0] := ExpandConstant('{userdocs}\Surasura');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = LibraryPage.ID) and KeepNote;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Problem: String;
begin
  Result := True;
  if CurPageID = LibraryPage.ID then begin
    Problem := LibraryProblem;
    if Problem <> '' then begin
      SuppressibleMsgBox(Problem, mbError, MB_OK, IDOK);
      Result := False;
    end;
  end;
end;

{ A silent run with a library inside the program folder stops here, before anything is installed. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not KeepNote then
    Result := LibraryProblem;
end;

procedure WriteLibraryNote;
var
  Note, Tmp, Text: String;
begin
  Note := LibraryNote;
  Tmp := Note + '.tmp';
  Text := '{"version": 1, "install": ' + JsonString(ExpandConstant('{app}')) + ', "library": ' +
    JsonString(LibraryFolder) + '}' + #10;
  if not ForceDirectories(ExtractFileDir(Note)) then
    NoteFailed := True
  else if not SaveStringToFile(Tmp, AnsiString(Text), False) then
    NoteFailed := True
  else begin
    if FileExists(Note) then
      DeleteFile(Note);
    if not RenameFile(Tmp, Note) then
      NoteFailed := True;
  end;
  if NoteFailed then begin
    Log('library.json could not be written: ' + Note);
    SuppressibleMsgBox('Surasura could not write ' + Note + '. Run Setup again.', mbError, MB_OK, IDOK);
  end else
    Log('library.json written: ' + Text);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    if KeepNote then
      Log('library.json kept as it is: ' + LibraryNote)
    else
      WriteLibraryNote;
  end;
end;

{ A failed library.json is a failed install for whoever ran Setup silently (the updater reads the exit code). }
function GetCustomSetupExitCode: Integer;
begin
  if NoteFailed then
    Result := 9
  else
    Result := 0;
end;

{ FT K2: has Surasura kept a record of what it changed in Anki - an anki_first_touch folder in the library's
  User Files\<language>\? }
function KeptAnkiRecord: Boolean;
var
  Files: String;
  Rec: TFindRec;
begin
  Result := False;
  if NoteLibrary = '' then
    Exit;
  Files := AddBackslash(NoteLibrary) + 'User Files\';
  if FindFirst(Files + '*', Rec) then begin
    try
      repeat
        if ((Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and (Rec.Name <> '.') and (Rec.Name <> '..') then
          Result := DirExists(Files + Rec.Name + '\anki_first_touch');
      until Result or not FindNext(Rec);
    finally
      FindClose(Rec);
    end;
  end;
end;

{ FT K2: asked before anything is removed, only when that record exists - once Surasura is gone, nothing can put
  Anki back. Yes goes on; No (the default, C23: Enter keeps Surasura) stops the uninstall. Both doors are named (C23).
  Characters: $2026 is ..., $9806 is Junban's mark, $2192 is the arrow (a line here never starts with #: ISPP reads it). }
function InitializeUninstall: Boolean;
begin
  Result := True;
  if UninstallSilent or not KeptAnkiRecord then
    Exit;
  Result := MsgBox('Surasura changed your Anki cards, and kept a record of how they were.' + #13#10#13#10 +
    'To put Anki back the way it was before Surasura, press No, open Surasura and press Put Anki back' + #$2026 +
    ' in ' + #$9806 + ' or in Settings ' + #$2192 + ' Data & System (Anki must be open), then uninstall again.' + #13#10#13#10 +
    'Remove Surasura now?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Lib: String;
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then begin
    Lib := NoteLibrary;
    if Lib = '' then
      Lib := 'the folder you chose when installing (Documents\Surasura unless you changed it)';
    MsgBox('{#AppName} is removed. Everything that is yours was kept, where it is:' + #13#10#13#10 +
      'Your library: ' + Lib + #13#10 +
      'Your settings: ' + ExpandConstant('{userappdata}\Houseki\{#DataName}') + #13#10 +
      'Surasura''s own data (its word index, its logs, and in update\previous the earlier version it kept for Go ' +
      'back): ' + ExpandConstant('{localappdata}\Houseki\{#DataName}') + #13#10#13#10 +
      'Delete these folders yourself if you no longer want them.', mbInformation, MB_OK);
  end;
end;
