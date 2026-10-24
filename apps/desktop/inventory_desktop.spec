# PyInstaller spec: `pyinstaller apps/desktop/inventory_desktop.spec` (run from the repo root after `make install`).
# pyzbar needs the native zbar library on the build machine (brew install zbar / apt install libzbar0).
from PyInstaller.utils.hooks import collect_dynamic_libs

a = Analysis(
    ["inventory_desktop/main.py"],
    pathex=["."],
    binaries=collect_dynamic_libs("pyzbar"),
    hiddenimports=["keyring.backends", "boto3", "botocore"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="InventoryCapture", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="InventoryCapture")
app = BUNDLE(coll, name="InventoryCapture.app", bundle_identifier="com.example.inventorycapture")
