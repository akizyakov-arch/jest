"""PyInstaller entry: dispatch watchdog children before importing the UI."""
import multiprocessing
import os
import sys

if __name__ == '__main__':
    for stream in ('stdout', 'stderr'):
        if getattr(sys,stream) is None:
            setattr(sys,stream,open(os.devnull,'w',encoding='utf-8'))
    multiprocessing.freeze_support()
    from gesture_control.portable import main
    raise SystemExit(main())
