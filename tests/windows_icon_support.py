import ctypes as c
from ctypes import wintypes as w
import struct

u = c.WinDLL('user32', use_last_error=True)
g = c.WinDLL('gdi32', use_last_error=True)
u.GetParent.argtypes = [w.HWND]; u.GetParent.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND,w.UINT,w.WPARAM,w.LPARAM]; u.SendMessageW.restype = c.c_ssize_t
u.LoadImageW.argtypes = [w.HINSTANCE,w.LPCWSTR,w.UINT,c.c_int,c.c_int,w.UINT]; u.LoadImageW.restype = w.HANDLE
u.DrawIconEx.argtypes = [w.HDC,c.c_int,c.c_int,w.HICON,c.c_int,c.c_int,w.UINT,w.HBRUSH,w.UINT]
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateDIBSection.argtypes = [w.HDC,c.c_void_p,w.UINT,c.POINTER(c.c_void_p),w.HANDLE,w.DWORD]; g.CreateDIBSection.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC,w.HANDLE]; g.SelectObject.restype = w.HANDLE
g.DeleteObject.argtypes = [w.HANDLE]
g.DeleteDC.argtypes = [w.HDC]
u.DestroyIcon.argtypes = [w.HICON]
u.GetClassLongPtrW.argtypes = [w.HWND,c.c_int]; u.GetClassLongPtrW.restype = c.c_size_t

def pixels(icon, size):
    assert icon
    dc = g.CreateCompatibleDC(None)
    header = c.create_string_buffer(struct.pack('<IiiHHIIiiII',40,size,-size,1,32,0,size*size*4,0,0,0,0))
    bits = c.c_void_p()
    bitmap = g.CreateDIBSection(dc,header,0,c.byref(bits),None,0)
    old = g.SelectObject(dc,bitmap)
    c.memset(bits,0,size*size*4)
    assert u.DrawIconEx(dc,0,0,icon,size,size,0,None,3)
    value = c.string_at(bits,size*size*4)
    g.SelectObject(dc,old); g.DeleteObject(bitmap); g.DeleteDC(dc)
    return value
