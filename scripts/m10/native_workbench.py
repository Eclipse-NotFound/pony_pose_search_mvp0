"""Native Tk source catalogue, direction editor and result location panels."""
import copy
from concurrent.futures import ThreadPoolExecutor
import io
import json
import math
import os
from pathlib import Path
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk
from multispecies.catalog import require
from multispecies.records import new_id
from workbench_model import WorkbenchSession

NAMES = dict(core='主干', fore_a='前肢 A', fore_b='前肢 B', hind_a='后肢 A', hind_b='后肢 B',
             wing_a='翼 A', wing_b='翼 B', arm_a='手臂 A', arm_b='手臂 B', leg_a='腿 A', leg_b='腿 B',
             head='头', neck='颈', body='身体', tail='尾根初始方向', upper='上段', middle='中段', lower='下段',
             torso='躯干', torso_a='躯干前段', torso_b='躯干后段', root_to_bend='翼根至转折', bend_to_tip_reference='翼的外伸方向')
PRESENCE = {'unknown':'未确认', 'present':'存在', 'absent':'不存在'}
VISIBILITY = {'unknown':'未知', 'visible':'可见', 'occluded':'被遮挡', 'out_of_frame':'画面外'}
MISSING = {'not_annotated':'尚未标注', 'not_discernible':'无法辨认', 'occluded':'被遮挡', 'out_of_frame':'画面外', 'not_drawn':'未绘制'}
REVIEWS = {'unreviewed':'待审核', 'approved':'已通过', 'corrected':'已修正', 'rejected':'已驳回', 'legacy_official':'原正式标注', 'query_input':'查询输入'}
VIEWS = {'':'未知', 'front':'正面', 'front_oblique':'斜前', 'side':'侧面', 'rear_oblique':'斜后', 'rear':'背面'}
COLLECTIONS = {'all':'全部', 'official':'原正式标注', 'manual':'新增人工标注', 'experimental':'实验／待审', 'query':'查询图片'}
STATES = {'ready':'可用', 'error':'读取失败', 'pending':'等待读取', 'queued':'排队', 'running':'处理中', 'done':'完成', 'failed':'失败'}


def label(key):
    return NAMES.get(key, key)


def readable_location(text):
    for old,new in {'frame_exact':'精确到视频帧', 'timeline_exact':'精确到工程时间轴帧', 'image_exact':'精确到原图', 'time_approx':'只有约略时间',
                    'timeline_exact':'精确到工程时间轴帧',
                    'image_only':'只有留存图片', 'unbound':'尚未绑定原素材', 'available':'可用', 'changed':'原内容已变化', 'missing':'原素材缺失'}.items():
        text=text.replace('：'+old, '：'+new)
    return text


from ui_components import COLORS, install_theme, Toolbar, ScrollPanel, FieldGroup, section, split, dialog_form, position_caption


class Choice(ttk.Combobox):
    """Show labels without exposing IDs in the everyday UI."""
    def __init__(self, parent, items=None, **kwargs):
        super().__init__(parent, state='readonly', **kwargs)
        self.keys = []
        self.set_items(items or {})

    def set_items(self, items, selected=None):
        self.keys = list(items)
        self.configure(values=list(items.values()))
        if self.keys:
            self.current(self.keys.index(selected) if selected in self.keys else 0)
        else:
            self.set('')

    def key(self):
        index = self.current()
        return self.keys[index] if 0 <= index < len(self.keys) else None

    def choose(self, key):
        if key in self.keys:
            self.current(self.keys.index(key))


class Picture(ttk.Frame):
    """Fit an image; translate clicks/drags back to its original pixel coordinates."""
    def __init__(self, parent, callback=None, *, empty='选择记录后查看画面', hint='滚轮缩放 · 中键拖动 · 适应画面可恢复全图'):
        super().__init__(parent)
        self.empty, self.hint = empty, hint
        tools=ttk.Frame(self);tools.pack(side='bottom',fill='x')
        self.zoom_label=ttk.Label(tools,text='画面预览',style='Muted.TLabel')
        self.zoom_label.pack(side='left',padx=6)
        ttk.Button(tools,text='适应画面',style='Compact.TButton',command=self.fit).pack(side='right')
        ttk.Button(tools,text='100%',style='Compact.TButton',command=self.actual_size).pack(side='right')
        self.canvas = tk.Canvas(self, background=COLORS['canvas'], highlightthickness=1,
                                highlightbackground=COLORS['line'], width=200, height=160, takefocus=True)
        self.canvas.pack(fill='both', expand=True)
        self.image = None
        self.photo = None
        self.scale, self.offset = 1, (0, 0)
        self.lines = {}
        self.points = {}
        self.zoom = 1.
        self.pan = [0., 0.]
        self.active = None
        self.region = None
        self.callback = callback
        self.start = self.first = self.moving = None
        self.mode = 'direction'
        self.space_pan = False
        self.panning = False
        self.canvas.bind('<Configure>', lambda e: self.redraw())
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<B2-Motion>', self.drag_pan)
        self._pan_start = None
        self.canvas.bind('<ButtonPress-2>', lambda e:setattr(self,'_pan_start',(e.x,e.y)))
        self.canvas.bind('<Escape>',lambda e:self.fit())
        self.canvas.bind('<KeyPress-space>',lambda e:setattr(self,'space_pan',True))
        self.canvas.bind('<KeyRelease-space>',lambda e:setattr(self,'space_pan',False))
        self.canvas.bind('<FocusOut>',lambda e:setattr(self,'space_pan',False))

    def actual_size(self):
        if self.image:
            fitted=min(max(10,self.canvas.winfo_width())/self.image.width,max(10,self.canvas.winfo_height())/self.image.height)
            self.zoom=1/fitted;self.pan=[0.,0.];self.redraw()

    def fit(self):
        self.zoom=1.;self.pan=[0.,0.];self.first=self.start=self.moving=None
        self.redraw()

    def set_image(self, image):
        self.image = image.copy() if image else None
        self.first = self.start = self.moving = None
        self.lines, self.points, self.region = {}, {}, None
        self.zoom=1.;self.pan=[0.,0.]
        self.redraw()

    def point(self, event):
        if self.image is None:
            return None
        x, y = ((event.x-self.offset[0])/self.scale, (event.y-self.offset[1])/self.scale)
        return [min(self.image.width, max(0., x)), min(self.image.height, max(0., y))]

    def press(self, event):
        self.canvas.focus_set()
        if self.space_pan:
            self.panning=True;self._pan_start=(event.x,event.y);return
        if self.image is not None:
            self.start = self.point(event)

    def motion(self, event):
        if self.panning:
            self.drag_pan(event);return
        if self.start is not None:
            self.moving = self.point(event)
            self.redraw()

    def release(self, event):
        if self.panning:
            self.panning=False;self._pan_start=None;return
        if self.start is None:
            return
        end, start = self.point(event), self.start
        self.start = self.moving = None
        if self.mode == 'point':
            self.first=None
            if self.callback:self.callback(end,end)
            return
        if math.dist(start, end)*self.scale < 5:
            if self.first is None:
                self.first = end
                self.redraw()
                return
            start, self.first = self.first, None
        else:
            self.first = None
        self.redraw()
        if self.callback:
            self.callback(start, end)

    def redraw(self):
        c = self.canvas
        c.delete('all')
        if self.image is None:
            width=max(160,c.winfo_width()-40)
            c.create_text(c.winfo_width()/2, max(35,c.winfo_height()/2-14),
                          text=self.empty, fill='#e6eff2',font=('Microsoft YaHei UI',12,'bold'),width=width)
            c.create_text(c.winfo_width()/2, max(68,c.winfo_height()/2+24),
                          text=self.hint, fill='#adbdc5',font=('Microsoft YaHei UI',9),width=width)
            self.zoom_label.configure(text='尚未载入画面')
            return
        width, height = max(c.winfo_width(), 10), max(c.winfo_height(), 10)
        self.scale = min(width/self.image.width, height/self.image.height)*self.zoom
        self.zoom_label.configure(text=f'{self.image.width} × {self.image.height}  ·  {self.scale:.0%}')
        w, h = max(1, round(self.image.width*self.scale)), max(1, round(self.image.height*self.scale))
        self.offset = ((width-w)/2+self.pan[0], (height-h)/2+self.pan[1])
        self.photo = ImageTk.PhotoImage(self.image.resize((w,h), Image.Resampling.LANCZOS), master=c)
        c.create_image(*self.offset, image=self.photo, anchor='nw')
        def xy(p):
            return [self.offset[0]+p[0]*self.scale, self.offset[1]+p[1]*self.scale]
        for key, pair in self.lines.items():
            color = '#ffb45f' if key == self.active else '#53d6c0'
            c.create_line(*xy(pair['start']), *xy(pair['end']), fill=color, width=3 if key==self.active else 2,
                          arrow='last', arrowshape=(10,12,5))
        from multispecies.keypoints import ORDER
        if self.mode=='point':
            from pose_record import EDGES
            for a,b in EDGES.values():
                if a in self.points and b in self.points:
                    c.create_line(*xy(self.points[a]),*xy(self.points[b]),fill='#53d6c0',width=2)
        for i,(key,point) in enumerate(self.points.items(),1):
            i=ORDER.index(key)+1 if key in ORDER else i
            x,y=xy(point);color='#ffb45f' if key==self.active else '#53d6c0'
            c.create_oval(x-4,y-4,x+4,y+4,fill=color,outline='white')
            c.create_text(x+8,y-7,text=str(i),fill=color,anchor='w')
        if self.region:
            x,y,w,h = self.region
            c.create_rectangle(*xy((x,y)), *xy((x+w,y+h)), outline='#ffb45f', width=2)
        if self.first:
            x,y=xy(self.first)
            c.create_oval(x-4,y-4,x+4,y+4,fill='#ffb45f',outline='')
        if self.start and self.moving:
            if self.mode == 'region':
                c.create_rectangle(*xy(self.start),*xy(self.moving),outline='#ffb45f',width=2)
            else:
                c.create_line(*xy(self.start),*xy(self.moving),fill='#ffb45f',width=3,arrow='last')

    def wheel(self,event):
        if self.image is None:return
        self.zoom=min(6.,max(1.,self.zoom*(1.15 if event.delta>0 else 1/1.15)))
        if self.zoom==1.:self.pan=[0.,0.]
        self.redraw()

    def drag_pan(self,event):
        if self._pan_start:
            self.pan[0]+=event.x-self._pan_start[0];self.pan[1]+=event.y-self._pan_start[1]
            self._pan_start=(event.x,event.y);self.redraw()


