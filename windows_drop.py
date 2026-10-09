"""Windows Explorer file drops without another Python package or CAD install."""
import ctypes
from ctypes import wintypes
import os


class WindowsFileDrop:
    def __init__(self, widget, deliver):
        if os.name != 'nt':
            raise OSError('Explorer file drops are available on Windows.')
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.shell32 = ctypes.WinDLL('shell32', use_last_error=True)
        self.user32.GetParent.argtypes = [wintypes.HWND]
        self.user32.GetParent.restype = wintypes.HWND
        self.window = self.user32.GetParent(widget.winfo_id()) or widget.winfo_id()
        self.set_proc = self.user32.SetWindowLongPtrW
        self.set_proc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.set_proc.restype = ctypes.c_ssize_t
        self.user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        self.user32.CallWindowProcW.restype = ctypes.c_ssize_t
        self.shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        self.shell32.DragAcceptFiles.restype = None
        self.shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        self.shell32.DragQueryFileW.restype = wintypes.UINT
        self.shell32.DragFinish.argtypes = [wintypes.HANDLE]
        self.shell32.DragFinish.restype = None
        signature = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t)

        def procedure(hwnd, message, wparam, lparam):
            if message == 0x0233:  # WM_DROPFILES
                try:
                    count = self.shell32.DragQueryFileW(wparam, 0xffffffff, None, 0)
                    paths = []
                    for index in range(count):
                        length = self.shell32.DragQueryFileW(wparam, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        self.shell32.DragQueryFileW(wparam, index, buffer, length + 1)
                        paths.append(buffer.value)
                    # Queue only; Tk widgets are updated by the event loop.
                    deliver(paths)
                finally:
                    self.shell32.DragFinish(wparam)
                return 0
            return self.user32.CallWindowProcW(self.original, hwnd, message, wparam, lparam)

        self.callback = signature(procedure)  # retain for the whole window lifetime
        ctypes.set_last_error(0)
        self.original = self.set_proc(self.window, -4, ctypes.cast(self.callback, ctypes.c_void_p).value)
        if not self.original and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        self.shell32.DragAcceptFiles(self.window, True)
        self.active = True

    def close(self):
        if self.active:
            self.shell32.DragAcceptFiles(self.window, False)
            self.set_proc(self.window, -4, self.original)
            self.active = False
