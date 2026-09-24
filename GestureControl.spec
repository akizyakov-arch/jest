# Windows x64 onedir distribution; model is bundled for offline use.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

root=Path(SPECPATH)
mp_data,mp_binaries,mp_hidden=collect_all('mediapipe')
datas=mp_data+collect_data_files('gesture_control')+[(str(root/'settings.example.json'),'.')]
a=Analysis([str(root/'portable_entry.py')],pathex=[str(root)],binaries=mp_binaries,datas=datas,
    hiddenimports=mp_hidden+['pystray._win32','cv2_enumerate_cameras.windows_backend'],
    excludes=['pytest','IPython','jupyter','torch','tensorflow'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='GestureControl',console=False,
    debug=False,strip=False,upx=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='GestureControl')
