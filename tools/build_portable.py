"""Build and verify a fresh portable folder, then create a checksummed ZIP."""
from datetime import datetime
from hashlib import sha256
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    if sys.platform!='win32':
        raise SystemExit('Build on Windows x64 with requirements-cv and requirements-build installed.')
    version=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    output=ROOT/'dist'/stamp
    work=ROOT/'build'/('portable-'+stamp)
    output.mkdir(parents=True,exist_ok=False)
    work.mkdir(parents=True,exist_ok=False)
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',str(output),
                    '--workpath',str(work),str(ROOT/'GestureControl.spec')],cwd=ROOT,check=True)
    folder=output/'GestureControl'
    shutil.copy2(ROOT/'settings.example.json',folder/'settings.example.json')
    shutil.copy2(ROOT/'PORTABLE.md',folder/'README.txt')
    shutil.copy2(ROOT/'ИНСТРУКЦИЯ.md',folder/'ИНСТРУКЦИЯ.md')
    shutil.copy2(ROOT/'requirements-cv-win-py314.lock.txt',folder/'DEPENDENCIES.txt')
    licenses=folder/'THIRD_PARTY_LICENSES'
    licenses.mkdir()
    for distribution in metadata.distributions():
        name=distribution.metadata.get('Name','unknown')
        for entry in distribution.files or ():
            if any(word in entry.name.lower() for word in ('license','copying','notice')):
                source=Path(distribution.locate_file(entry))
                if source.is_file():
                    destination=licenses/name/str(entry).replace('..','_').replace(':','_')
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(source,destination)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.exists():
        shutil.copy2(python_license,licenses/'PYTHON-LICENSE.txt')
    # Check from an unrelated empty directory with Python removed from PATH.
    check_dir=work/'isolated-check'
    check_dir.mkdir()
    environment=os.environ.copy()
    for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'):
        environment.pop(key,None)
    environment['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
    executable=folder/'GestureControl.exe'
    print('Checking standalone executable (no camera or real input)...',flush=True)
    result=subprocess.run([str(executable),'--self-test'],cwd=check_dir,env=environment,
                          timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
    report=folder/'self-test.json'
    if result.returncode or not report.exists() or not json.loads(report.read_text(encoding='utf-8')).get('ok'):
        raise SystemExit('Portable check failed: '+str(report))
    report.rename(folder/'SELF_TEST_REPORT.json')
    files=sorted(p for p in folder.rglob('*') if p.is_file())
    manifest='\n'.join(sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(folder).as_posix() for p in files)+'\n'
    (folder/'SHA256SUMS.txt').write_text(manifest,encoding='utf-8')
    archive=output/f'Gesture-Control-{version}-win64.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                bundle.write(path,Path('GestureControl')/path.relative_to(folder))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
    digest=sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n',encoding='utf-8')
    print(json.dumps({'folder':str(folder),'zip':str(archive),'sha256':digest,
                      'size_mb':round(archive.stat().st_size/1024**2,1)},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
