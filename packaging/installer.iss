; Inno Setup-script: TuningMatchingSetup.exe
; Installeert de portable PyInstaller-build als gewoon Windows-programma:
; startmenu-snelkoppeling, database-initialisatie bij eerste start (wizard),
; geen admin-rechten nodig, uninstaller inbegrepen.

[Setup]
AppId={{8E4B2C1A-77E3-4D2A-9F5B-TUNINGMATCH}}
AppName=TuningMatching
AppVersion=5.0.0
AppPublisher=TuningMatching
DefaultDirName={autopf}\TuningMatching
DefaultGroupName=TuningMatching
OutputBaseFilename=TuningMatchingSetup
OutputDir=dist
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern

[Files]
Source: "dist\TuningMatching\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\TuningMatching"; Filename: "{app}\TuningMatching.exe"
Name: "{group}\TuningMatching CLI"; Filename: "{app}\TuningMatching.exe"; Parameters: "--help"
Name: "{autodesktop}\TuningMatching"; Filename: "{app}\TuningMatching.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Desktopsnelkoppeling maken"; Flags: unchecked

[Run]
Filename: "{app}\TuningMatching.exe"; Description: "TuningMatching starten"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; gebruikersdata (data/, backups/) worden NIET verwijderd: kennis blijft behouden
Type: filesandordirs; Name: "{app}\__pycache__"
