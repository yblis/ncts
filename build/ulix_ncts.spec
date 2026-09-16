# -*- mode: python ; coding: utf-8 -*-
"""Spécification PyInstaller de l'exécutable « ulix-ncts » (mode dossier).

Lancée par build/construire.py depuis app_ncts/ :
    python -m PyInstaller --noconfirm --clean ../build/ulix_ncts.spec

Le gabarit generate_doc.py est embarqué comme fichier de données au chemin
relatif attendu par render.trouver_gabarit (GABARIT_REL). reportlab, python-docx
et zxing-cpp sont collectés en entier : polices, gabarits .docx et extension
compilée compris.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

APP = Path(SPECPATH).resolve().parent / "app_ncts"
GABARIT_REL = "Documentation/skills/ulix-doc-arrivee-ncts/scripts"

datas = [(str(APP / GABARIT_REL / "generate_doc.py"), GABARIT_REL)]
datas += collect_data_files("reportlab")
datas += collect_data_files("docx")

hiddenimports = (collect_submodules("reportlab")
                 + collect_submodules("ulix_ncts")
                 + ["zxingcpp", "PIL.Image", "docx", "runpy"])

a = Analysis(
    [str(APP / "lancer.py")],
    pathex=[str(APP)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pytest", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ulix-ncts",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="app",
)
