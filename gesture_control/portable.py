"""Portable paths are relative to the executable, never the working directory."""
from pathlib import Path
import sys


def arguments(argv, home):
    args=list(argv)
    def has(option):
        return any(a==option or a.startswith(option+'=') for a in args)
    if not any(has(option) for option in ('--gui','--demo','--preview','--control','--download-model','--help','-h')):
        args.insert(0,'--gui')
    for option,path in (('--config',home/'settings.user.json'),('--log-dir',home/'logs')):
        if not has(option):
            args.extend((option,str(path)))
    return args


def main():
    home=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    if '--self-test' in sys.argv[1:]:
        from .portable_check import run
        return run(home/'self-test.json')
    from .app import main as application
    return application(arguments(sys.argv[1:],home))
