; ULIX — annonce d'arrivée NCTS : installateur Windows (Inno Setup 6).
; Compilé par build/construire.py :
;   ISCC /DVersion=1.2.0 /DSource=dist\ULIX NCTS /DSortie=dist build\installateur_windows.iss
;
; Installation SANS droits administrateur, dans les Documents de l'utilisateur :
; le dossier installé est directement le dossier PROJET (dépôts + programme),
; comme « hermes/ » en développement. Les dépôts et le .env ne sont jamais
; supprimés à la désinstallation.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Source
  #define Source "..\dist\ULIX NCTS"
#endif
#ifndef Sortie
  #define Sortie "..\dist"
#endif

[Setup]
AppId={{7C1E4B2A-5D9F-4E3B-9A6C-3F2A1B0C9D8E}
AppName=ULIX NCTS
AppVersion={#Version}
AppVerName=ULIX NCTS {#Version}
AppPublisher=ULIX SWISS SA
DefaultDirName={userdocs}\ULIX NCTS
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
OutputDir={#Sortie}
OutputBaseFilename=ULIX-NCTS-{#Version}-windows-installateur
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallFilesDir={app}\app
UninstallDisplayName=ULIX NCTS (annonce d'arrivée)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "bureau"; Description: "Créer un raccourci « ULIX NCTS » sur le Bureau"; GroupDescription: "Raccourcis :"
Name: "demarrage"; Description: "Lancer la surveillance des dépôts en arrière-plan à l'ouverture de session"; GroupDescription: "Raccourcis :"; Flags: unchecked

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\data\Dépôts unique"; Flags: uninsneveruninstall
Name: "{app}\data\Dépôts multiple"; Flags: uninsneveruninstall
Name: "{app}\data\Annonces d'arrivées"; Flags: uninsneveruninstall
Name: "{app}\data\Archive"; Flags: uninsneveruninstall

[Files]
Source: "{#Source}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Source}\Lancer.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Source}\Surveiller.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Source}\Surveillance.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Source}\LISEZMOI.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme
; réglages du poste : créé une seule fois, jamais écrasé ni désinstallé
Source: "{#Source}\app\.env.example"; DestDir: "{app}"; DestName: ".env"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\ULIX NCTS - Surveiller les dépôts"; Filename: "{app}\Surveiller.cmd"; WorkingDir: "{app}"; Comment: "Déposer un PDF suffit : l'annonce se génère seule"
Name: "{autoprograms}\ULIX NCTS - Traiter maintenant"; Filename: "{app}\Lancer.cmd"; WorkingDir: "{app}"
Name: "{autoprograms}\ULIX NCTS - Surveillance en arrière-plan"; Filename: "{app}\Surveillance.cmd"; WorkingDir: "{app}"; Comment: "Surveillance invisible, journal dans Surveillance.log"
Name: "{autoprograms}\ULIX NCTS - Arrêter la surveillance"; Filename: "{app}\Surveillance.cmd"; Parameters: "--kill"; WorkingDir: "{app}"
Name: "{autoprograms}\ULIX NCTS - Ouvrir le dossier"; Filename: "{app}"
Name: "{autodesktop}\ULIX NCTS"; Filename: "{app}"; Tasks: bureau
Name: "{userstartup}\ULIX NCTS - Surveillance"; Filename: "{app}\Surveillance.cmd"; WorkingDir: "{app}"; Tasks: demarrage

[Run]
Filename: "{app}\app\ulix-ncts.exe"; Parameters: "--preparer"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; StatusMsg: "Préparation des dossiers de dépôt…"
Filename: "{app}"; Description: "Ouvrir le dossier ULIX NCTS"; Flags: postinstall shellexec skipifsilent nowait
Filename: "notepad.exe"; Parameters: """{app}\.env"""; Description: "Renseigner la clé IA (.env)"; Flags: postinstall skipifsilent nowait unchecked
