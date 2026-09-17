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
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs, copy_metadata

APP = Path(SPECPATH).resolve().parent / "app_ncts"
GABARIT_REL = "Documentation/skills/ulix-doc-arrivee-ncts/scripts"

datas = [(str(APP / GABARIT_REL / "generate_doc.py"), GABARIT_REL)]
datas += collect_data_files("reportlab")
datas += collect_data_files("docx")
datas += collect_data_files("paddlex")
datas += collect_data_files("paddleocr")
datas += [(str(Path(SPECPATH) / "ocr_models"), "ocr_models")]
# Les vérifications de dépendances de PaddleX utilisent importlib.metadata.
datas += copy_metadata("paddleocr", recursive=True)
datas += copy_metadata("paddlepaddle", recursive=True)
# copy_metadata ne suit pas les dépendances optionnelles ocr-core de PaddleX.
for paquet in ("imagesize", "opencv-contrib-python", "pyclipper", "pypdfium2",
               "python-bidi", "shapely"):
    datas += copy_metadata(paquet, recursive=True)
binaries = collect_dynamic_libs("paddle")
if sys.platform.startswith("linux"):
    # Paddle charge certaines dépendances CPU par leur seul nom (dlopen).
    # Le bootloader cherche dans _internal, pas dans paddle/libs : y placer
    # aussi ces bibliothèques, y compris les .so versionnées.
    binaries += collect_dynamic_libs("paddle", destdir=".",
                                    search_patterns=["lib*.so", "lib*.so.*"])

hiddenimports = (collect_submodules("reportlab")
                 + collect_submodules("ulix_ncts")
                 + ["zxingcpp", "PIL.Image", "docx", "runpy", "paddleocr", "paddle",
                    "unittest", "unittest.mock"])

a = Analysis(
    [str(APP / "lancer.py")],
    pathex=[str(APP)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Paddle utilise unittest à l'exécution sur Windows : ne pas l'exclure.
    excludes=["tkinter", "pytest", "PyInstaller"],
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
