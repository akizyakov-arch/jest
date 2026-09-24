"""Temporary standard Windows cursor hiding, owned by the input watchdog."""
import ctypes as ct


class CursorVisibility:
    IDS=(32512,32513,32514,32515,32516,32642,32643,32644,32645,32646,32648,32649,32650)

    def __init__(self, user=None):
        self.user=user if user is not None else ct.WinDLL('user32',use_last_error=True)
        self.hidden=False
        self.originals={}
        if user is None:
            for name,args,result in (
                ('CreateCursor',[ct.c_void_p,ct.c_int,ct.c_int,ct.c_int,ct.c_int,ct.c_void_p,ct.c_void_p],ct.c_void_p),
                ('SetSystemCursor',[ct.c_void_p,ct.c_uint],ct.c_int),
                ('DestroyCursor',[ct.c_void_p],ct.c_int),
                ('LoadCursorW',[ct.c_void_p,ct.c_void_p],ct.c_void_p),
                ('CopyImage',[ct.c_void_p,ct.c_uint,ct.c_int,ct.c_int,ct.c_uint],ct.c_void_p)):
                fn=getattr(self.user,name)
                fn.argtypes,fn.restype=args,result

    def set_hidden(self, hidden):
        if hidden==self.hidden:
            return
        if not hidden:
            for cursor_id,original in self.originals.items():
                copy=self.user.CopyImage(original,2,0,0,0)
                if not copy or not self.user.SetSystemCursor(copy,cursor_id):
                    raise OSError('Cannot restore original Windows cursors')
            for original in self.originals.values():
                self.user.DestroyCursor(original)
            self.originals.clear()
            self.hidden=False
            return
        # Monochrome AND=1/XOR=0 leaves the desktop unchanged (transparent).
        and_mask=(ct.c_ubyte*128)(*([255]*128))
        xor_mask=(ct.c_ubyte*128)()
        try:
            for cursor_id in self.IDS:
                original=self.user.LoadCursorW(None,cursor_id)
                copy=self.user.CopyImage(original,2,0,0,0) if original else None
                if not copy: raise OSError('Cannot save original Windows cursors')
                self.originals[cursor_id]=copy
        except Exception:
            for original in self.originals.values(): self.user.DestroyCursor(original)
            self.originals.clear()
            raise
        self.hidden=True  # Also restore a partially replaced cursor set.
        try:
            for cursor_id in self.IDS:
                cursor=self.user.CreateCursor(None,0,0,32,32,and_mask,xor_mask)
                if not cursor:
                    raise OSError('Cannot create transparent Windows cursor')
                if not self.user.SetSystemCursor(cursor,cursor_id):
                    raise OSError('Cannot hide Windows cursor')
        except Exception:
            self.set_hidden(False)
            raise
