import argparse
import ctypes
import os
from pathlib import Path
import sys
import traceback

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))


def block_socket_access(event, args):
    if event in ('socket.connect', 'socket.sendto', 'socket.getaddrinfo',
                 'socket.gethostbyname', 'socket.gethostbyaddr', 'socket.getnameinfo'):
        raise OSError('OcuField runs offline')


def enable_per_monitor_dpi():
    user32 = ctypes.windll.user32
    user32.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
    user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.AreDpiAwarenessContextsEqual.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    context = ctypes.c_void_p(-4)
    user32.SetProcessDpiAwarenessContext(context)
    if not user32.AreDpiAwarenessContextsEqual(user32.GetThreadDpiAwarenessContext(), context):
        raise RuntimeError('無法啟用每螢幕 DPI 感知')


def prepare_tk():
    if getattr(sys, 'frozen', False):
        libraries = {'TCL_LIBRARY': Path(sys._MEIPASS) / '_tcl_data',
                     'TK_LIBRARY': Path(sys._MEIPASS) / '_tk_data'}
    else:
        base = Path(sys.base_prefix) / 'tcl'
        libraries = {'TCL_LIBRARY': base / 'tcl8.6', 'TK_LIBRARY': base / 'tk8.6'}
    for key, path in libraries.items():
        if path.is_dir():
            os.environ[key] = '\\\\?\\' + str(path)


def main():
    sys.addaudithook(block_socket_access)
    for stream in ('stdout', 'stderr'):
        if getattr(sys, stream) is None:
            setattr(sys, stream, open(os.devnull, 'w', encoding='utf-8'))
    parser = argparse.ArgumentParser(prog='OcuField')
    tests = parser.add_mutually_exclusive_group()
    tests.add_argument('--self-test', type=Path, metavar='OUTPUT_DIR', help='Run on a private Windows desktop.')
    tests.add_argument('--self-test-visible', type=Path, metavar='OUTPUT_DIR', help='Run the on-screen timing check.')
    args = parser.parse_args()
    directory = args.self_test or args.self_test_visible
    try:
        if directory is not None:
            directory = directory.resolve()
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'selftest.json').unlink(missing_ok=True)
            error_path = directory / 'selftest-error.txt'
            error_path.unlink(missing_ok=True)
        if args.self_test is not None:
            from ocufield.private_desktop import DESKTOP_ENV, require_private_desktop, run_on_private_desktop

            desktop = os.environ.get(DESKTOP_ENV)
            if desktop is None:
                command = [sys.executable]
                if not getattr(sys, 'frozen', False):
                    command.append(str(Path(__file__).resolve()))
                exit_code = run_on_private_desktop([*command, '--self-test', str(directory)])
                if exit_code and not error_path.exists():
                    error_path.write_text(f'Hidden self-test exited with code {exit_code}.\n', encoding='utf-8')
                return exit_code
            require_private_desktop(desktop)
        enable_per_monitor_dpi()
        from ocufield.experiment import runtime, self_test

        with runtime(directory) as visual:
            if directory is not None:
                self_test(visual, directory, verify_timing=args.self_test_visible is not None)
            else:
                prepare_tk()
                import tkinter as tk
                from ocufield.ui import App

                root = tk.Tk()
                App(root, visual)
                root.mainloop()
        return 0
    except Exception as error:
        traceback.print_exc()
        if directory is not None:
            if directory.is_dir():
                (directory / 'selftest-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        else:
            ctypes.windll.user32.MessageBoxW(None, str(error), '周邊視野訓練', 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
