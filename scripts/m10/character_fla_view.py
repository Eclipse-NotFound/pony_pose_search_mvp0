"""A small M01 dialog for character FLA timelines and their exported pictures."""
import tkinter as tk
from tkinter import ttk

from multispecies.catalog import require
from ui_components import Toolbar, position_caption


class CharacterFlaWindow(tk.Toplevel):
    def __init__(self, view, file_id, timeline_id=None):
        super().__init__(view)
        self.view, self.file_id = view, file_id
        self.characters = view.session.context.characters
        self.selected_timeline = timeline_id
        self.manifest = None
        self.timelines = {}
        self.exported = {}
        self.title('角色工程 · 时间轴与画面')
        self.geometry('860x680')
        self.minsize(620, 440)
        self.transient(view.winfo_toplevel())
        box = ttk.Frame(self, padding=10); box.pack(fill='both', expand=True)
        file = view.session.sources.file(file_id)
        ttk.Label(box, text=file['name'], style='Title.TLabel').pack(anchor='w')
        self.notice = tk.StringVar(self, '正在检查工程时间轴…')
        note = ttk.Label(box, textvariable=self.notice, wraplength=810, style='Muted.TLabel')
        note.pack(fill='x', pady=6)
        note.bind('<Configure>', lambda e: note.configure(wraplength=max(100, e.width)))
        bar = Toolbar(box); bar.pack(fill='x')
        self.show_all = tk.BooleanVar(self, False)
        ttk.Checkbutton(bar, text='显示全部时间轴（含零件）', variable=self.show_all,
                        command=lambda: view.guard(self.refresh_timelines)).pack(side='left')
        view.button(bar, '重新检查', lambda: self.inspect(refresh=True))
        self.timeline_tree = view.tree(box, {'name': ('时间轴', 270), 'kind': ('类型', 70),
            'count': ('总帧数', 65), 'reason': ('建议及依据', 300)}, height=7)
        self.timeline_tree.bind('<<TreeviewSelect>>', lambda e: view.guard(self.select_timeline))
        controls = Toolbar(box); controls.pack(fill='x', pady=7)
        self.start = tk.StringVar(self, '1'); self.stop = tk.StringVar(self, '1'); self.step = tk.StringVar(self, '1')
        for title, value in [('起始帧', self.start), ('结束帧', self.stop), ('步长', self.step)]:
            field = ttk.Frame(controls); field.pack(side='left')
            ttk.Label(field, text=title).pack(side='left')
            ttk.Entry(field, textvariable=value, width=6).pack(side='left', padx=4)
        self.export_button = view.button(controls, '导出并建立待筛候选', self.queue_export)
        self.export_button.configure(state='disabled')
        ttk.Label(box, text='帧号从 1 开始；默认逐帧。导出画面先进入 M02 筛选，不自动认定完整角色。',
                  style='Muted.TLabel', wraplength=800).pack(fill='x', pady=(0, 7))
        ttk.Label(box, text='当前时间轴已导出的画面', style='Section.TLabel').pack(anchor='w')
        self.positions_tree = view.tree(box, {'position': ('工程位置', 600)}, height=6)
        self.positions_tree.bind('<Double-1>', lambda e: view.guard(self.open_position))
        actions = Toolbar(box); actions.pack(fill='x', pady=(7, 0))
        view.button(actions, '刷新已导出画面', self.refresh_positions)
        view.button(actions, '打开所选画面', self.open_position)
        view.button(actions, '进入 M02 筛选', self.open_candidates)
        self.inspect()

    def inspect(self, refresh=False):
        self.view.run('正在检查角色 FLA 的时间轴…',
                      lambda: self.characters.inspect(self.file_id, **({'refresh':True} if refresh else {})), self.inspected)

    def inspected(self, manifest):
        if not self.winfo_exists():
            return
        self.manifest = manifest
        self.timelines = {item['id']: item for item in manifest.get('timelines', [])}
        renderer = manifest.get('renderer') or {}
        notes = list(manifest.get('warnings') or [])
        if renderer.get('available'):
            notes.append('Animate 若询问 JSFL 打开方式，请选择“作为命令运行”；旧版工程还可能出现转换提示。')
        notes.insert(0, '可导出工程画面。' if renderer.get('available') else
                     '暂不能导出：' + (renderer.get('reason') or '工程渲染组件尚未就绪。'))
        if not self.timelines:
            notes.append('尚未读到可选择的时间轴。')
        elif not any(item.get('suggested') for item in self.timelines.values()):
            notes.append('未找到明确推荐项，已显示全部；请选择完整角色所在的时间轴。')
        self.notice.set('\n'.join(str(note) for note in notes))
        self.refresh_timelines()

    def refresh_timelines(self):
        previous = self.selected_timeline
        if previous is None:
            # Reopening an imported template should show its usable pictures first.
            existing = self.characters.positions(self.file_id)
            previous = next((row['payload']['timeline_id'] for row in existing
                             if row['payload']['timeline_id'] in self.timelines), None)
        self.timeline_tree.delete(*self.timeline_tree.get_children())
        recommended = any(item.get('suggested') for item in self.timelines.values())
        rows = [item for item in self.timelines.values()
                if self.show_all.get() or not recommended or item.get('suggested') or item['id'] == previous]
        for item in rows:
            kind = '元件' if item['kind'] == 'symbol' else '场景'
            reason = ('优先预览 · ' if item.get('suggested') else '') + (item.get('reason') or '')
            self.timeline_tree.insert('', 'end', iid=item['id'],
                values=(item['name'], kind, item['frame_count'], reason))
        if rows:
            selected = previous if previous and self.timeline_tree.exists(previous) else rows[0]['id']
            self.timeline_tree.selection_set(selected)
            self.select_timeline()
        else:
            self.selected_timeline = None
            self.export_button.configure(state='disabled')
            self.refresh_positions()

    def select_timeline(self):
        selected = self.timeline_tree.selection()
        if not selected:
            return
        changed = self.selected_timeline != selected[0]
        self.selected_timeline = selected[0]
        item = self.timelines[self.selected_timeline]
        if changed or self.stop.get() == '1':
            self.start.set('1'); self.stop.set(str(item['frame_count'])); self.step.set('1')
        available = bool((self.manifest or {}).get('renderer', {}).get('available'))
        self.export_button.configure(state='normal' if available and item['frame_count'] > 0 else 'disabled')
        self.refresh_positions()

    def refresh_positions(self):
        rows = self.characters.positions(self.file_id, timeline_id=self.selected_timeline)
        self.exported = {item['id']: item for item in rows}
        self.positions_tree.delete(*self.positions_tree.get_children())
        for item in rows:
            self.positions_tree.insert('', 'end', iid=item['id'], values=(position_caption(item['payload']),))
        if rows:
            self.positions_tree.selection_set(rows[0]['id'])

    def queue_export(self):
        require(self.selected_timeline, '请先选择一个时间轴。')
        renderer = (self.manifest or {}).get('renderer') or {}
        require(renderer.get('available'), renderer.get('reason') or '工程渲染组件尚未就绪。')
        args = dict(start=int(self.start.get()), stop=int(self.stop.get()), step=int(self.step.get()))
        require(1 <= args['start'] <= args['stop'] <= self.timelines[self.selected_timeline]['frame_count'],
                '起止帧须位于所选时间轴内，且结束帧不小于起始帧。')
        require(args['step'] >= 1, '步长至少为 1 帧。')
        fid, tid, actor = self.file_id, self.selected_timeline, self.view.actor.get()
        def queued(jid):
            if self.winfo_exists():
                self.notice.set('导出已排队。任务完成后刷新已导出画面，或进入 M02 筛选；进度见任务页。')
            self.view.status.set('角色工程导出已排队；暂停中的队列需先继续处理。')
        self.view.run('正在安排角色工程导出…',
                      lambda: self.characters.queue_export(fid, tid, actor=actor, **args), queued)

    def open_position(self):
        selected = self.positions_tree.selection()
        require(selected, '请先选择一个已导出的画面；任务完成后可点击刷新。')
        self.view.clean()
        self.view.source_generation += 1
        self.view.show_position(selected[0])
        self.view.open_module('M01')
        self.withdraw()

    def open_candidates(self):
        self.view.open_module('M02')
        self.withdraw()
