"""M10 native host. All module operations share one ProjectContext."""
import argparse
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'scripts/common'), str(ROOT/'scripts/m10')]
from workflow import ProjectContext, MODULES
from native_workbench import NativeWorkbench
from ui_components import install_theme


class ControlCenter:
    def __init__(self, root, project_root=None, workbench_library=None, startup_check=False):
        self.root = root
        self.project = Path(project_root or ROOT).resolve()
        self.project_context = None
        self.native_workbench = None
        install_theme(root)
        root.title('Pony Pose Search · M10')
        root.geometry('1380x880')
        root.minsize(1100, 720)
        self.header = ttk.LabelFrame(root, text='项目与资料库', padding=(6,3))
        self.header.pack(fill='x',padx=6,pady=(4,2))
        ttk.Button(self.header, text='切换资料库…', command=self.choose_library, style='Quiet.TButton').pack(side='right')
        self.summary = tk.StringVar(root)
        ttk.Button(self.header, textvariable=self.summary, style='Quiet.TButton',
                   command=lambda:self.native_workbench.details('当前资料库',str(self.project_context.library.root))).pack(side='left', padx=3)
        self.module_status_vars = {mid: tk.StringVar(root) for mid in MODULES}
        self.open_library(workbench_library)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def open_library(self, path):
        if self.native_workbench:
            self.native_workbench.clean()
        context = ProjectContext(self.project, path)
        try:
            view = NativeWorkbench(self.root, self.project, context=context)
        except Exception:
            context.close()
            raise
        if self.native_workbench:
            self.native_workbench.close()
            self.native_workbench.destroy()
            self.project_context.close()
        self.project_context, self.native_workbench = context, view
        view.on_change = self._refresh_all_status
        view.pack(fill='both', expand=True)
        self._refresh_all_status()

    def choose_library(self):
        try:
            self.native_workbench.clean()
            path = filedialog.askdirectory(parent=self.root, title='选择现有或新的资料库目录')
            if path:
                self.open_library(path)
        except Exception as exc:
            messagebox.showerror('未切换资料库', str(exc), parent=self.root)

    def _refresh_all_status(self):
        for mid, (state, detail) in self.project_context.statuses().items():
            self.module_status_vars[mid].set(state)
            self.native_workbench.set_module_status(mid, state)
        self.summary.set(str(self.project_context.library.root))

    def close(self):
        if self.native_workbench and not self.native_workbench.can_close():
            return
        if self.native_workbench:
            self.native_workbench.close()
        if self.project_context:
            self.project_context.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='M10 素材与姿态检索，共同资料库')
    parser.add_argument('--project-root', type=Path, default=ROOT)
    parser.add_argument('--library', '--workbench-library', dest='library', type=Path)
    parser.add_argument('--check-ui', action='store_true')
    args = parser.parse_args()
    root = tk.Tk()
    if args.check_ui:
        root.withdraw()
    app = None
    try:
        app = ControlCenter(root, args.project_root, args.library, args.check_ui)
        if args.check_ui:
            root.update()
            print(json.dumps({'m10_native_ui':'ready', 'library':str(app.project_context.library.root),
                              'modules':list(MODULES), 'observations':len(app.native_workbench.rows)}, ensure_ascii=False))
        else:
            root.mainloop()
    finally:
        if app:
            app.native_workbench.close()
            app.project_context.close()
        try:
            root.destroy()
        except tk.TclError:
            pass


if __name__ == '__main__':
    main()
