# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Woo's NWN Parser.

To build the executable, run:
    pyinstaller WoosNwnParser.spec

The executable will be created in the 'dist' folder.
"""

import sys
from pathlib import Path
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
    StringStruct, VarFileInfo, VarStruct
)

block_cipher = None

# Define the root directory
root_dir = Path(SPECPATH)

# Create version info
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(1, 0, 0, 0),
        prodvers=(1, 0, 0, 0),
        mask=0x3f,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0)
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    '040904B0',
                    [
                        StringStruct('CompanyName', 'Woo\'s NWN Tools'),
                        StringStruct('FileDescription', 'Woo\'s Neverwinter Nights Combat Log Parser'),
                        StringStruct('FileVersion', '1.0.0.0'),
                        StringStruct('InternalName', 'WoosNwnParser'),
                        StringStruct('LegalCopyright', 'Copyright © 2026 Woo\'s NWN Tools'),
                        StringStruct('OriginalFilename', 'WoosNwnParser.exe'),
                        StringStruct('ProductName', 'Woo\'s NWN Parser'),
                        StringStruct('ProductVersion', '1.0.0.0')
                    ]
                )
            ]
        ),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])
    ]
)

a = Analysis(
    ['app/__main__.py'],
    pathex=[str(root_dir)],
    binaries=[],
    datas=[
        ('ir_attack.ico', '.'),  # Include the icon file
    ],
    hiddenimports=[
        'sv_ttk',  # Sun Valley ttk theme
        'tkinter',
        'tkinter.ttk',
        '_tkinter',
        'queue',
        'threading',
        'pathlib',
        'dataclasses',
        'datetime',
        're',
        'typing',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',  # Exclude if not used
        'numpy',  # Exclude if not used
        'PIL',  # Exclude if not used
        'pytest',  # Exclude test dependencies
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='WoosNwnParser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Compress with UPX if available
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='ir_attack.ico',  # Application icon
    version=version_info,  # Windows file properties/metadata
)

