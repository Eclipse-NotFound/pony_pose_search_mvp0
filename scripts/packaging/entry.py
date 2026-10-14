"""Windowed distribution entry: keep diagnostics available without a console."""
import sys
import traceback
from pathlib import Path


def main():
    from app_runtime import user_home
    user_home().mkdir(parents=True, exist_ok=True)
    log = user_home()/'startup.log'
    with log.open('a', encoding='utf-8', buffering=1) as stream:
        sys.stdout = stream
        sys.stderr = stream
        try:
            if len(sys.argv) == 3 and sys.argv[1] == '--smoke-test':
                from release_smoke import run
                run(Path(sys.argv[2]))
            else:
                from control_center import main as launch
                launch()
        except Exception:
            traceback.print_exc(file=stream)
            # Automated checks must fail without leaving an unattended dialog.
            if '--smoke-test' not in sys.argv and '--check-ui' not in sys.argv:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk(); root.withdraw()
                messagebox.showerror('Pony Pose Search 未能启动',
                    str(sys.exception())+'\n\n详细记录已保存到：\n'+str(log), parent=root)
                root.destroy()
            raise SystemExit(1)


if __name__ == '__main__':
    main()
