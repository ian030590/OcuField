import ctypes
from ctypes import wintypes
import os
from subprocess import list2cmdline
from uuid import uuid4

import win32api
import win32con
import win32event
import win32process
import win32service

DESKTOP_ENV = 'OCUFIELD_SELF_TEST_DESKTOP'
DESKTOP_PREFIX = 'OcuField-'


def run_on_private_desktop(command):
    name = DESKTOP_PREFIX + uuid4().hex
    original = win32service.GetThreadDesktop(win32api.GetCurrentThreadId())
    access = win32con.DESKTOP_CREATEWINDOW | win32con.DESKTOP_READOBJECTS
    desktop = win32service.CreateDesktop(name, 0, access, None)
    try:
        current = win32service.GetThreadDesktop(win32api.GetCurrentThreadId())
        if int(current) == int(desktop):
            original.SetThreadDesktop()
        startup = win32process.STARTUPINFO()
        startup.lpDesktop = name
        startup.dwFlags = win32con.STARTF_FORCEOFFFEEDBACK
        environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
        environment[DESKTOP_ENV] = name
        process, thread, _, _ = win32process.CreateProcess(
            command[0], list2cmdline(command), None, None, False,
            win32con.CREATE_NO_WINDOW, environment, None, startup,
        )
        try:
            thread.Close()
            win32event.WaitForSingleObject(process, win32event.INFINITE)
            return win32process.GetExitCodeProcess(process)
        finally:
            process.Close()
    finally:
        desktop.CloseDesktop()


def require_private_desktop(expected):
    desktop = win32service.GetThreadDesktop(win32api.GetCurrentThreadId())
    if not expected.startswith(DESKTOP_PREFIX) or win32service.GetUserObjectInformation(desktop, win32con.UOI_NAME) != expected:
        raise RuntimeError('Hidden self-test did not start on its private Windows desktop.')
    get_info = ctypes.WinDLL('user32', use_last_error=True).GetUserObjectInformationW
    get_info.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPDWORD)
    is_input_desktop = wintypes.BOOL()
    uoi_io = 6
    if not get_info(int(desktop), uoi_io, ctypes.byref(is_input_desktop), ctypes.sizeof(is_input_desktop), None):
        raise ctypes.WinError(ctypes.get_last_error())
    if is_input_desktop.value:
        raise RuntimeError('Hidden self-test desktop is receiving user input.')
