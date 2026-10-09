"""Windows taskbar identity, shared by the process and installed shortcuts."""
import ctypes as c
from pathlib import Path
import uuid

APP_ID = 'RhinoConverter.Desktop'


class GUID(c.Structure):
    _fields_ = [('data', c.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__()
        self.data[:] = uuid.UUID(value).bytes_le


class PROPERTYKEY(c.Structure):
    _fields_ = [('fmtid', GUID), ('pid', c.c_ulong)]


class VariantValue(c.Union):
    _fields_ = [('text', c.c_void_p), ('storage', c.c_ubyte * 16)]


class PROPVARIANT(c.Structure):
    _fields_ = [('vt', c.c_ushort), ('reserved', c.c_ushort * 3), ('value', VariantValue)]


def checked(result):
    if result < 0:
        raise OSError(f'Windows taskbar identity failed (HRESULT 0x{result & 0xffffffff:08x}).')


def configure_process():
    shell = c.WinDLL('shell32')
    setter = shell.SetCurrentProcessExplicitAppUserModelID
    setter.argtypes = [c.c_wchar_p]
    setter.restype = c.c_long
    checked(setter(APP_ID))


def current_process_id():
    shell, ole = c.WinDLL('shell32'), c.WinDLL('ole32')
    getter = shell.GetCurrentProcessExplicitAppUserModelID
    getter.argtypes = [c.POINTER(c.c_void_p)]
    getter.restype = c.c_long
    ole.CoTaskMemFree.argtypes = [c.c_void_p]
    pointer = c.c_void_p()
    checked(getter(c.byref(pointer)))
    try:
        return c.wstring_at(pointer)
    finally:
        ole.CoTaskMemFree(pointer)


def method(pointer, index, *types):
    table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
    return c.WINFUNCTYPE(c.c_long, c.c_void_p, *types)(table[index])


def register_shortcut(path):
    """Stamp only an existing converter link; do not change its target or icon."""
    path = Path(path).resolve(strict=True)
    if path.name != 'Rhino Converter.lnk':
        raise ValueError('Expected an existing Rhino Converter.lnk shortcut.')
    ole = c.WinDLL('ole32')
    ole.CoInitializeEx.argtypes = [c.c_void_p, c.c_ulong]
    ole.CoInitializeEx.restype = c.c_long
    checked(ole.CoInitializeEx(None, 2))
    ole.CoCreateInstance.argtypes = [c.POINTER(GUID), c.c_void_p, c.c_ulong,
                                    c.POINTER(GUID), c.POINTER(c.c_void_p)]
    ole.CoCreateInstance.restype = c.c_long
    persist, store = c.c_void_p(), c.c_void_p()
    try:
        clsid = GUID('00021401-0000-0000-c000-000000000046')
        iid_persist = GUID('0000010b-0000-0000-c000-000000000046')
        checked(ole.CoCreateInstance(c.byref(clsid), None, 1, c.byref(iid_persist), c.byref(persist)))
        checked(method(persist, 5, c.c_wchar_p, c.c_ulong)(persist, str(path), 2))
        iid_store = GUID('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
        checked(method(persist, 0, c.POINTER(GUID), c.POINTER(c.c_void_p))(
            persist, c.byref(iid_store), c.byref(store)))
        key = PROPERTYKEY(GUID('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'), 5)
        text = c.create_unicode_buffer(APP_ID)
        variant = PROPVARIANT()
        variant.vt = 31  # VT_LPWSTR; keep text alive through SetValue/Commit.
        variant.value.text = c.cast(text, c.c_void_p).value
        checked(method(store, 6, c.POINTER(PROPERTYKEY), c.POINTER(PROPVARIANT))(
            store, c.byref(key), c.byref(variant)))
        checked(method(store, 7)(store))
        checked(method(persist, 6, c.c_wchar_p, c.c_int)(persist, str(path), 1))
    finally:
        if store:
            method(store, 2)(store)
        if persist:
            method(persist, 2)(persist)
        ole.CoUninitialize()
    shell = c.WinDLL('shell32')
    shell.SHChangeNotify.argtypes = [c.c_long, c.c_uint, c.c_void_p, c.c_void_p]
    shell.SHChangeNotify(0x2000, 0x1005, c.cast(c.c_wchar_p(str(path)), c.c_void_p), None)