class NativeWorkbench(ttk.Frame):
    def __init__(self, parent, project, *, library=None, context=None, on_change=None):
        install_theme(parent)
        super().__init__(parent, padding=0, style='App.TFrame')
        self.session = WorkbenchSession(project, library, context=context)
        self.on_change = on_change
        self.catalog = self.session.library.catalog
        self.busy = self.closed = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='m10-workbench')
        self.messages = queue.Queue()
        self.watched = {}
        self.rows = []
        self.file_id = self.position_id = None
        self.timeline_id = None
        self._character_fla_window = None
        self.source_generation = 0
        self.import_request = None
        self.excludes = []
        self.advanced_source_filters = {'format':'', 'root_id':''}
        self.comparison_options = {}
        self.active_suggestion = None
        self.query_observation = None
        self.offset = 0
        self.actor = tk.StringVar(self, '本机用户')
        self.status = tk.StringVar(self, '就绪：登记素材，或选择已有姿态。')
        self.jobs_status = tk.StringVar(self)
        self.file_count = tk.StringVar(self)
        self.record_state = tk.StringVar(self, '请从左侧选择一份记录')
        self.direction_state = tk.StringVar(self)
        self.roi_text = tk.StringVar(self, '尚未框选角色')
        self.frame_number = tk.StringVar(self, '1')
        self.confirm_region = tk.BooleanVar(self, False)
        self.query_only = tk.BooleanVar(self, False)
        self.mirror = tk.BooleanVar(self, False)
        self.exchange = tk.BooleanVar(self, True)
        self.unreviewed = tk.BooleanVar(self, False)
        self.experimental = tk.BooleanVar(self, False)
        self.draft_contract = tk.BooleanVar(self, False)
        self.strict_identity = tk.BooleanVar(self, False)
        self.source_exact = tk.BooleanVar(self, False)
        self.source_available = tk.BooleanVar(self, False)
        self.source_related = tk.BooleanVar(self, False)
        self._build()
        self.refresh_records()
        self.refresh_sources()
        if self.session.query_id:
            self.restore_query(self.session.workflow.query(self.session.query_id))
        if self.session.last_results:
            self.render_results(self.session.last_results)
        self.session.sources.start()
        self._poll_id = self.after(100, self._poll)
        self._status_id = self.after(1000, self._tick_sources)

    def button(self, parent, text, command, **kwargs):
        style = kwargs.pop('style', 'TButton')
        result = ttk.Button(parent, text=text, style=style, command=lambda: self.guard(command))
        result.pack(**({'side':'left', 'padx':3, 'pady':3} | kwargs))
        return result

    def guard(self, fn):
        try:
            return fn()
        except Exception as exc:
            self.status.set('未完成：'+str(exc))
            messagebox.showerror('素材与姿态工作台', str(exc), parent=self)
            return None

    def run(self, text, task, done=None):
        require(not self.busy, '当前操作尚未完成，请稍候。')
        self.busy = True
        self.progress.pack(side='left',padx=(0,10),before=self.status_label)
        self.progress.start(12)
        self.status.set(text)
        def complete(future):
            try:
                self.messages.put((done, future.result(), None))
            except Exception as exc:
                self.messages.put((None, None, exc))
        self.executor.submit(task).add_done_callback(complete)

    def _poll(self):
        if self.closed:
            return
        try:
            callback, result, error = self.messages.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop();self.progress.pack_forget()
            if error:
                self.guard(lambda: self._raise(error))
            else:
                self.status.set('操作完成')
                if callback:
                    self.guard(lambda: callback(result))
                if self.on_change:
                    self.guard(self.on_change)
        self._poll_id = self.after(100, self._poll)

    @staticmethod
    def _raise(exc):
        raise exc

    def clean(self):
        require(not self.busy, '当前操作尚未完成，请稍候。')
        require(not self.session.dirty, '有未保存修改，请先保存或放弃修改。')

    def _build(self):
        self.active_module = 'M01'
        self.module_states = {}
        self.nav_titles = {'M01':'素材库', 'M02':'筛选候选', 'M03':'框选角色', 'M04':'生成样本',
                           'M05':'样本标注', 'M06':'准备训练资料', 'M07':'查询图标注',
                           'M08':'搜索设置', 'M09':'结果与定位', 'AI':'模型与建议', 'TASKS':'后台任务'}
        self.page_titles = {'M01':('素材库', '添加素材，读取画面，再框选需要检索的角色。'),
                            'M02':('筛选候选画面', '保留需要的画面，排除重复或不适合标注的内容。'),
                            'M03':('框选角色', '一个框对应一个角色；同一画面可以保存多个角色。'),
                            'M04':('生成姿态样本', '核对角色与区域后生成样本，接着进入姿态标注。'),
                            'M05':('姿态标注', '在画面中画出方向，逐项核对并保存。'),
                            'M06':('准备训练资料', '检查标注，保存已审核数据，再交给模型训练。'),
                            'M07':('查询图标注', '载入查询图片，按熟悉的方式逐点标注或直接画方向。'),
                            'M08':('搜索设置', '选择范围、部位权重，再搜索。'),
                            'M09':('搜索结果与素材定位', '比较命中画面，找回原文件和对应帧位置。'),
                            'AI':('模型与建议审核', '模型先提出建议，核对后再接受到标注中。'),
                            'TASKS':('后台任务', '查看素材处理、样本生成和模型任务的进度。')}
        footer=ttk.Frame(self,padding=(14,7));footer.pack(side='bottom',fill='x')
        self.progress=ttk.Progressbar(footer,mode='indeterminate',length=70)
        status_label=ttk.Label(footer,textvariable=self.status,style='Muted.TLabel',wraplength=1000)
        self.status_label=status_label
        status_label.pack(side='left',fill='x',expand=True)
        status_label.bind('<Configure>',lambda e:status_label.configure(wraplength=max(100,e.width)))
        body=ttk.Frame(self);body.pack(fill='both',expand=True,padx=6,pady=3)
        from tkinter import font
        navwidth=max(190,font.nametofont('TkDefaultFont',root=self).measure('M06  准备训练资料')+44)
        self.navigation=ttk.LabelFrame(body,text='模块',width=navwidth,padding=4)
        self.navigation.pack(side='left',fill='y',padx=(0,7));self.navigation.pack_propagate(False)
        queuebox=ttk.Frame(self.navigation,padding=(2,4));queuebox.pack(side='bottom',fill='x')
        ttk.Label(queuebox,textvariable=self.jobs_status,wraplength=navwidth-20).pack(fill='x')
        navscroll=ScrollPanel(self.navigation,width=navwidth-12);navscroll.pack(fill='both',expand=True)
        navscroll.content.configure(padding=0)
        self.module_buttons={};self.extra_buttons={}
        for mid in ('M01','M02','M03','M04','M05','M06','M07','M08','M09','AI','TASKS'):
            if mid=='AI':ttk.Separator(navscroll.content).pack(fill='x',pady=5)
            title=mid+' '+self.nav_titles[mid] if mid.startswith('M') else self.nav_titles[mid]
            button=self.button(navscroll.content,title,lambda m=mid:self.open_module(m),
                               side='top',fill='x',padx=0,pady=2,style='Nav.TButton')
            (self.module_buttons if mid.startswith('M') else self.extra_buttons)[mid]=button
        main=ttk.Frame(body);main.pack(side='left',fill='both',expand=True)
        heading=Toolbar(main);heading.pack(fill='x',pady=(0,4))
        self.page_title=ttk.Label(heading,style='Title.TLabel');self.page_title.pack(side='left')
        self.page_badge=ttk.Label(heading);self.page_badge.pack(side='left')
        actor_box=ttk.Frame(heading);actor_box.pack(side='left')
        ttk.Label(actor_box,text='标注者').pack(side='left',padx=(10,4))
        ttk.Entry(actor_box,textvariable=self.actor,width=12).pack(side='left')
        self.button(heading,'角色与形态…',self.add_character)
        self.page_hint=ttk.Label(main,wraplength=900)
        self.tabs=ttk.Notebook(main,style='Module.TNotebook');self.tabs.pack(fill='both',expand=True)
        self.files_tab,self.editor_tab,self.results_tab=[ttk.Frame(self.tabs) for _ in range(3)]
        for page,text in zip((self.files_tab,self.editor_tab,self.results_tab),('素材库','姿态标注','搜索结果')):
            self.tabs.add(page,text=text)
        self._build_sources();self._build_editor();self._build_results()
        from lifecycle_views import LifecycleViews
        self.lifecycle=LifecycleViews(self)
        self.tabs.bind('<<NotebookTabChanged>>',self._page_changed)
        self._highlight_module('M01')
        self._save_binding=self.winfo_toplevel().bind('<Control-s>',self._save_shortcut,add='+')
        self._editor_bindings={key:self.winfo_toplevel().bind(key,lambda e,k=key:self._editor_shortcut(k,e),add='+')
            for key in ('<Left>','<Right>','<Up>','<Down>','<Control-Return>')}

    def _editor_shortcut(self,key,event):
        if self.tabs.select()!=str(self.editor_tab) or event.widget.winfo_toplevel()!=self.winfo_toplevel():return
        # Never consume text editing, selection or spinbox keys in fields.
        if isinstance(event.widget,(tk.Entry,ttk.Entry,ttk.Combobox,tk.Text,ttk.Spinbox)):return
        actions={'<Left>':lambda:self.next_record(-1),'<Right>':self.next_record,
            '<Up>':lambda:self.next_annotation(-1),'<Down>':lambda:self.next_annotation(1),
            '<Control-Return>':self.clear_point if self.annotation_mode.key()=='keypoints' else self.clear_direction}
        self.guard(actions[key]);return 'break'

    def _save_shortcut(self,event=None):
        if self.tabs.select()==str(self.editor_tab) and self.session.dirty:
            self.guard(self.save_record)
            return 'break'

    def set_module_status(self, module, state):
        self.module_states[module]=state
        if module==self.active_module:self.page_badge.configure(text=state)
        if module in self.module_buttons:
            prefix='▶ ' if module==self.active_module else ''
            self.module_buttons[module].configure(text=prefix+module+' '+self.nav_titles[module]+'\n'+state)
        self.page_badge.master._schedule()

    def _highlight_module(self, module):
        self.active_module=module
        for mid,button in {**self.module_buttons,**self.extra_buttons}.items():
            title=(mid+' ' if mid.startswith('M') else '')+self.nav_titles[mid]
            state=self.module_states.get(mid)
            button.configure(text=('▶ ' if mid==module else '')+title+('\n'+state if state else ''),
                             style='Nav.TButton')
        title,hint=self.page_titles[module]
        self.page_title.configure(text=(module+'  ' if module.startswith('M') else '')+title)
        self.page_hint.configure(text=hint)
        self.page_badge.configure(text=self.module_states.get(module,''))
        self.page_title.master._schedule()

    def _page_changed(self,event=None):
        page=self.tabs.select()
        groups={str(self.files_tab):('M01',),str(self.editor_tab):('M05','M07'),str(self.search_tab):('M08',),str(self.results_tab):('M09',),
                str(self.lifecycle.pages['regions']):('M02','M03','M04'),str(self.lifecycle.pages['preparation']):('M06',),
                str(self.lifecycle.pages['models']):('AI',),str(self.lifecycle.pages['tasks']):('TASKS',)}
        ids=groups.get(page,('M01',))
        self._highlight_module(self.active_module if self.active_module in ids else ids[0])

    def open_module(self,module):
        self.clean()
        if module=='M01':self.tabs.select(self.files_tab)
        elif module in {'M02','M03','M04'}:
            self.lifecycle.refresh_regions();self.tabs.select(self.lifecycle.pages['regions'])
        elif module=='M05':self.tabs.select(self.editor_tab)
        elif module=='M06':
            self.lifecycle.refresh_snapshots();self.tabs.select(self.lifecycle.pages['preparation'])
        elif module=='AI':
            self.lifecycle.refresh_models();self.tabs.select(self.lifecycle.pages['models'])
        elif module=='TASKS':
            self.lifecycle.refresh_tasks();self.tabs.select(self.lifecycle.pages['tasks'])
        elif module=='M07':
            if self.query_observation and (not self.session.record or self.session.record['observation_id']!=self.query_observation or self.session.historical):
                self.load_record(self.query_observation)
            self.tabs.select(self.editor_tab)
            self.status.set('更换查询图片，或使用当前样本作为查询；标注完成后进入 M08。')
        elif module=='M08':
            if self.session.record:self.prepare_search()
            else:self.tabs.select(self.search_tab)
        elif module=='M09':
            state=self.session.workflow.current()
            if state.get('run_id'):
                self.session.last_results=self.session.workflow.result(state['run_id'])
                self.render_results(self.session.last_results)
            self.tabs.select(self.results_tab)
        self._highlight_module(module)
        self._page_changed()

    @staticmethod
    def tree(parent, columns, height=12):
        box=ttk.Frame(parent);box.pack(fill='both',expand=True)
        box.rowconfigure(0,weight=1);box.columnconfigure(0,weight=1)
        tree=ttk.Treeview(box,columns=list(columns),show='headings',selectmode='browse',height=height)
        factor=max(1.,float(tree.tk.call('tk','scaling'))/(96/72))
        for key,(title,width) in columns.items():
            width=round(width*factor)
            tree.heading(key,text=title,anchor='w');tree.column(key,width=width,minwidth=min(width,round(160*factor)),anchor='w',stretch=width>160)
        scroll=ttk.Scrollbar(box,orient='vertical',command=tree.yview)
        horizontal=ttk.Scrollbar(box,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        tree.grid(row=0,column=0,sticky='nsew');scroll.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        return tree

    @staticmethod
    def field(parent, title, choice):
        ttk.Label(parent,text=title).pack(anchor='w',pady=(7,1))
        choice.pack(fill='x')
        return choice

    def _build_sources(self):
        bar=Toolbar(self.files_tab);bar.pack(fill='x',pady=(0,4))
        self.button(bar,'＋ 添加文件',self.add_files,style='Primary.TButton')
        self.button(bar,'添加文件夹…',self.add_folder)
        self.button(bar,'导入设置',self.import_options)
        self.queue_button=self.button(bar,'暂停处理',self.pause_sources)
        self.button(bar,'目录与任务管理',self.manage_sources)
        self.button(bar,'刷新',self.refresh_sources,style='Quiet.TButton')
        panes,(left,right)=split(self.files_tab,[330,760],[1,3])
        section(left,'已登记素材','输入文件名查找；可按格式筛选。')
        find=Toolbar(left);find.pack(fill='x',pady=(0,6))
        self.file_filter=ttk.Entry(find,width=12);self.file_filter.pack(side='left',fill='x',expand=True)
        self.file_filter.bind('<Return>',lambda e:self.guard(self.filter_sources))
        self.file_format=Choice(find,{'':'全部格式',**{k:k for k in ('MP4','MOV','MKV','PNG','JPG','WEBP','FLA','XFL','SWF')}},width=8)
        self.file_format.pack(side='left',padx=(6,0))
        self.file_format.bind('<<ComboboxSelected>>',lambda e:self.guard(self.filter_sources))
        self.button(find,'查找',self.filter_sources,style='Quiet.TButton')
        page=Toolbar(left);page.pack(side='bottom',fill='x',pady=(6,0))
        self.button(page,'上一页',lambda:self.page_sources(-1));self.button(page,'下一页',lambda:self.page_sources(1))
        ttk.Label(page,textvariable=self.file_count,style='Muted.TLabel').pack(side='left')
        self.files_empty=ttk.Label(left,text='还没有素材。点击“添加文件”开始，图片、视频和工程可以一起选。',style='Muted.TLabel',wraplength=290)
        self.files_empty.pack(fill='x',pady=12)
        self.files=self.tree(left,{'name':('文件',185),'format':('格式',55),'state':('状态',80)})
        self.files.bind('<<TreeviewSelect>>',lambda e:self.guard(self.select_file))
        section(right,'画面与来源')
        framebar=Toolbar(right);framebar.pack(fill='x',pady=(0,5))
        self.button(framebar,'上一帧',lambda:self.read_frame(-1))
        frameinput=ttk.Frame(framebar);frameinput.pack(side='left')
        ttk.Label(frameinput,text='第').pack(side='left')
        ttk.Entry(frameinput,textvariable=self.frame_number,width=6).pack(side='left',padx=4)
        ttk.Label(frameinput,text='帧').pack(side='left')
        self.button(framebar,'读取画面',self.read_frame,style='Primary.TButton')
        self.button(framebar,'下一帧',lambda:self.read_frame(1))
        self.button(framebar,'批量选帧…',self.sample_frames_dialog)
        self.character_fla_button=self.button(framebar,'角色工程…',self.open_character_fla)
        self.character_fla_button.configure(state='disabled')
        self.stream=Choice(framebar,{},width=9);self.stream.pack(side='left')
        self.import_controls=FieldGroup(right,'建立姿态记录')
        self.import_controls.pack(side='bottom',fill='x',pady=(6,0))
        importbox=self.import_controls.content
        ttk.Label(importbox,textvariable=self.roi_text,style='Muted.TLabel').pack(anchor='w')
        row=Toolbar(importbox);row.pack(fill='x')
        self.button(row,'选整张图',self.full_region,style='Quiet.TButton')
        ttk.Checkbutton(row,text='确认框内是一个角色',variable=self.confirm_region).pack(side='left')
        ttk.Checkbutton(row,text='仅作查询图',variable=self.query_only,command=self._reset_request).pack(side='left')
        row=Toolbar(importbox);row.pack(fill='x')
        self.form=Choice(row,{r['id']:r['label'] for r in self.catalog.data['forms']},width=23)
        self.form.pack(side='left');self.form.bind('<<ComboboxSelected>>',lambda e:self._reset_request())
        self.import_button=self.button(row,'建立记录 → 标注',self.import_region,style='Primary.TButton')
        self.button(row,'先保存为候选',self.save_candidate)
        actions=Toolbar(right);actions.pack(side='bottom',fill='x')
        self.button(actions,'在文件夹中选中',self.locate_source)
        self.button(actions,'复制位置',self.copy_source)
        self.button(actions,'素材信息／工程线索',self.source_info)
        self.button(actions,'播放附近片段',self.preview_source)
        detail=FieldGroup(right,'原文件与位置详情');detail.pack(side='bottom',fill='x')
        self.source_detail=tk.Text(detail.content,height=2,wrap='word',font=('Microsoft YaHei UI',9))
        self.source_detail.pack(fill='x');self.source_detail.configure(state='disabled')
        self.source_caption=ttk.Label(right,text='帧号从 1 开始',style='Muted.TLabel',wraplength=600)
        self.source_caption.pack(side='bottom',fill='x',pady=4)
        self.source_caption.bind('<Configure>',lambda e:self.source_caption.configure(wraplength=max(100,e.width)))
        self.source_picture=Picture(right,lambda a,b:self.guard(lambda:self.set_region(a,b)),
                                    empty='选择左侧素材，再读取画面',hint='图片可直接查看 · 视频按帧读取 · 工程可查看结构与文件位置')
        self.source_picture.mode='region';self.source_picture.pack(fill='both',expand=True)

    def _reset_request(self):
        self.import_request=None

    def add_files(self):
        paths=filedialog.askopenfilenames(parent=self,title='选择素材，可混选视频、图片和工程')
        if paths:self.enqueue_sources(list(paths))

    def add_folder(self):
        path=filedialog.askdirectory(parent=self,title='登记整个素材目录（含子目录）')
        if path:self.enqueue_sources([path])

    def enqueue_sources(self, paths):
        excludes=list(self.excludes)
        self.run('正在登记素材…',lambda:self.session.sources.add_inputs(paths,excludes=excludes),lambda r:self.refresh_sources())

    def import_options(self, root_id=None):
        win=tk.Toplevel(self);win.title('扫描排除目录');win.geometry('460x215')
        box=dialog_form(win)
        current=self.excludes
        if root_id:current=json.loads(self.session.sources.get_root(root_id)['excludes'])
        entry=self.field(box,'不扫描的目录名，用逗号分隔',ttk.Entry(box));entry.insert(0,', '.join(current))
        ttk.Label(box,text='例如：缓存, 临时导出。只影响后续扫描，已经登记的素材与标注会保留。',wraplength=425).pack(fill='x',pady=8)
        def apply():
            excluded=[v.strip() for v in entry.get().replace('，',',').split(',') if v.strip()]
            if root_id:
                self.session.sources.set_excludes(root_id,excluded)
            else:self.excludes=excluded
            self.status.set('排除设置已保存；下次添加目录时生效。' if not root_id else '已按新排除设置排队扫描。')
            win.destroy()
        self.button(box,'保存排除设置',apply,side='top',fill='x')

    def filter_sources(self):
        self.offset=0;self.refresh_sources()

    def page_sources(self, direction):
        self.offset=max(0,self.offset+direction*50);self.refresh_sources()

    def refresh_sources(self):
        source=self.session.sources
        data=source.list_files(query=self.file_filter.get().strip(),format=self.file_format.key() or '',limit=50,offset=self.offset)
        if self.offset and not data['items']:
            self.offset=max(0,((data['total']-1)//50)*50)
            data=source.list_files(query=self.file_filter.get().strip(),format=self.file_format.key() or '',limit=50,offset=self.offset)
        if data['items']:
            self.files_empty.pack_forget()
        else:
            self.files_empty.configure(text='没有匹配的素材。请修改文件名或格式筛选。' if data['total']==0 and (self.file_filter.get() or self.file_format.key()) else '还没有素材。点击“添加文件”开始，图片、视频和工程可以一起选。')
            self.files_empty.pack(fill='x',pady=12,before=self.files.master)
        selected=self.files.selection()
        self.files.delete(*self.files.get_children())
        for row in data['items']:
            self.files.insert('', 'end', iid=row['id'], values=(row['name'],row['format'],('可编目' if row['kind'] not in {'image','video'} else '可查看') if row['state']=='ready' else STATES.get(row['state'],row['state'])))
        if selected and self.files.exists(selected[0]):self.files.selection_set(selected[0])
        self.file_count.set(f"{self.offset//50+1} 页 · 共 {data['total']} 件")
        state=source.status();counts=state['states']
        self.queue_button.configure(text='继续处理' if state['paused'] else '暂停处理')
        self.jobs_status.set(f"{'已暂停' if state['paused'] else '后台处理'} · 排队 {counts.get('queued',0)} · 处理中 {counts.get('running',0)} · 失败 {counts.get('failed',0)}")

    def _tick_sources(self):
        if self.closed:return
        try:
            self.session.sources.start()  # Recover the worker lease after another window exits.
            state=self.session.sources.status();counts=state['states']
            self.jobs_status.set(f"{'已暂停' if state['paused'] else '后台处理'} · 排队 {counts.get('queued',0)} · 处理中 {counts.get('running',0)} · 失败 {counts.get('failed',0)}")
            for jid,(generation,callback) in list(self.watched.items()):
                job=self.session.sources.job(jid)
                if job['state'] in {'done','failed'}:
                    del self.watched[jid]
                    if generation==self.source_generation:
                        if job['state']=='failed':self.status.set('读取失败：'+str(job['error']))
                        else:self.guard(lambda j=job,cb=callback:cb(j['result']))
            # File rows can change as the queue advances, but don't reset an active crop.
            signature=(tuple(sorted(counts.items())),tuple(sorted(state['files'].items())))
            if getattr(self,'_queue_signature',None)!=signature:
                self._queue_signature=signature;self.refresh_sources()
                if self.on_change:self.on_change()
            if self.tabs.select()==str(self.lifecycle.pages['tasks']):self.lifecycle.refresh_tasks()
        except Exception as exc:
            self.status.set('素材队列：'+str(exc))
        self._status_id=self.after(1000,self._tick_sources)

    def pause_sources(self):
        self.session.sources.pause(not self.session.sources.paused);self.refresh_sources()

    @staticmethod
    def text(widget, value):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',value);widget.configure(state='disabled')

    def select_file(self):
        chosen=self.files.selection()
        if not chosen or chosen[0]==self.file_id:return
        self.file_id=chosen[0];self.source_generation+=1;self.position_id=None;self.import_request=None;self.timeline_id=None
        self.confirm_region.set(False);self.roi_text.set('尚未框选角色');self.source_picture.set_image(None)
        file=self.session.sources.file(self.file_id)
        self.character_fla_button.configure(state='normal' if file['format']=='FLA' else 'disabled')
        self.stream.set_items({s['index']:f"视频流 {s['index']}" for s in file['metadata'].get('streams',[])},file['metadata'].get('default_stream'))
        self.frame_number.set('1')
        self.source_caption.configure(text=file['name']+' · '+file['format']+' · '+STATES.get(file['state'],file['state']))
        hint='点击“角色工程…”选择时间轴、导出并查看工程画面。' if file['format']=='FLA' else '选择帧号后读取画面；工程文件可查看信息和所在位置。'
        self.text(self.source_detail,file['path']+'\n'+(file.get('error') or hint))
        if file['kind']=='image' and file['state']=='ready':self.read_frame()

    def read_frame(self, delta=0):
        require(self.file_id, '请先选择素材。')
        # Programmatic navigation may precede an older Treeview selection event.
        # Keep the visible selection and queued request on the same source.
        if self.files.exists(self.file_id):
            self.files.selection_set(self.file_id)
            self.files.see(self.file_id)
        else:
            self.files.selection_remove(*self.files.selection())
        ordinal=int(self.frame_number.get())+delta
        require(ordinal>=1,'帧号从 1 开始。')
        file=self.session.sources.file(self.file_id)
        if file['format']=='FLA':
            if self.timeline_id:
                positions=self.session.context.characters.positions(self.file_id,timeline_id=self.timeline_id)
                position=next((p for p in positions if p['payload'].get('frame_index0')==ordinal-1),None)
                if position:
                    self.source_generation+=1
                    self.show_position(position['id'])
                    return
            self.open_character_fla()
            self.status.set('请在角色工程窗口选择时间轴；未导出的工程帧需先加入导出任务。')
            return
        require(file['kind'] in {'image','video'},'此工程目前支持编目、结构信息和文件定位，尚不能渲染工程画面。')
        self.source_generation+=1;self.position_id=None;self.import_request=None;self.confirm_region.set(False)
        self.roi_text.set('正在读取画面…');self.source_picture.set_image(None)
        self.frame_number.set(str(ordinal))
        jid=self.session.sources.queue('position',{'fid':self.file_id,'version_id':file['version_id'],
                                                  'ordinal0':ordinal-1,'stream_index':self.stream.key()})
        self.watched[jid]=(self.source_generation,lambda p:self.show_position(p['id']))
        self.status.set('画面已排队；如队列已暂停，请点击“继续处理”。')

    def show_position(self, pid):
        info=self.session.service.describe_position(pid)
        self.file_id,self.position_id=info['file_id'],pid
        position=info.get('position') or {}
        self.timeline_id=position.get('timeline_id') if position.get('kind')=='fla_frame' else None
        if self.files.exists(self.file_id):self.files.selection_set(self.file_id);self.files.see(self.file_id)
        with Image.open(self.session.sources.cached_image(pid)) as im:self.source_picture.set_image(im.convert('RGBA'))
        ordinal=position.get('frame_index0',0) if position.get('kind')=='fla_frame' else position.get('presentation_ordinal0',0)
        self.frame_number.set(str(ordinal+1))
        file=self.session.sources.file(self.file_id)
        self.character_fla_button.configure(state='normal' if file['format']=='FLA' else 'disabled')
        self.stream.set_items({s['index']:f"视频流 {s['index']}" for s in file['metadata'].get('streams',[])},info['position'].get('stream_index'))
        self.source_caption.configure(text=file['name']+' · '+file['format']+' · '+(position_caption(position) or '原图'))
        self.text(self.source_detail,readable_location(self.session.service.position_text(info)))
        self.roi_text.set('请在图上框选一个角色');self.confirm_region.set(False);self.import_request=None
        self.status.set('画面已就绪，框选角色后可建立姿态。')

    def set_region(self, start, end):
        require(self.position_id,'请先读取画面。')
        x,y=math.floor(min(start[0],end[0])),math.floor(min(start[1],end[1]))
        w,h=math.ceil(max(start[0],end[0]))-x,math.ceil(max(start[1],end[1]))-y
        require(w>0 and h>0,'请框出有宽度和高度的区域。')
        self.source_picture.region=[x,y,w,h];self.source_picture.redraw()
        self.roi_text.set(f'角色框：{x}, {y} · {w} × {h}')
        self.confirm_region.set(False);self.import_request=None

    def full_region(self):
        require(self.source_picture.image is not None,'请先读取画面。')
        self.set_region([0,0],list(self.source_picture.image.size))

    def import_region(self):
        self.clean()
        require(self.position_id and self.source_picture.region and self.confirm_region.get(),'请先框选并确认一个角色。')
        self.import_request=self.import_request or new_id('import')
        args=dict(position_id=self.position_id,roi=list(self.source_picture.region),form_ref=self.form.key(),
                  request_id=self.import_request,actor=self.actor.get(),is_query=self.query_only.get())
        def done(result):
            self.refresh_records();self.load_record(result['record']['observation_id']);self.tabs.select(self.editor_tab)
        self.run('正在保存角色与来源位置…',lambda:self.session.context.dataset.import_region(**args),done)

    def sample_frames_dialog(self):
        self.clean();require(self.file_id,'请先选择视频或图片')
        if self.session.sources.file(self.file_id)['format']=='FLA':
            return self.open_character_fla()
        win=tk.Toplevel(self);win.title('批量建立待筛候选');box=dialog_form(win)
        values={}
        for key,title,default in [('start','起始帧（从 1 开始）',1),('stop','结束帧',1),('step','每隔多少帧取一次',24)]:
            entry=self.field(box,title,ttk.Entry(box));entry.insert(0,str(default));values[key]=entry
        ttk.Label(box,text='全部先进入 M02 待判断；重复执行不覆盖人工筛选。').pack(fill='x',pady=8)
        def enqueue():
            args={k:int(v.get()) for k,v in values.items()}
            self.session.context.dataset.queue_frames(self.file_id,actor=self.actor.get(),**args)
            self.status.set('批量选帧已排队，进度见任务页。');win.destroy()
        self.button(box,'加入队列',enqueue)

    def open_character_fla(self):
        self.clean();require(self.file_id,'请先选择 FLA 角色工程。')
        require(self.session.sources.file(self.file_id)['format']=='FLA','请先选择 FLA 角色工程。')
        win=self._character_fla_window
        if win and win.winfo_exists():
            if win.file_id==self.file_id:
                if self.timeline_id and self.timeline_id!=win.selected_timeline:
                    win.selected_timeline=self.timeline_id
                    win.refresh_timelines()
                win.deiconify();win.lift();return win
            win.destroy()
        from character_fla_view import CharacterFlaWindow
        self._character_fla_window=CharacterFlaWindow(self,self.file_id,self.timeline_id)
        return self._character_fla_window

    def save_candidate(self):
        require(self.position_id,'请先读取一个画面')
        data=self.session.context.dataset
        current=data.candidate(self.position_id)
        if not current:current=data.decide(self.position_id,'undecided',actor=self.actor.get())
        self.lifecycle.focus_candidate(current['id'])
        self.tabs.select(self.lifecycle.pages['regions'])

    def copy_source(self):
        require(self.file_id,'请先选择素材。')
        value=self.session.service.position_text(self.session.service.describe_position(self.position_id)) if self.position_id else self.session.sources.file(self.file_id)['path']
        self.copy_text(value)

    def copy_text(self, value):
        self.clipboard_clear();self.clipboard_append(value);self.status.set('已复制到剪贴板。')

    def locate_source(self):
        require(self.file_id,'请先选择素材。')
        args={'position_id':self.position_id} if self.position_id else {'file_id':self.file_id}
        self.run('正在核验并定位原文件…',lambda:self.session.service.locate(**args),lambda r:self.status.set('已请求文件管理器选中素材。'))

    def source_info(self):
        require(self.file_id,'请先选择素材。')
        file=self.session.sources.file(self.file_id)
        self.details('素材信息与同名线索',{'素材':file,'同名候选（帧与角色尚未核对）':self.session.sources.related(self.file_id)})

    def preview_source(self):
        require(self.position_id,'请先读取一个视频画面。')
        require(self.session.sources.position(self.position_id)['payload']['kind']=='video_frame','此素材不是视频。')
        jid=self.session.sources.queue('proxy',{'position_id':self.position_id})
        self.watched[jid]=(self.source_generation,lambda proxy:self.run('正在准备窗口内播放…',lambda:self.session.preview_frames(proxy),self.show_clip))
        self.status.set('附近片段已排队；预览不会改变当前精确帧号。')

    def show_clip(self, frames):
        win=tk.Toplevel(self);win.title('附近片段 · 无声预览');win.geometry('720x490')
        picture=Picture(win);picture.pack(fill='both',expand=True)
        ttk.Label(win,text='仅用于观察动作上下文。精确位置仍以素材库中的帧号和静态画面为准。',wraplength=680).pack(fill='x',padx=8,pady=4)
        frame=tk.IntVar(win,0);playing=tk.BooleanVar(win,True)
        bar=Toolbar(win);bar.pack(fill='x')
        def seek(value):
            index=max(0,min(len(frames)-1,round(float(value))))
            frame.set(index);picture.set_image(frames[index])
        self.button(bar,'暂停／继续',lambda:playing.set(not playing.get()))
        scale=ttk.Scale(bar,from_=0,to=len(frames)-1,variable=frame,command=seek);scale.pack(side='left',fill='x',expand=True,padx=8)
        def tick():
            if not win.winfo_exists():return
            if playing.get():
                seek(frame.get())
                if frame.get()>=len(frames)-1:playing.set(False)
                else:frame.set(frame.get()+1)
            win._clip_timer=win.after(100,tick)
        def close():
            win.after_cancel(win._clip_timer);win.destroy()
        win.protocol('WM_DELETE_WINDOW',close)
        seek(0);tick()

    def details(self, title, data):
        win=tk.Toplevel(self);win.title(title);win.geometry('760x520')
        body=tk.Text(win,wrap='word',font=('Microsoft YaHei UI',10));body.pack(fill='both',expand=True)
        scroll=ttk.Scrollbar(body,command=body.yview);scroll.pack(side='right',fill='y');body.configure(yscrollcommand=scroll.set)
        self.text(body,data if isinstance(data,str) else json.dumps(data,ensure_ascii=False,indent=2))
        return win

    def manage_sources(self):
        win=tk.Toplevel(self);win.title('后台任务与素材目录');win.geometry('850x550')
        state=self.session.sources.status()
        roots=Choice(win,{r['id']:r['path'] for r in state['roots']});roots.pack(fill='x',padx=8,pady=5)
        bar=Toolbar(win);bar.pack(fill='x')
        def scan(force=False):
            require(roots.key(),'尚未登记素材目录。')
            self.session.sources.queue('scan',{'root_id':roots.key(),'force':force});self.status.set('目录扫描已排队。')
        def rebind():
            require(roots.key(),'尚未登记素材目录。')
            path=filedialog.askdirectory(parent=win,title='选择搬家后的素材目录，核验相同内容后才改绑')
            if path:self.session.sources.queue('rebind',{'root_id':roots.key(),'path':path})
        self.button(bar,'扫描新增和变化',scan);self.button(bar,'核验全部内容',lambda:scan(True));self.button(bar,'目录搬家…',rebind)
        def exclusions():
            require(roots.key(),'尚未登记素材目录。');self.import_options(roots.key())
        self.button(bar,'修改排除项',exclusions)
        jobs=self.tree(win,{'kind':('任务',80),'name':('素材',340),'state':('状态',80),'error':('错误原因',260)})
        def refresh():
            jobs.delete(*jobs.get_children())
            for j in self.session.sources.status()['jobs']:
                jobs.insert('','end',iid=j['id'],values=({'scan':'扫描','probe':'读素材','position':'取帧','rebind':'改绑','proxy':'片段'}.get(j['kind'],j['kind']),j['label'],STATES.get(j['state'],j['state']),j['error'] or ''))
        def retry():
            require(jobs.selection(),'请选择失败的任务。');self.session.sources.retry(jobs.selection()[0]);refresh()
        footer=Toolbar(win);footer.pack(fill='x')
        self.button(footer,'重试选中任务',retry);self.button(footer,'刷新列表',refresh)
        self.button(footer,'导出编目 JSON',lambda:self.export_catalog())
        footer.pack_configure(side='bottom',before=jobs.master)
        refresh()

    def export_catalog(self):
        path=filedialog.asksaveasfilename(parent=self,title='保存素材编目快照',defaultextension='.json',filetypes=[('JSON','*.json')])
        if path:
            Path(path).write_text(json.dumps(self.session.sources.export(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            self.status.set('编目已导出：'+path)

    def _build_editor(self):
        # Same working arrangement as M05/M07: large image and a visible point list.
        # The sample browser is optional so it does not consume the drawing area.
        header=Toolbar(self.editor_tab);header.pack(fill='x')
        self.button(header,'选择样本…',self.choose_record)
        self.button(header,'更换查询图片…',self.choose_query_image)
        self.record_title=ttk.Label(header,text='选择样本或查询图片',width=46)
        self.record_title.pack(side='left')
        self.record_state_label=ttk.Label(self.editor_tab,textvariable=self.record_state)
        self.record_state_label.pack(fill='x',padx=4)
        panes,(center,right)=split(self.editor_tab,[720,320],[4,0])
        self.pose_picture=Picture(center,lambda a,b:self.guard(lambda:self.draw_annotation(a,b)),
            empty='选择样本或查询图片，开始标注',hint='单击落点并前进 · 点击已有点选中修改 · Ctrl+Enter 标缺失')
        self.pose_picture.pack(fill='both',expand=True,padx=3,pady=3)
        ttk.Label(center,text='↑↓ 选点  ·  ←→ 换图  ·  滚轮缩放  ·  空格拖动／中键平移').pack(fill='x',padx=4)
        self.annotation_mode=Choice(right,{'keypoints':'关键点','directions':'直接方向'})
        self.annotation_mode.pack(fill='x',pady=3)
        self.annotation_mode.bind('<<ComboboxSelected>>',lambda e:self.guard(self.update_annotation_mode))
        # Always-visible save/navigation controls are packed before the expanding list.
        bottom=ttk.Frame(right);bottom.pack(side='bottom',fill='x')
        nav=Toolbar(bottom);nav.pack(fill='x')
        self.button(nav,'◀ 上一张',lambda:self.next_record(-1))
        self.button(nav,'下一张 ▶',self.next_record)
        self.button(bottom,'跳到未完成',self.jump_unannotated,side='top',fill='x')
        bar=Toolbar(bottom);bar.pack(fill='x')
        self.save_button=self.button(bar,'保存 (Ctrl+S)',self.save_record)
        self.button(bar,'放弃修改',self.discard_record)
        bar=Toolbar(bottom);bar.pack(fill='x')
        self.button(bar,'生成方向…',self.derive_from_points)
        self.button(bar,'搜索此姿态 → M08',self.prepare_search)
        more=Toolbar(bottom);more.pack(fill='x')
        self.button(more,'标注属性…',self.annotation_properties)
        self.button(more,'历史版本',self.history)
        self.button(more,'原素材位置',self.record_location)
        from classic_widgets import AnnotationList
        from multispecies.keypoints import LABELS, ORDER
        self.point_controls=ttk.Frame(right)
        actions=Toolbar(self.point_controls);actions.pack(side='bottom',fill='x')
        self.button(actions,'标缺失 (Ctrl+Enter)',self.clear_point)
        self.button(actions,'确认此点',self.review_point)
        self.point_state=ttk.Label(self.point_controls,wraplength=290)
        self.point_state.pack(side='bottom',fill='x',pady=3)
        frame=ttk.Frame(self.point_controls);frame.pack(fill='both',expand=True)
        self.point_key=AnnotationList(frame,{k:f'{i+1:02} '+LABELS.get(k,k) for i,k in enumerate(ORDER)})
        scroll=ttk.Scrollbar(frame,command=self.point_key.yview);scroll.pack(side='right',fill='y')
        self.point_key.configure(yscrollcommand=scroll.set);self.point_key.pack(fill='both',expand=True)
        self.point_key.bind('<<ListboxSelect>>',lambda e:self.guard(self.refresh_editor_state))
        for key in ('<Up>','<Down>'):
            self.point_key.bind(key,lambda e,k=key:self._editor_shortcut(k,e))
        self.direction_controls=ttk.Frame(right)
        actions=Toolbar(self.direction_controls);actions.pack(side='bottom',fill='x')
        self.direction_review_button=self.button(actions,'确认此方向',lambda:self.review('approved',True))
        self.button(actions,'标缺失',self.clear_direction)
        ttk.Label(self.direction_controls,textvariable=self.direction_state,wraplength=290).pack(side='bottom',fill='x')
        frame=ttk.Frame(self.direction_controls);frame.pack(fill='both',expand=True)
        self.direction=AnnotationList(frame)
        scroll=ttk.Scrollbar(frame,command=self.direction.yview);scroll.pack(side='right',fill='y')
        self.direction.configure(yscrollcommand=scroll.set);self.direction.pack(fill='both',expand=True)
        self.direction.bind('<<ListboxSelect>>',lambda e:self.guard(self.update_direction))
        for key in ('<Up>','<Down>'):
            self.direction.bind(key,lambda e,k=key:self._editor_shortcut(k,e))
        # Shared controls are kept in ordinary modeless dialogs, not another editor.
        self.record_browser=tk.Toplevel(self);self.record_browser.withdraw()
        self.record_browser.title('选择样本');self.record_browser.geometry('650x520')
        self.record_browser.protocol('WM_DELETE_WINDOW',self.record_browser.withdraw)
        left=ttk.Frame(self.record_browser,padding=8);left.pack(fill='both',expand=True)
        self.collection=Choice(left,COLLECTIONS);self.collection.pack(fill='x')
        self.collection.bind('<<ComboboxSelected>>',lambda e:self.guard(self.render_records))
        ttk.Label(left,text='按角色或素材名查找').pack(anchor='w')
        self.record_filter=ttk.Entry(left);self.record_filter.pack(fill='x')
        self.record_filter.bind('<KeyRelease>',lambda e:self.render_records())
        bar=Toolbar(left);bar.pack(side='bottom',fill='x')
        self.button(bar,'打开所选样本',self.open_selected_record)
        self.button(bar,'刷新',self.refresh_records)
        self.records=self.tree(left,{'name':('姿态记录',430),'known':('方向',65)})
        self.records.bind('<<TreeviewSelect>>',lambda e:self.guard(self.select_record))
        self.records.bind('<Double-1>',lambda e:self.guard(self.open_selected_record))
        self.property_window=tk.Toplevel(self);self.property_window.withdraw()
        self.property_window.title('标注属性');self.property_window.geometry('400x600')
        self.property_window.protocol('WM_DELETE_WINDOW',self.property_window.withdraw)
        self.editor_settings=ScrollPanel(self.property_window,width=360);self.editor_settings.pack(fill='both',expand=True)
        controls=self.editor_settings.content
        self.part=self.field(controls,'部位',Choice(controls))
        self.part.bind('<<ComboboxSelected>>',lambda e:self.guard(self.update_part))
        self.presence=self.field(controls,'部位是否存在',Choice(controls,PRESENCE))
        self.presence.bind('<<ComboboxSelected>>',lambda e:self.guard(self.set_presence))
        self.semantics=ttk.Label(controls,wraplength=330);self.semantics.pack(fill='x')
        self.visibility=self.field(controls,'方向可见性',Choice(controls,VISIBILITY))
        self.visibility.bind('<<ComboboxSelected>>',lambda e:self.guard(lambda:self.patch_direction({'visibility':self.visibility.key()})))
        self.missing=self.field(controls,'方向缺失原因',Choice(controls,MISSING));self.missing.choose('not_discernible')
        self.point_reason=self.field(controls,'点位缺失原因',Choice(controls,MISSING));self.point_reason.choose('not_discernible')
        bar=Toolbar(controls);bar.pack(fill='x')
        ttk.Label(bar,text='方向角度').pack(side='left');self.angle=ttk.Entry(bar,width=7);self.angle.pack(side='left')
        self.button(bar,'应用',self.apply_angle)
        ttk.Label(controls,text='0° 向右，90° 向下；尾巴表示初始伸出方向。',wraplength=320).pack(fill='x')
        self.button(controls,'仅审核部位存在性',lambda:self.review('approved',False),side='top',fill='x')
        self.button(controls,'驳回此方向',lambda:self.review('rejected',True),side='top',fill='x')
        self.button(controls,'身份、视角与分组…',self.context_editor,side='top',fill='x')
        self.update_annotation_mode()

    def choose_record(self):
        self.record_browser.deiconify();self.record_browser.lift();self.record_filter.focus_set()

    def open_selected_record(self):
        self.select_record();self.record_browser.withdraw();self.tabs.select(self.editor_tab)

    def annotation_properties(self):
        self.property_window.deiconify();self.property_window.lift()

    def choose_query_image(self):
        self.clean()
        path=filedialog.askopenfilename(parent=self,title='选择查询图片',filetypes=[('图片','*.png *.jpg *.jpeg *.webp *.bmp'),('所有文件','*.*')])
        if not path:return
        win=tk.Toplevel(self);win.title('查询图片的角色');box=dialog_form(win)
        form=self.field(box,'角色／形态',Choice(box,{r['id']:r['label'] for r in self.catalog.data['forms']}))
        form.choose(self.session.record['subject'].get('form_ref') if self.session.record else self.form.key())
        ttk.Label(box,text='图片用于查询，不进入训练集。若图片有多个角色，可从 M01 框选其中一个。',wraplength=390).pack(fill='x',pady=8)
        def apply():
            self.import_query_image(path,form.key());win.destroy()
        self.button(box,'载入并标注',apply)

    def import_query_image(self,path,form_ref):
        self.clean();actor=self.actor.get()
        def task():
            # Query input is a library image; the original file remains unchanged.
            from multispecies import new_observation
            from PIL import ImageOps
            with Image.open(path) as image:
                image=ImageOps.exif_transpose(image).convert('RGBA')
                output=io.BytesIO();image.save(output,'PNG')
            asset=self.session.library.upload_image(output.getvalue())
            form=self.catalog.get('forms',form_ref)
            record=new_observation(self.catalog,profile_ref=form['profile_ref'],image_ref=asset['id'],
                image_size=asset['size'],character_ref=form.get('character_ref'),form_ref=form_ref,
                collection='query',actor=actor)
            record['source']['label']=Path(path).name
            self.session.library.save(record)
            return record
        def done(record):
            self.query_observation=record['observation_id']
            self.collection.choose('all');self.refresh_records();self.load_record(record['observation_id'])
            self.open_module('M07')
        self.run('正在载入查询图片…',task,done)

    def clear_direction(self):
        self.patch_direction({'value':None,'missing_reason':self.missing.key() or 'not_discernible'})
        self.next_annotation(1)

    def derive_from_points(self):
        if self.session.dirty:
            require(not self.active_suggestion,'请先完成当前建议审核。')
            self.save_record(after=self.lifecycle.derive_dialog)
        else:self.lifecycle.derive_dialog()

    def refresh_records(self):
        self.rows=self.session.service.records();self.render_records()

    def render_records(self):
        selected=self.session.record['observation_id'] if self.session.record else None
        query=self.record_filter.get().casefold()
        self.records.delete(*self.records.get_children())
        for r in self.rows:
            char=self.catalog.tables['characters'].get(r['subject'].get('character_ref'),{}).get('label','身份未确认')
            name=r.get('legacy',{}).get('sample_id') or r['source'].get('label') or r['observation_id']
            if (self.collection.key()!='all' and r['collection']!=self.collection.key()) or query not in (char+' '+name).casefold():continue
            known=sum(d['value'] is not None for d in r['annotation']['directions'].values())
            self.records.insert('','end',iid=r['observation_id'],values=(char+' · '+name,str(known)))
        if selected and self.records.exists(selected):self.records.selection_set(selected)

    def select_record(self):
        selected=self.records.selection()
        if not selected:return
        if self.session.record and selected[0]==self.session.record['observation_id']:return
        try:self.load_record(selected[0])
        except Exception:
            if self.session.record and self.records.exists(self.session.record['observation_id']):self.records.selection_set(self.session.record['observation_id'])
            raise

    def load_record(self, oid, revision=None):
        self.clean();record=self.session.load(oid,revision)
        self.active_suggestion=None
        # A refresh may already have queued a selection event for the previous
        # record. Align the actual selection before that event is dispatched.
        if self.records.exists(oid):
            self.records.selection_set(oid)
            self.records.see(oid)
        else:
            self.records.selection_remove(*self.records.selection())
        self.catalog=self.session.library.catalog
        name=record.get('legacy',{}).get('sample_id') or record['source'].get('label') or oid
        self.record_title.configure(text=name)
        self.pose_picture.set_image(None)
        try:
            raw,_=self.session.library.image_bytes(record['image_ref'])
            with Image.open(io.BytesIO(raw)) as im:self.pose_picture.set_image(im.convert('RGBA'))
        except Exception as exc:
            self.status.set('图片不可用：'+str(exc))
        self.part.set_items({p['slot']:label(p['slot']) for p in self.catalog.get('profiles',record['profile_ref'])['parts']})
        contracts={c['id']:c['label']+('（草案）' if c['status']=='draft' else '') for c in self.catalog.data['contracts'] if record['profile_ref'] in c['projections']}
        self.contract.set_items(contracts,'pony.body14@1')
        self.contract_note.configure(text=self.contract.get())
        self.refresh_comparison_weights()
        from multispecies.keypoints import PROFILES, ORDER
        if record['profile_ref'] in PROFILES:
            points=record['annotation'].get('keypoints',{}).get('points',{})
            has_points=any(p['value'] is not None or p.get('missing_reason') not in (None,'not_annotated') for p in points.values())
            has_directions=any(d['value'] is not None for d in record['annotation']['directions'].values())
            self.annotation_mode.choose('keypoints' if has_points or not has_directions else 'directions')
            first=next((k for k in ORDER if not points.get(k) or points[k].get('missing_reason')=='not_annotated'),ORDER[0])
            self.point_key.choose(first)
        else:self.annotation_mode.choose('directions')
        self.update_part();self.update_annotation_mode();self.refresh_editor_state()
        if self.on_change:self.on_change()

    def refresh_editor_state(self):
        s=self.session
        if not s.record:return
        self.record_state.set('历史版本 · 只读' if s.historical else '有未保存修改' if s.dirty else '已保存 · '+s.record['annotation']['author'])
        self.save_button.configure(state='normal' if s.dirty and not s.historical else 'disabled',
                                   text='修改后接受建议' if self.active_suggestion else '保存 (Ctrl+S)')
        self.save_button.master._schedule()
        if self.annotation_mode.key()=='keypoints':
            points=s.draft['annotation'].get('keypoints',{}).get('points',{})
            self.pose_picture.lines={};self.pose_picture.points={k:p['value'] for k,p in points.items() if p['value'] is not None}
            self.pose_picture.active=self.point_key.key();self.pose_picture.redraw()
            self.point_key.show_states({k:(f"({p['value'][0]:.0f}, {p['value'][1]:.0f})" if p['value'] is not None else
                '缺失' if p.get('missing_reason')!='not_annotated' else '—') for k,p in points.items()})
            p=points.get(self.point_key.key())
            self.point_state.configure(text=(REVIEWS.get(p['review_status'],p['review_status'])+' · '+str(p['value'])) if p else '尚未标注此点')
            return
        self.pose_picture.points={}
        self.pose_picture.lines=copy.deepcopy(s.draft['annotation'].get('reference_points') or {})
        # Direct vector labels may have no reference points. A compass-like arrow
        # shows their direction without inventing anatomical positions.
        key=self.direction.key()
        direction=s.draft['annotation']['directions'].get(key)
        if direction and direction['value'] is not None and key not in self.pose_picture.lines and self.pose_picture.image:
            w,h=self.pose_picture.image.size
            start=[w/2,h/2];length=min(w,h)*.25
            self.pose_picture.lines[key]={'start':start,'end':[start[i]+direction['value'][i]*length for i in (0,1)]}
        self.pose_picture.active=self.direction.key();self.pose_picture.redraw()
        self.direction.show_states({k:(f"{math.degrees(math.atan2(d['value'][1],d['value'][0])):.0f}°" if d['value'] is not None else '—')
            for k,d in s.draft['annotation']['directions'].items()})

    def update_part(self):
        if not self.session.draft:return
        slot=self.part.key();part=self.session.draft['annotation']['parts'][slot]
        self.presence.choose(part['presence'])
        channels=self.catalog.channels(self.session.draft['profile_ref'])
        selected=self.direction.key()
        if not selected or not selected.startswith(slot+'.'):
            selected=next((k for k,v in channels.items() if v['slot']==slot),None)
        self.direction.set_items({k:label(v['slot'])+' · '+label(v['key']) for k,v in channels.items()},selected)
        self.pose_picture.first=None;self.update_direction()

    def update_direction(self):
        if not self.session.draft:return
        a=self.session.draft['annotation'];key=self.direction.key()
        if key:
            self.part.choose(key.split('.')[0]);self.presence.choose(a['parts'][self.part.key()]['presence'])
        d=a['directions'].get(key);definition=self.catalog.channels(self.session.draft['profile_ref']).get(key)
        self.semantics.configure(text=(definition['from_semantic']+' → '+definition['to_semantic']) if definition else '')
        self.visibility.choose(d['visibility'] if d else 'unknown');self.angle.delete(0,'end')
        if d and d['value'] is not None:self.angle.insert(0,f"{math.degrees(math.atan2(d['value'][1],d['value'][0])):.1f}")
        if d:self.missing.choose(d['missing_reason'])
        self.direction_state.set(('方向：'+REVIEWS.get(d['review_status'],d['review_status'])+
                                  ('\n无图上参考点，箭头居中示意方向。' if d['value'] is not None and key not in (a.get('reference_points') or {}) else '')) if d else '请先确认部位存在，再标注方向。')
        if d and d.get('derived_from',{}).get('stale'):
            self.direction_state.set('派生方向已过期：相关点位已改变。请在 M06 查看差异并重新派生。')
        self.pose_picture.first=None;self.refresh_editor_state()

    def patch(self, value):
        require(not self.busy,'当前操作尚未完成。')
        self.session.edit(value,self.actor.get());self.update_direction()

    def set_presence(self):
        require(self.session.draft,'请先选择记录。')
        self.patch({'parts':{self.part.key():{'presence':self.presence.key()}}});self.update_part()

    def patch_direction(self, patch):
        require(self.session.draft and self.direction.key() in self.session.draft['annotation']['directions'],'请先确认部位存在。')
        self.patch({'directions':{self.direction.key():patch}})

    def draw_direction(self, start, end):
        require(self.pose_picture.image is not None,'图片不可用，不能在图上标注。')
        require(self.session.draft,'请先选择姿态。')
        key=self.direction.key();slot=key.split('.')[0]
        require(self.session.draft['annotation']['parts'][slot]['presence']!='absent','此部位已标为不存在，请在标注属性中核对。')
        parts={slot:{'presence':'present'}} if self.session.draft['annotation']['parts'][slot]['presence']=='unknown' else {}
        self.patch({'parts':parts,'directions':{key:{'reference_points':{'start':start,'end':end},'visibility':'visible'}}})

    def update_annotation_mode(self):
        from multispecies.keypoints import PROFILES
        if self.annotation_mode.key()=='keypoints' and self.session.record and self.session.record['profile_ref'] not in PROFILES:
            self.annotation_mode.choose('directions')
            self.status.set('当前身体暂无已定义的点位模式，请使用方向标注。')
        point=self.annotation_mode.key()=='keypoints'
        self.pose_picture.mode='point' if point else 'direction'
        self.pose_picture.first=None
        (self.direction_controls if point else self.point_controls).pack_forget()
        (self.point_controls if point else self.direction_controls).pack(fill='both',expand=True)
        self.refresh_editor_state()

    def draw_annotation(self,start,end):
        if self.annotation_mode.key()=='keypoints':
            require(self.session.record,'请先选择姿态')
            points=self.session.draft['annotation'].get('keypoints',{}).get('points',{})
            clicked=next((key for key,p in points.items() if p['value'] is not None and
                math.dist(p['value'],end)*self.pose_picture.scale<10),None)
            if clicked:
                self.point_key.choose(clicked);self.refresh_editor_state();return
            self.patch({'keypoints':{'points':{self.point_key.key():{'value':end,'visibility':'visible'}}}})
            # AI review remains on the edited point until explicitly accepted.
            if not self.active_suggestion:self.next_point()
        else:
            self.draw_direction(start,end)
            if not self.active_suggestion:self.next_annotation(1)

    def clear_point(self):
        self.patch({'keypoints':{'points':{self.point_key.key():{'value':None,'missing_reason':self.point_reason.key() or 'not_discernible','visibility':'unknown'}}}})
        if not self.active_suggestion:self.next_point()

    def next_point(self):
        self.next_annotation(1,points=True)

    def next_annotation(self,delta,points=False):
        control=self.point_key if points or self.annotation_mode.key()=='keypoints' else self.direction
        control.current(control.current()+delta)
        if control is self.direction:self.update_direction()
        else:self.refresh_editor_state()

    def review_point(self):
        require(self.session.draft and self.session.draft['annotation'].get('keypoints'),'请先标出点位或填写缺失原因')
        point=self.session.draft['annotation']['keypoints']['points'][self.point_key.key()]
        require(point['value'] is not None or point['missing_reason']!='not_annotated','当前点尚未标注。请先点选或标记缺失。')
        self.save_record({'status':'approved','targets':['keypoints.'+self.point_key.key()]})

    def next_record(self,delta=1):
        require(not self.busy,'正在保存，请稍候。')
        ids=list(self.records.get_children());require(ids,'没有可标注记录')
        current=self.session.record['observation_id'] if self.session.record else None
        index=max(0,min(ids.index(current)+delta,len(ids)-1)) if current in ids else 0
        if current==ids[index]:return
        self.navigate_record(ids[index])

    def navigate_record(self,oid):
        if self.session.dirty:
            require(not self.active_suggestion,'请先完成或放弃当前建议审核。')
            self.save_record(after=lambda:self.load_record(oid))
        else:self.load_record(oid)

    def jump_unannotated(self):
        from multispecies.keypoints import ORDER
        ids=list(self.records.get_children());require(ids,'没有可标注记录')
        current=self.session.record['observation_id'] if self.session.record else None
        start=ids.index(current)+1 if current in ids else 0
        for oid in ids[start:]+ids[:start]:
            record=self.session.library.read(oid)
            if self.annotation_mode.key()=='keypoints':
                from multispecies.keypoints import PROFILES
                if record['profile_ref'] not in PROFILES:continue
                points=record['annotation'].get('keypoints',{}).get('points',{})
                incomplete=any(k not in points or points[k].get('missing_reason')=='not_annotated' for k in ORDER)
            else:incomplete=any(d['value'] is None and d.get('missing_reason')=='not_annotated' for d in record['annotation']['directions'].values()) or not record['annotation']['directions']
            if incomplete:
                self.navigate_record(oid);return
        self.status.set('当前筛选范围内没有未完成的样本。')

    def apply_angle(self):
        angle=math.radians(float(self.angle.get()))
        self.patch_direction({'value':[math.cos(angle),math.sin(angle)]})

    def save_record(self, review=None, after=None):
        actor=self.actor.get()
        suggestion=copy.deepcopy(self.active_suggestion)
        def done(result):
            if suggestion:self.active_suggestion=result if result['status']=='pending' else None
            self.refresh_records();self.update_part();self.lifecycle.refresh_models()
            self.status.set('本次审核已保存；其余建议仍待审核。' if self.active_suggestion else '已保存新版本，旧版本保留。')
            if after:after()
        task=(lambda:self.session.save_suggestion(suggestion,actor,review)) if suggestion else (lambda:self.session.save(actor,review))
        self.run('正在保存标注…',task,done)

    def discard_record(self):
        require(not self.busy,'当前操作尚未完成。')
        if self.session.dirty and not messagebox.askyesno('放弃修改','放弃本次尚未保存的修改？',parent=self):return
        self.session.discard();self.active_suggestion=None;self.update_part()

    def review(self, status, direction):
        require(self.session.draft,'请先选择记录。')
        targets=['parts.'+self.part.key()]
        if direction:
            require(self.direction.key() in self.session.draft['annotation']['directions'],'此部位尚未确认存在。')
            targets+=['directions.'+self.direction.key()]
        if status=='rejected':targets=targets[-1:]
        self.save_record({'targets':targets,'status':status})

    def history(self):
        self.clean();require(self.session.record,'请先选择记录。')
        oid=self.session.record['observation_id'];win=tk.Toplevel(self);win.title('历史版本（只读）');win.geometry('680x400')
        tree=self.tree(win,{'time':('保存时间',260),'author':('标注者',160),'version':('版本',160)})
        for r in reversed(self.session.library.history(oid)):
            a=r['annotation'];tree.insert('','end',iid=a['id'],values=(a['created_at'],a['author'],a['id']))
        bar=Toolbar(win);bar.pack(fill='x')
        def load(latest=False):
            if not latest:require(tree.selection(),'请先选择版本。')
            self.load_record(oid,None if latest else tree.selection()[0]);win.destroy()
        self.button(bar,'查看所选版本',load);self.button(bar,'返回当前版本',lambda:load(True))
        bar.pack_configure(side='bottom',before=tree.master)

    def context_editor(self):
        require(self.session.draft and not self.session.historical,'请先载入当前版本。')
        win=tk.Toplevel(self);win.title('身份、视角与分组');win.geometry('410x620')
        box=dialog_form(win)
        a=self.session.draft['annotation'];slot=self.part.key();identity=a['parts'][slot]['identity']
        side=self.field(box,'所选部位身体侧别',Choice(box,{'':'未知','left':'身体左侧','right':'身体右侧','midline':'中线'}));side.choose(identity['anatomical_side'] or '')
        depth=self.field(box,'所选部位镜头远近',Choice(box,{'':'未知','near':'近侧','far':'远侧'}));depth.choose(identity['camera_depth'] or '')
        asset=self.field(box,'工程部件路径（有证据再填写）',ttk.Entry(box));asset.insert(0,identity['asset_path'] or '')
        views={}
        for key,title in [('body','身体视角'),('head','头部视角')]:
            views[key]=self.field(box,title,Choice(box,VIEWS));views[key].choose(a['view'].get(key,{}).get('value',''))
        groups={}
        for key,title in [('shot_ref','镜头组'),('asset_family_ref','复用素材族')]:
            groups[key]=self.field(box,title,ttk.Entry(box));groups[key].insert(0,self.session.draft['split_groups'].get(key) or '')
        ttk.Label(box,text='不确定的身份与分组请留空。同一镜头或模板的训练划分依赖这些分组。',wraplength=365).pack(fill='x',pady=8)
        original=self.session.record['observation_id']
        def apply():
            require(self.session.record['observation_id']==original,'当前记录已切换，请重新打开此面板。')
            profile=self.session.record['profile_ref']
            view={k:{'value':v.key(),'definition_ref':'pony.view5@1' if profile.startswith('pony.') else profile+'/view5'} for k,v in views.items() if v.key()}
            self.patch({'parts':{slot:{'identity':{'anatomical_side':side.key() or None,'camera_depth':depth.key() or None,'asset_path':asset.get().strip() or None}}},
                        'view':view,'split_groups':{k:v.get().strip() or None for k,v in groups.items()}});win.destroy()
        self.button(box,'应用到待保存修改',apply,side='top',fill='x')

    def add_character(self):
        win=tk.Toplevel(self);win.title('新增角色或形态');win.geometry('440x440')
        box=dialog_form(win)
        existing=self.field(box,'角色',Choice(box,{'':'新建角色',**{r['id']:r['label'] for r in self.catalog.data['characters']}}))
        name=self.field(box,'角色名称',ttk.Entry(box))
        form=self.field(box,'形态名称',ttk.Entry(box))
        species=self.field(box,'物种标签',Choice(box,{r['id']:r['label'] for r in self.catalog.data['species']}))
        profile=self.field(box,'身体结构',Choice(box,{r['id']:r['label'] for r in self.catalog.data['profiles']}))
        def create():
            self.clean()
            character_name=name.get().strip() or (self.catalog.get('characters',existing.key())['label'] if existing.key() else '')
            self.session.library.add_character(character_name,species_ref=species.key(),profile_ref=profile.key(),form_label=form.get().strip() or None,character_ref=existing.key() or None)
            self.catalog=self.session.library.catalog
            self.form.set_items({r['id']:r['label'] for r in self.catalog.data['forms']})
            self.refresh_search_choices();win.destroy();self.status.set('角色／形态已登记，建立记录时可选择。')
        self.button(box,'登记角色与形态',create,side='top',fill='x')

    def _build_results(self):
        self.search_tab=ttk.Frame(self.tabs);self.tabs.add(self.search_tab,text='搜索设置')
        self.search_settings=ScrollPanel(self.search_tab,width=900);self.search_settings.pack(fill='both',expand=True)
        settings=self.search_settings.content
        self.query_label=ttk.Label(settings,text='先在 M07 选择或标注查询图片。',wraplength=800)
        self.query_label.pack(fill='x',pady=5)
        bar=Toolbar(settings);bar.pack(fill='x')
        self.button(bar,'修改查询姿态 → M07',lambda:self.open_module('M07'))
        self.search_button=self.button(bar,'搜索并查看结果',self.search)
        self.query_save_button=self.button(bar,'保存查询条件',self.save_query)
        self.saved_search_button=self.button(bar,'重跑已保存查询',self.search_saved_query)
        columns=ttk.Frame(settings);columns.pack(fill='x',pady=6)
        columns.columnconfigure((0,1),weight=1)
        basic=ttk.LabelFrame(columns,text='搜索范围',padding=8);basic.grid(row=0,column=0,sticky='nsew',padx=(0,6))
        weights=ttk.LabelFrame(columns,text='部位权重',padding=8);weights.grid(row=0,column=1,sticky='nsew')
        self.contract=self.field(basic,'比较范围',Choice(basic))
        self.contract_note=ttk.Label(basic)
        self.contract.bind('<<ComboboxSelected>>',lambda e:self.guard(self.refresh_comparison_weights))
        self.search_character=self.field(basic,'角色',Choice(basic))
        self.search_species=self.field(basic,'物种',Choice(basic));self.refresh_search_choices()
        row=ttk.Frame(basic);row.pack(fill='x',pady=4)
        ttk.Label(row,text='返回数量 Top N').pack(side='left')
        self.top_n=ttk.Spinbox(row,from_=1,to=1000,width=7);self.top_n.insert(0,'15');self.top_n.pack(side='left',padx=5)
        for text,var in [('允许左右翻转',self.mirror),('允许同类整腿交换',self.exchange)]:
            ttk.Checkbutton(basic,text=text,variable=var).pack(anchor='w')
        self.weight_fields=ttk.Frame(weights);self.weight_fields.pack(fill='x')
        self.group_weight_vars={}
        self.view_weight=tk.StringVar(self,'0.10');self.layout_weight=tk.StringVar(self,'0.05')
        for title,var in [('视角辅助',self.view_weight),('相对位置辅助',self.layout_weight)]:
            row=ttk.Frame(weights);row.pack(fill='x',pady=2)
            ttk.Label(row,text=title,width=18).pack(side='left');ttk.Entry(row,textvariable=var,width=8).pack(side='left')
        ttk.Label(weights,text='方向为主；两项辅助权重合计不超过 0.25。',wraplength=300).pack(fill='x',pady=5)
        advanced=ttk.LabelFrame(settings,text='审核与素材定位条件',padding=8);advanced.pack(fill='x')
        self.search_advanced=advanced
        for i,(text,var) in enumerate([('仅原素材可用',self.source_available),('仅能精确定位',self.source_exact),
            ('仅有同名工程线索',self.source_related),('严格匹配已知部位身份',self.strict_identity),
            ('包含未审核方向',self.unreviewed),('包含实验／待审资料',self.experimental),('允许使用草案比较规则',self.draft_contract)]):
            ttk.Checkbutton(advanced,text=text,variable=var).grid(row=i//2,column=i%2,sticky='w',padx=4,pady=2)
        advanced.columnconfigure((0,1),weight=1)
        row=ttk.Frame(settings);row.pack(fill='x',pady=4)
        ttk.Label(row,text='最低覆盖率（0 到 1）').pack(side='left')
        self.coverage=ttk.Entry(row,width=8);self.coverage.insert(0,'0');self.coverage.pack(side='left',padx=5)
        self.source_filter_button=self.button(row,'来源格式与目录…',self.source_filter_options)
        self.scope_note=ttk.Label(settings,wraplength=750);self.scope_note.pack(fill='x',pady=4)
        for variable in (self.unreviewed,self.experimental,self.draft_contract,self.source_exact,self.source_available,self.source_related):
            variable.trace_add('write',lambda *args:self.update_scope_note())
        self.update_scope_note()
        right=self.results_tab
        bar=Toolbar(right);bar.pack(fill='x')
        self.button(bar,'返回 M08 修改条件',lambda:self.open_module('M08'))
        self.button(bar,'导出结果 CSV / JSON',lambda:self.show_export(self.session.export_results()))
        self.button(bar,'导出离线浏览 HTML',lambda:self.show_export(self.session.export_html()))
        self.result_summary=ttk.Label(right,text='尚未搜索。到 M08 设置条件并搜索。',wraplength=900)
        self.result_summary.pack(fill='x',pady=4)
        self.result_views=ttk.Notebook(right);self.result_views.pack(fill='both',expand=True)
        from classic_widgets import ResultGallery
        self.gallery=ResultGallery(self.result_views,self);self.result_views.add(self.gallery,text='原画面与裁剪（M09）')
        details=ttk.Frame(self.result_views);self.result_views.add(details,text='列表与放大查看')
        row=Toolbar(details);row.pack(side='bottom',fill='x')
        self.button(row,'查看原画面／帧号',self.open_result_source)
        self.button(row,'在文件夹中选中',self.locate_result)
        self.button(row,'复制素材位置',lambda:self.copy_text(self.current_hit()['position_text']))
        self.button(row,'查看命中标注',self.open_result_record)
        self.hit_location=tk.Text(details,height=3,wrap='word');self.hit_location.pack(side='bottom',fill='x');self.hit_location.configure(state='disabled')
        self.hit_caption=ttk.Label(details,wraplength=850);self.hit_caption.pack(side='bottom',fill='x')
        panes=ttk.Panedwindow(details,orient='vertical');panes.pack(fill='both',expand=True)
        table=ttk.Frame(panes,height=160);preview=ttk.Frame(panes,height=300)
        panes.add(table,weight=1);panes.add(preview,weight=3)
        self.results=self.tree(table,{'name':('角色 / 素材',270),'position':('来源位置',130),
            'score':('相似分',75),'coverage':('覆盖率',75),'mirror':('朝向',110)},height=5)
        self.results.bind('<<TreeviewSelect>>',lambda e:self.guard(self.select_result) if self.results.selection() else None)
        self.hit_picture=Picture(preview,empty='选择结果，查看命中姿态');self.hit_picture.pack(fill='both',expand=True)

    def refresh_comparison_weights(self):
        contract=self.contract.key()
        if not contract:return
        definition=self.catalog.get('contracts',contract);saved=self.comparison_options.get(contract,{})
        for child in self.weight_fields.winfo_children():child.destroy()
        self.group_weight_vars={}
        titles={'front_legs':'前肢','back_legs':'后肢','forelimbs':'前肢','hindlimbs':'后肢'}
        for group in definition['groups']:
            row=ttk.Frame(self.weight_fields);row.pack(fill='x',pady=2)
            key=group['id'];ttk.Label(row,text=titles.get(key,label(key)),width=18).pack(side='left')
            var=tk.StringVar(self,str(saved.get('group_weights',{}).get(key,group['weight'])))
            ttk.Entry(row,textvariable=var,width=8).pack(side='left');self.group_weight_vars[key]=var
        self.view_weight.set(str(saved.get('view_weight',.10)));self.layout_weight.set(str(saved.get('layout_weight',.05)))
        self.contract_note.configure(text=self.contract.get())

    def update_scope_note(self):
        flags=[self.advanced_source_filters.get('format') or '全部格式', '含未审方向' if self.unreviewed.get() else '已审方向']
        for enabled,label in [(self.experimental.get(),'含实验资料'),(self.draft_contract.get(),'含草案规则'),(self.source_exact.get(),'精确定位'),(self.source_available.get(),'原文件可用'),(self.source_related.get(),'有工程线索'),(bool(self.advanced_source_filters.get('root_id')),'指定素材目录')]:
            if enabled:flags.append(label)
        self.scope_note.configure(text=' · '.join(flags))

    def refresh_search_choices(self):
        self.search_character.set_items({'':'全部角色',**{r['id']:r['label'] for r in self.catalog.data['characters']}})
        self.search_species.set_items({'':'全部物种',**{r['id']:r['label'] for r in self.catalog.data['species']}})

    def prepare_search(self):
        self.clean();require(self.session.record,'请先选择姿态记录。')
        self.query_observation=self.session.record['observation_id']
        self.query_label.configure(text='查询姿态：'+self.record_title.cget('text'))
        self.update_scope_note()
        self.tabs.select(self.search_tab)
        self._highlight_module('M08')

    def query_inputs(self):
        self.prepare_search()
        options=dict(allow_mirror=self.mirror.get(),allow_whole_limb_exchange=self.exchange.get(),strict_identity=self.strict_identity.get(),
                     include_unreviewed=self.unreviewed.get(),allow_draft=self.draft_contract.get(),
                     collections=['official','manual']+(['experimental'] if self.experimental.get() else []),
                     character_ref=self.search_character.key() or None,species_ref=self.search_species.key() or None,
                     minimum_coverage=float(self.coverage.get()),top_n=int(self.top_n.get()))
        filters=dict(self.advanced_source_filters,exact=self.source_exact.get(),available=self.source_available.get(),related=self.source_related.get())
        contract=self.contract.key();require(contract,'此身体结构没有可用的比较规则。')
        options.update(copy.deepcopy(self.comparison_options.get(contract,{})))
        options.update(group_weights={k:float(v.get()) for k,v in self.group_weight_vars.items()},
                       view_weight=float(self.view_weight.get()),layout_weight=float(self.layout_weight.get()))
        return contract,options,filters

    def query_description(self, spec):
        record=self.session.library.read(spec['observation_id'],spec['annotation_id'])
        character=self.catalog.tables['characters'].get(record['subject'].get('character_ref'),{}).get('label','身份未确认')
        return character+' / '+(record['source'].get('label') or record.get('legacy',{}).get('sample_id') or '姿态记录')

    def restore_query(self, spec):
        self.query_observation=spec['observation_id']
        self.load_record(spec['observation_id'],spec['annotation_id'])
        self.contract.choose(spec['contract_ref'])
        self.contract_note.configure(text=self.contract.get())
        opts,filters=spec['options'],spec['source_filters']
        for variable,key in ((self.mirror,'allow_mirror'),(self.exchange,'allow_whole_limb_exchange'),
                             (self.strict_identity,'strict_identity'),(self.unreviewed,'include_unreviewed'),(self.draft_contract,'allow_draft')):
            variable.set(opts[key])
        self.experimental.set('experimental' in opts['collections'])
        self.search_character.choose(opts['character_ref'] or '');self.search_species.choose(opts['species_ref'] or '')
        for entry,value in ((self.top_n,opts['top_n']),(self.coverage,opts['minimum_coverage'])):
            entry.delete(0,'end');entry.insert(0,str(value))
        self.advanced_source_filters={k:filters.get(k,'') for k in ('format','root_id')}
        self.source_exact.set(filters.get('exact',False));self.source_available.set(filters.get('available',False));self.source_related.set(filters.get('related',False))
        self.comparison_options[spec['contract_ref']]={k:copy.deepcopy(opts[k]) for k in ('group_weights','view_weight','layout_weight')}
        self.refresh_comparison_weights()
        self.update_scope_note()
        self.query_label.configure(text='已保存：'+self.query_description(spec)+'\n使用保存时的标注与条件')

    def comparison_settings(self):
        contract=self.contract.key();require(contract,'请先选择查询姿态和比较范围。')
        definition=self.catalog.get('contracts',contract)
        saved=self.comparison_options.get(contract,{})
        win=tk.Toplevel(self);win.title('比较权重');box=dialog_form(win)
        entries={}
        for group in definition['groups']:
            entry=self.field(box,'部位组 '+group['id'],ttk.Entry(box))
            entry.insert(0,str(saved.get('group_weights',{}).get(group['id'],group['weight'])))
            entries[group['id']]=entry
        view=self.field(box,'视角辅助权重',ttk.Entry(box));view.insert(0,str(saved.get('view_weight',.10)))
        layout=self.field(box,'相对位置辅助权重',ttk.Entry(box));layout.insert(0,str(saved.get('layout_weight',.05)))
        ttk.Label(box,text='两个辅助项合计不超过 0.25。保存 M07 查询后用于 M08。',wraplength=360).pack(pady=8)
        def apply():
            values={'group_weights':{k:float(e.get()) for k,e in entries.items()},'view_weight':float(view.get()),'layout_weight':float(layout.get())}
            require(all(math.isfinite(v) and v>=0 for v in values['group_weights'].values()),'部位权重须为有限非负数')
            require(all(math.isfinite(values[k]) and 0<=values[k]<=.25 for k in ('view_weight','layout_weight')) and
                    values['view_weight']+values['layout_weight']<=.25,'辅助权重合计不能超过 0.25')
            self.comparison_options[contract]=values;self.refresh_comparison_weights();win.destroy()
        self.button(box,'应用到查询设置',apply)

    def save_query(self):
        contract,options,filters=self.query_inputs()
        self.run('正在保存查询条件…',lambda:self.session.prepare_query(contract,options,filters),
                 lambda spec:self.status.set('M07 已保存查询；固定标注版本 '+spec['annotation_id']))

    def search_saved_query(self):
        self.clean()
        query_id=self.session.workflow.current().get('query_id')
        require(query_id,'请先在 M07 保存查询条件。')
        self.restore_query(self.session.workflow.query(query_id))
        self.tabs.select(self.results_tab)
        self.run('正在执行 M07 已保存的查询…',lambda:self.session.search_saved_query(query_id),self.render_results)

    def search(self):
        contract,options,filters=self.query_inputs()
        self.run('正在比较姿态…',lambda:self.session.find(contract,options,filters),self.render_results)

    def render_results(self, data):
        spec=data.get('query_spec')
        if spec:self.query_label.configure(text='结果依据：'+self.query_description(spec)+'\n已固定查询时的标注版本')
        self.results.delete(*self.results.get_children());self.hit_picture.set_image(None);self.text(self.hit_location,'')
        self.hit_caption.configure(text='')
        for index,row in enumerate(data['results']):
            location=row['location'];record=self.session.library.read(row['observation_id'],row['annotation_id'])
            character=self.catalog.tables['characters'].get(record['subject'].get('character_ref'),{}).get('label','身份未确认')
            position=location.get('position') or {};caption=position_caption(position)
            source_position=(location.get('format') or '')+(' · '+caption if caption else ' · 图片' if row['source'].get('precision')=='image_exact' else '')
            self.results.insert('','end',iid=str(index),values=(character+' / '+location['name'],source_position,
                                f"{row['score']:.3f}",f"{row['candidate_coverage']:.0%}",'需左右翻转' if row['mirrored'] else '原始朝向'))
        self.result_summary.configure(text=f"找到 {data['total_eligible']} 条可比较记录，显示 {len(data['results'])} 条。\n"+
                                      ('没有结果时，可检查审核状态、方向是否已标注及比较范围。' if not data['results'] else '相似分用于排序；修改条件请返回 M08。'))
        if data['results']:self.results.selection_set('0')
        self.gallery.render(data)
        self.tabs.select(self.results_tab)
        self._highlight_module('M09')

    def current_hit(self):
        require(self.results.selection() and self.session.last_results,'请先选择搜索结果。')
        return self.session.last_results['results'][int(self.results.selection()[0])]

    def select_result(self):
        if not self.results.selection():return
        row=self.current_hit();self.hit_picture.set_image(None);self.text(self.hit_location,readable_location(row['position_text']))
        location=row['location'];caption=position_caption(location.get('position'))
        self.hit_caption.configure(text=location['name']+' · '+(location.get('format') or '')+(' · '+caption if caption else '')+(' · 需左右翻转' if row['mirrored'] else ' · 原始朝向'))
        raw,_=self.session.library.image_bytes(row['image_ref'])
        with Image.open(io.BytesIO(raw)) as im:self.hit_picture.set_image(im.convert('RGBA'))
        r=self.session.library.read(row['observation_id'],row['annotation_id'])
        self.hit_picture.lines=r['annotation'].get('reference_points') or {};self.hit_picture.redraw()

    def open_result_source(self):
        info=self.current_hit()['location'];self.open_location(info)

    def open_location(self, info):
        self.clean()
        if info.get('position_id'):
            self.source_generation+=1;self.show_position(info['position_id']);self.tabs.select(self.files_tab)
        else:self.details('来源位置',readable_location(self.session.service.position_text(info)))

    def record_location(self):
        require(self.session.record,'请先选择姿态。')
        self.open_location(self.session.service.describe(self.session.record))

    def locate_result(self):
        row=self.current_hit();info=row['location']
        args={'position_id':info['position_id']} if info.get('position_id') else {'observation_id':row['observation_id']}
        self.run('正在核验并定位素材…',lambda:self.session.service.locate(**args),lambda r:self.status.set('已请求文件管理器选中素材。'))

    def open_result_record(self):
        row=self.current_hit();self.load_record(row['observation_id'],row['annotation_id']);self.tabs.select(self.editor_tab)

    def show_export(self, paths):
        value='\n'.join(str(p) for p in paths) if isinstance(paths,tuple) else str(paths)
        self.status.set('已导出：'+value)
        self.details('导出完成',value)

    def source_filter_options(self):
        win=tk.Toplevel(self);win.title('搜索结果的来源筛选');win.geometry('520x245')
        box=dialog_form(win)
        formats={'':'全部格式',**{k:k for k in ('MP4','MOV','MKV','AVI','WEBM','M4V','PNG','JPG','JPEG','WEBP','FLA','XFL','SWF')}}
        format_choice=self.field(box,'原素材格式',Choice(box,formats));format_choice.choose(self.advanced_source_filters['format'])
        roots={'':'全部素材目录',**{r['id']:r['path'] for r in self.session.sources.status()['roots']}}
        root_choice=self.field(box,'素材目录',Choice(box,roots));root_choice.choose(self.advanced_source_filters['root_id'])
        def apply():
            self.advanced_source_filters={'format':format_choice.key() or '', 'root_id':root_choice.key() or ''}
            self.update_scope_note()
            self.source_filter_button.configure(text='来源筛选（已设）' if any(self.advanced_source_filters.values()) else '更多来源筛选…')
            win.destroy()
        self.button(box,'应用筛选',apply,side='top',fill='x')

    def training_options(self):
        win=tk.Toplevel(self);win.title('导出已审核训练快照');win.geometry('480x280')
        box=dialog_form(win)
        draft=tk.BooleanVar(win,False);ungrouped=tk.BooleanVar(win,False)
        ttk.Label(box,text='导出已保存、已审核的标注和分组记录，不会启动训练。',wraplength=435).pack(fill='x',pady=6)
        ttk.Checkbutton(box,text='包含尚为草案的部位规则',variable=draft).pack(anchor='w',pady=5)
        ttk.Checkbutton(box,text='包含未知分组（保持未分配，不混入训练／验证）',variable=ungrouped).pack(anchor='w',pady=5)
        ttk.Label(box,text='默认均关闭。新物种规则是否准确、镜头和模板是否属于同组，仍需实际确认。',wraplength=435).pack(fill='x',pady=8)
        def export():
            self.clean()
            options={'allow_draft':draft.get(),'include_ungrouped':ungrouped.get()}
            self.run('正在导出训练快照…',lambda:self.session.export_training(**options),self.show_export)
            win.destroy()
        self.button(box,'保存快照',export,side='top',fill='x')

    def can_close(self):
        if self.busy:
            self.status.set('操作正在完成，请稍后关闭。');return False
        return not self.session.dirty or messagebox.askyesno('尚未保存','放弃当前尚未保存的标注并关闭？',parent=self)

    def close(self):
        if self.closed:return
        self.closed=True
        try:
            self.winfo_toplevel().unbind('<Control-s>',self._save_binding)
            for key,binding in self._editor_bindings.items():self.winfo_toplevel().unbind(key,binding)
        except tk.TclError:
            pass
        try:
            self.after_cancel(self._poll_id);self.after_cancel(self._status_id)
        except tk.TclError:
            pass  # The whole application may already have destroyed its Tcl widgets.
        self.executor.shutdown(wait=True,cancel_futures=True)
        self.session.close()
        self.session.sources.stop()
