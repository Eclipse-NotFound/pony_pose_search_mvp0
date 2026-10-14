"""Native views for the shared candidate/region, preparation and model operations."""
import copy
import io
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog

from PIL import Image
from multispecies.catalog import require, load_json
from multispecies.keypoints import ORDER, PROFILES, proposals
from multispecies.importers import LEGACY_MAPPING
from multispecies.records import new_id

from ui_components import Toolbar, section, split, dialog_form

DECISIONS={'selected':'保留','excluded':'排除','undecided':'待判断'}
TASKS={'directions':'方向模型','keypoints':'点位模型','detection':'角色检测'}


class LifecycleViews:
    def __init__(self, host):
        self.host=host;self.context=host.session.context
        from native_workbench import Choice, Picture
        self.Choice,self.Picture=Choice,Picture
        self.region_id=self.region_revision=None
        self.candidate_id=None
        self.candidate_offset=0;self.task_offset=0
        self.pages={}
        for name in ('regions','preparation','models','tasks'):
            page=ttk.Frame(host.tabs);host.tabs.add(page,text=name);self.pages[name]=page
        self._regions();self._preparation();self._models();self._tasks()

    def button(self, parent, text, action, **kw):return self.host.button(parent,text,action,**kw)

    def _regions(self):
        page=self.pages['regions'];bar=Toolbar(page);bar.pack(fill='x')
        self.button(bar,'刷新候选',self.refresh_regions)
        self.button(bar,'上页',lambda:self.page_candidates(-1))
        self.button(bar,'下页',lambda:self.page_candidates(1))
        for key,label in DECISIONS.items():self.button(bar,label,lambda key=key:self.decide(key))
        self.button(bar,'回到原素材',self.open_candidate_source)
        self.button(bar,'生成全部已审样本',self.generate_all)
        panes,(left,right)=split(page,[310,780],[1,3])
        section(left,'候选画面')
        self.candidates=self.host.tree(left,{'name':('候选画面',165),'state':('判断',70)},height=8)
        self.candidates.bind('<<TreeviewSelect>>',lambda e:self.host.guard(self.select_candidate))
        section(left,'画面中的角色')
        self.regions=self.host.tree(left,{'name':('角色实例',120),'state':('框审核',90),'size':('区域',100)},height=6)
        self.regions.bind('<<TreeviewSelect>>',lambda e:self.host.guard(self.select_region))
        actions=Toolbar(right);actions.pack(side='bottom',fill='x')
        self.button(actions,'保存角色框',self.save_region,style='Primary.TButton')
        self.button(actions,'生成样本 → 标注',self.generate)
        self.button(actions,'框修订历史',self.region_history)
        self.button(actions,'本画面角色已全部框出',self.complete_frame)
        controls=Toolbar(right);controls.pack(side='bottom',fill='x')
        self.region_form=self.Choice(controls,{r['id']:r['label'] for r in self.context.library.catalog.data['forms']},width=25)
        self.region_form.pack(side='left');self.approved=tk.BooleanVar(page,False)
        ttk.Checkbutton(controls,text='已核对区域与形态',variable=self.approved).pack(side='left')
        self.button(controls,'新增另一个角色',self.new_region)
        self.button(controls,'排除此角色框',self.reject_region)
        self.region_note=tk.StringVar(page,'选择候选画面，再框出一个角色。改框后生成新样本，旧标注保留。')
        ttk.Label(right,textvariable=self.region_note,wraplength=600).pack(side='bottom',fill='x',pady=5)
        self.region_picture=self.Picture(right,self.draw_region);self.region_picture.mode='region'
        self.region_picture.pack(fill='both',expand=True)

    def refresh_regions(self):
        self.region_form.set_items({r['id']:r['label'] for r in self.context.library.catalog.data['forms']},self.region_form.key())
        selection=self.candidate_id
        self.candidates.delete(*self.candidates.get_children())
        candidates=self.context.dataset.candidates()
        self.candidate_offset=min(self.candidate_offset,max(0,(len(candidates)-1)//100*100))
        for c in candidates[self.candidate_offset:self.candidate_offset+100]:
            with self.context.sources.db() as db:
                row=db.execute('SELECT f.rel_path,p.payload FROM positions p JOIN files f ON f.id=p.file_id WHERE p.id=?',(c['position_id'],)).fetchone()
            name=Path(row[0]).name if row else c['position_id']
            position=json.loads(row[1]) if row else {}
            if position.get('presentation_ordinal0') is not None:name+=f" · 第{position['presentation_ordinal0']+1}帧"
            self.candidates.insert('','end',iid=c['id'],values=(name,DECISIONS[c['decision']]))
        if selection and self.candidates.exists(selection):self.candidates.selection_set(selection)

    def page_candidates(self, delta):
        self.candidate_offset=max(0,self.candidate_offset+100*delta);self.refresh_regions()

    def focus_candidate(self, candidate_id):
        ids=[c['id'] for c in self.context.dataset.candidates()]
        require(candidate_id in ids,'候选已不可用，请刷新素材')
        self.candidate_offset=ids.index(candidate_id)//100*100
        self.candidate_id=candidate_id
        self.refresh_regions()
        self.candidates.selection_set(candidate_id)
        self.candidates.see(candidate_id)
        self.select_candidate()

    def select_candidate(self):
        selected=self.candidates.selection()
        if not selected:return
        self.candidate_id=selected[0];self.candidate=self.context.dataset.store.read(self.candidate_id)
        with Image.open(self.context.sources.cached_image(self.candidate['position_id'])) as im:self.region_picture.set_image(im.convert('RGBA'))
        self.new_region();self.refresh_region_list()

    def refresh_region_list(self):
        self.regions.delete(*self.regions.get_children())
        if not self.candidate_id:return
        for r in self.context.dataset.regions(self.candidate_id):
            form=self.context.library.catalog.get('forms',r['form_ref'])
            self.regions.insert('','end',iid=r['id'],values=(form['label'],{'approved':'已审核','corrected':'已修正','unreviewed':'待审核','legacy_official':'原正式标注','rejected':'已排除'}.get(r['review_status'],r['review_status']),str(r['roi'])))

    def select_region(self):
        selected=self.regions.selection()
        if not selected:return
        r=self.context.dataset.store.read(selected[0]);self.region_id=r['id'];self.region_revision=r['revision']
        self.region_picture.region=r['roi'];self.region_picture.redraw();self.region_form.choose(r['form_ref'])
        self.approved.set(r['review_status'] in {'approved','corrected','legacy_official'})
        self.region_note.set('正在编辑已有角色。保存改框后，原样本与标注保持原绑定。')

    def new_region(self):
        self.region_id=self.region_revision=None;self.approved.set(False)
        self.region_picture.region=None;self.region_picture.redraw()
        self.region_note.set('新增角色实例：在图上拖出一个框。')

    def draw_region(self,start,end):
        import math
        x,y=math.floor(min(start[0],end[0])),math.floor(min(start[1],end[1]))
        w,h=math.ceil(max(start[0],end[0]))-x,math.ceil(max(start[1],end[1]))-y
        if w<=0 or h<=0:return
        self.region_picture.region=[x,y,w,h];self.region_picture.redraw();self.approved.set(False)
        self.region_note.set(f'区域：{x}, {y} · {w} × {h}，保存前请核对。')

    def decide(self, decision):
        require(self.candidate_id,'请选择候选画面')
        c=self.candidate
        self.candidate=self.context.dataset.decide(c['position_id'],decision,set_id=c['set_id'],expected=c['revision'],actor=self.host.actor.get())
        self.refresh_regions();self.host.status.set('候选判断已保存。')

    def save_region(self):
        require(self.candidate_id and self.region_picture.region,'请先选择候选画面并框选角色')
        r=self.context.dataset.region(self.candidate_id,list(self.region_picture.region),self.region_form.key(),
            region_id=self.region_id,expected=self.region_revision,actor=self.host.actor.get(),
            review_status='approved' if self.approved.get() else 'unreviewed')
        self.region_id,self.region_revision=r['id'],r['revision'];self.refresh_region_list()
        self.candidate=self.context.dataset.store.read(self.candidate_id)
        self.regions.selection_set(r['id']);self.host.status.set('角色框已保存新版本。')

    def generate(self):
        require(self.region_id and self.region_revision,'请先保存并审核角色框')
        jid=self.context.dataset.queue_generate(self.region_id,self.region_revision)
        self.host.watched[jid]=(self.host.source_generation,lambda result:self.generated(result))
        self.host.status.set('样本生成已排队；重复请求会复用同一份样本。')

    def generate_all(self):
        selected={c['id'] for c in self.context.dataset.candidates() if c['decision']=='selected'}
        regions=[r for r in self.context.dataset.regions() if r['candidate_id'] in selected and r['quality']=='keep' and r['review_status'] in {'approved','corrected','legacy_official'}]
        require(regions,'没有已保留且审核通过的角色框')
        for r in regions:self.context.dataset.queue_generate(r['id'],r['revision'])
        self.host.status.set(f'已将 {len(regions)} 个角色框交给样本生成队列；重复项复用。')

    def reject_region(self):
        require(self.region_id,'请选择已保存角色框')
        old=self.context.dataset.store.read(self.region_id)
        self.context.dataset.region(old['candidate_id'],old['roi'],old['form_ref'],region_id=old['id'],expected=self.region_revision,
            actor=self.host.actor.get(),review_status='rejected',quality='reject',is_query=old['is_query'])
        self.new_region();self.refresh_region_list();self.candidate=self.context.dataset.store.read(self.candidate_id)
        self.host.status.set('角色框已排除，历史保留。')

    def generated(self,result):
        self.host.refresh_records();self.host.load_record(result['record']['observation_id']);self.host.tabs.select(self.host.editor_tab)

    def complete_frame(self):
        require(self.candidate_id,'请选择候选画面')
        c=self.candidate
        self.candidate=self.context.dataset.decide(c['position_id'],c['decision'],set_id=c['set_id'],expected=c['revision'],actor=self.host.actor.get(),complete_regions=True)
        self.host.status.set('已记录本版画面的角色完整性；下次改框后需要重新确认。')

    def region_history(self):
        require(self.region_id,'请选择角色框')
        self.host.details('角色框历史（只读）',self.context.dataset.store.history(self.region_id))

    def open_candidate_source(self):
        require(self.candidate_id,'请选择候选画面')
        self.host.show_position(self.candidate['position_id']);self.host.tabs.select(self.host.files_tab)

    def _preparation(self):
        page=self.pages['preparation']
        ttk.Label(page,text='点位派生方向先核对差异；模型训练只读取下面保存的快照。未知镜头分组不会自动分进训练或验证。',wraplength=850).pack(anchor='w',pady=6)
        bar=Toolbar(page);bar.pack(fill='x')
        self.button(bar,'检查当前点位派生方向',self.derive_dialog)
        self.button(bar,'校验资料库',lambda:self.host.run('正在校验…',self.context.library.verify,lambda r:self.host.details('校验结果',r)))
        self.button(bar,'接续旧候选／框／点位资料',self.migrate)
        bar=Toolbar(page);bar.pack(fill='x')
        self.training_task=self.Choice(bar,TASKS,width=17);self.training_task.pack(side='left')
        self.allow_draft=tk.BooleanVar(page,False);self.include_ungrouped=tk.BooleanVar(page,False)
        ttk.Checkbutton(bar,text='允许已审核的草案方向',variable=self.allow_draft).pack(side='left')
        ttk.Checkbutton(bar,text='保留未知分组（不用于训练）',variable=self.include_ungrouped).pack(side='left')
        self.button(bar,'保存训练快照',self.freeze,style='Primary.TButton')
        self.button(bar,'固定同图点位／方向对照',lambda:self.host.run('正在固定对照数据…',self.context.training.freeze_pair,lambda r:(self.refresh_snapshots(),self.host.details('同图同分组对照',r))))
        self.snapshot_empty=ttk.Label(page,text='还没有训练快照。选择任务类型，点击“保存训练快照”开始。',style='Muted.TLabel')
        self.snapshot_empty.pack(fill='x',pady=12)
        self.snapshots=self.host.tree(page,{'time':('保存时间',180),'task':('监督任务',100),'count':('有效记录',85),'excluded':('排除',75),'id':('快照编号',290)},height=12)
        bar=Toolbar(page);bar.pack(fill='x')
        self.button(bar,'刷新',self.refresh_snapshots);self.button(bar,'查看快照／排除原因',self.snapshot_details)
        self.button(bar,'导出模型训练数据',self.materialize);self.button(bar,'使用此快照训练…',self.train)
        bar.pack_configure(side='bottom',before=self.snapshots.master)

    def derive_dialog(self):
        self.host.clean();r=self.host.session.record;require(r,'请先在 M05 选择姿态')
        import math
        from native_workbench import label
        info=proposals(r);win=tk.Toplevel(self.host);win.title('从点位生成方向');win.geometry('690x530')
        ttk.Label(win,text='按已标点位连接方向。旧标注保留在历史版本中；生成后仍可继续修改。',wraplength=650).pack(fill='x',padx=10,pady=8)
        footer=ttk.Frame(win);footer.pack(side='bottom',fill='x',padx=6,pady=5)
        tree=self.host.tree(win,{'name':('方向',220),'old':('原方向',100),'new':('点位生成',100),'state':('变化',140)})
        def angle(value):return '无法生成' if value is None else f'{math.degrees(math.atan2(value[1],value[0])):.0f}°'
        for key,item in info['directions'].items():
            slot,channel=key.split('.')
            absent=r['annotation']['parts'][slot]['presence']=='absent'
            old=r['annotation']['directions'].get(key,{}).get('value')
            tree.insert('','end',values=(label(slot)+' · '+label(channel),angle(old),angle(item['value']),
                '部位不存在，跳过' if absent else '将替换原方向' if key in info['conflicts'] else '新增' if old is None and item['value'] is not None else '无变化'))
        def apply():
            self.host.clean()
            require(self.host.session.record['observation_id']==r['observation_id'],'当前样本已切换，请重新生成方向。')
            args=dict(observation_id=r['observation_id'],revision=r['annotation']['id'],actor=self.host.actor.get(),replace=bool(info['conflicts']))
            self.host.run('正在派生方向…',lambda:self.context.derive(**args),lambda result:(self.host.load_record(result['observation_id']),self.host.status.set('方向已派生，需按实际内容审核。')))
            win.destroy()
        self.button(footer,'生成并替换变化项' if info['conflicts'] else '生成方向',apply)
        self.button(footer,'取消',win.destroy)

    def migrate(self):
        jid=self.context.sources.queue('migration',{},new_id('migration-request'))
        old=self.context.sources.job(jid)
        if old['state']=='done':self.host.details('旧资料迁移记录',old['result'])
        else:self.host.status.set('旧资料接续已排队；重复执行不覆盖新修订，冲突会列入报告。')

    def freeze(self):
        task=self.training_task.key();opts={'allow_draft':self.allow_draft.get(),'include_ungrouped':self.include_ungrouped.get()}
        self.host.run('正在保存训练快照…',lambda:self.context.training.freeze(task,**opts),lambda r:self.refresh_snapshots())

    def refresh_snapshots(self):
        self.snapshots.delete(*self.snapshots.get_children())
        snapshots=self.context.training.snapshots()
        if snapshots:self.snapshot_empty.pack_forget()
        else:self.snapshot_empty.pack(fill='x',pady=12,before=self.snapshots.master)
        for s in reversed(snapshots):
            self.snapshots.insert('','end',iid=s['id'],values=(s['created_at'],TASKS[s['task']],len(s['records']),len(s['excluded']),s['id']))

    def selected_snapshot(self):
        require(self.snapshots.selection(),'请选择一份训练快照')
        return self.snapshots.selection()[0]

    def snapshot_details(self):self.host.details('冻结快照与排除记录',self.context.training.read(self.selected_snapshot()))

    def materialize(self):
        sid=self.selected_snapshot()
        self.host.run('正在导出固定版本训练数据…',lambda:self.context.training.materialize(sid),lambda r:self.host.details('训练数据已导出',r))

    def train(self):
        sid=self.selected_snapshot();win=tk.Toplevel(self.host);win.title('按所选快照训练');win.geometry('570x430')
        box=dialog_form(win)
        choices=self.context.models.runtimes()
        runtime=ttk.Combobox(box,values=choices);runtime.set(choices[0] if choices else '')
        self.host.field(box,'现有 Python 训练环境',runtime)
        values={}
        for key,title,default in [('epochs','训练轮数',20),('image_size','输入尺寸',224),('batch','每批图片',4),('device','设备（cpu 或 0）','cpu')]:
            item=self.host.field(box,title,ttk.Entry(box));item.insert(0,str(default));values[key]=item
        ttk.Label(box,text='训练使用已冻结的审核数据。停止后需重新开始，不将训练图片当验证图片。',wraplength=520).pack(fill='x',pady=8)
        def launch():
            args={k:(v.get() if k=='device' else int(v.get())) for k,v in values.items()};args['runtime']=runtime.get()
            self.host.run('正在准备训练任务…',lambda:self.context.models.queue_train(sid,**args),lambda j:self.host.status.set('训练已排队，可在任务页查看日志或停止。'))
            win.destroy()
        self.button(box,'开始训练',launch)

    def _models(self):
        page=self.pages['models'];bar=Toolbar(page);bar.pack(fill='x')
        self.model_choice=self.Choice(bar,{},width=35);self.model_choice.pack(side='left')
        self.button(bar,'登记已有模型…',self.register_model,style='Primary.TButton')
        self.button(bar,'预测当前姿态',lambda:self.predict(False));self.button(bar,'预测所选候选画面',lambda:self.predict(True))
        self.button(bar,'刷新',self.refresh_models)
        batchbar=Toolbar(page);batchbar.pack(fill='x')
        self.button(batchbar,'批量预测 M05 列表中的姿态',lambda:self.predict(False,True))
        self.button(batchbar,'批量检测未排除候选',lambda:self.predict(True,True))
        ttk.Label(page,text='模型建议先保存在这里。接受、修改或拒绝均留记录；输入已经改变的建议不能直接覆盖新标注。',wraplength=850).pack(anchor='w',pady=6)
        self.model_empty=ttk.Label(page,text='还没有模型建议。先登记已有模型，再选择姿态或候选画面进行预测。',style='Muted.TLabel')
        self.model_empty.pack(fill='x',pady=12)
        self.suggestions=self.host.tree(page,{'target':('目标',260),'kind':('类型',110),'status':('审核',90),'stale':('输入状态',120)})
        bar=Toolbar(page);bar.pack(fill='x')
        self.button(bar,'查看／修改后接受…',self.review_dialog)
        self.button(bar,'接受建议',lambda:self.review('accepted'))
        self.button(bar,'拒绝建议',lambda:self.review('rejected'))
        bar.pack_configure(side='bottom',before=self.suggestions.master)

    def refresh_models(self):
        selected=self.model_choice.key();self.model_choice.set_items({m['id']:Path(m['path']).name+' · '+m['backend'] for m in self.context.models.models()},selected)
        self.suggestions.delete(*self.suggestions.get_children())
        suggestions=self.context.models.suggestions()
        if suggestions:self.model_empty.pack_forget()
        else:self.model_empty.pack(fill='x',pady=12,before=self.suggestions.master)
        for s in suggestions:
            self.suggestions.insert('','end',iid=s['id'],values=(s['target_id'],{'observation':'姿态','candidate':'角色框'}[s['target_kind']],{'pending':'待审核','accepted':'已接受','corrected':'已修正','rejected':'已拒绝','mixed':'部分接受'}[s['status']],'已过期' if s['stale'] else '版本一致'))

    def register_model(self):
        path=filedialog.askopenfilename(parent=self.host,title='选择已有模型权重',filetypes=[('模型','*.pt'),('全部','*.*')])
        if not path:return
        win=tk.Toplevel(self.host);win.title('明确模型能力');box=dialog_form(win)
        backend=self.host.field(box,'模型类型（须与实际训练一致）',self.Choice(box,{'yolo_pose':'21 点 YOLO 姿态','body14_resnet':'body14 ResNet 方向','yolo_detection':'YOLO 角色检测'}))
        form=self.host.field(box,'检测类别 0 对应形态',self.Choice(box,{f['id']:f['label'] for f in self.context.library.catalog.data['forms']}))
        ttk.Label(box,text='点位和方向模板仅用于已有小马模型。多类别检测模型可通过命令行登记完整类别表。',wraplength=440).pack(fill='x',pady=8)
        def save():
            kind=backend.key();kw={'profiles':sorted(PROFILES)} if kind!='yolo_detection' else {'forms':{'0':form.key()}}
            if kind=='yolo_pose':kw['point_order']=ORDER
            if kind=='body14_resnet':kw['directions']=list(LEGACY_MAPPING.values())
            self.context.models.register(path,kind,actor=self.host.actor.get(),**kw);self.refresh_models();win.destroy()
        self.button(box,'按上述能力登记',save)

    def predict(self, candidate, batch=False):
        self.host.clean();mid=self.model_choice.key();require(mid,'请选择模型')
        if candidate:
            require(self.candidate_id,'请在 M02—M04 选择候选画面');kwargs={'candidates':[c['id'] for c in self.context.dataset.candidates() if c['decision']!='excluded'] if batch else [self.candidate_id]}
        else:
            require(self.host.session.record,'请在 M05 选择姿态');kwargs={'observations':list(self.host.records.get_children()) if batch else [self.host.session.record['observation_id']]}
        self.context.models.queue_predict(mid,**kwargs);self.host.status.set('预测已排队；输出将出现在建议列表，标签尚未修改。')

    def selected_suggestion(self):
        require(self.suggestions.selection(),'请选择一份建议')
        return self.context.models.store.read(self.suggestions.selection()[0])

    def review(self, decision, changes=None, suggestion=None):
        self.host.clean();s=suggestion or self.selected_suggestion()
        self.context.models.review(s['id'],s['revision'],decision,actor=self.host.actor.get(),changes=changes)
        self.refresh_models();self.host.refresh_records()
        if s['target_kind']=='observation' and self.host.session.record and self.host.session.record['observation_id']==s['target_id']:
            self.host.load_record(s['target_id'])
        self.refresh_region_list()

    def review_dialog(self):
        s=self.selected_suggestion();win=tk.Toplevel(self.host);win.title('核对模型建议');win.geometry('900x650')
        picture=self.Picture(win);picture.pack(fill='both',expand=True)
        if s['target_kind']=='observation':
            r=self.context.library.read(s['target_id'],s['input_revision']);raw,_=self.context.library.image_bytes(r['image_ref'])
            with Image.open(io.BytesIO(raw)) as im:picture.set_image(im)
            picture.points={k:v['value'] for k,v in s['changes'].get('keypoints',{}).get('points',{}).items() if v.get('value')}
        else:
            c=self.context.dataset.store.read(s['target_id'],s['input_revision'])
            with Image.open(self.context.sources.cached_image(c['position_id'])) as im:picture.set_image(im)
            picture.region=s['changes']['roi']
        if s['target_kind']=='observation' and s['changes'].get('directions'):
            directions=s['changes']['directions']
            choice=self.Choice(win,{k:k for k in directions});choice.pack(fill='x')
            def show_direction(event=None):
                d=directions[choice.key()];w,h=picture.image.size;v=d.get('value')
                picture.lines={choice.key():{'start':[w/2,h/2],'end':[w/2+v[0]*min(w,h)/3,h/2+v[1]*min(w,h)/3]}} if v else {}
                picture.redraw()
            choice.bind('<<ComboboxSelected>>',show_direction);show_direction()
        picture.redraw()
        ttk.Label(win,text='图上显示点位、区域或居中方向示意。可以直接接受；需逐点修改时，载入编辑草稿后在 M05 点选，再逐项审核。',wraplength=850).pack(fill='x')
        bar=Toolbar(win);bar.pack(fill='x')
        def load_draft():
            require(s['target_kind']=='observation','区域建议请在下方修改坐标后接受')
            self.host.load_record(s['target_id']);require(self.host.session.record['annotation']['id']==s['input_revision'],'建议已过期')
            self.host.session.edit(s['changes'],self.host.actor.get())
            self.host.active_suggestion=s
            self.host.annotation_mode.choose('keypoints' if 'keypoints' in s['changes'] else 'directions')
            if 'keypoints' in s['changes']:
                first=next((key for key in ORDER if key in s['changes']['keypoints'].get('points',{})),None)
                if first:self.host.point_key.choose(first)
            else:
                first=next(iter(s['changes'].get('directions',{})),None)
                if first:self.host.direction.choose(first);self.host.update_direction()
            self.host.update_annotation_mode();self.host.tabs.select(self.host.editor_tab);win.destroy()
        self.button(bar,'载入标注草稿修改',load_draft)
        if s['target_kind']=='candidate':
            entry=ttk.Entry(bar,width=28);entry.insert(0,','.join(map(str,s['changes']['roi'])));entry.pack(side='left')
            def corrected():
                changes={**s['changes'],'roi':[int(v.strip()) for v in entry.get().split(',')]}
                self.review('corrected',changes,s);win.destroy()
            self.button(bar,'修改坐标后接受',corrected)
        self.button(bar,'接受',lambda:(self.review('accepted',suggestion=s),win.destroy()))
        self.button(bar,'拒绝',lambda:(self.review('rejected',suggestion=s),win.destroy()))

    def _tasks(self):
        page=self.pages['tasks'];bar=Toolbar(page);bar.pack(fill='x')
        self.button(bar,'上页',lambda:self.page_tasks(-1));self.button(bar,'下页',lambda:self.page_tasks(1))
        self.button(bar,'刷新任务',self.refresh_tasks);self.button(bar,'暂停队列／继续',self.host.pause_sources)
        self.button(bar,'重试失败任务',self.retry);self.button(bar,'取消排队／停止模型任务',self.cancel)
        self.button(bar,'查看日志与输出',self.task_details)
        ttk.Label(page,text='素材读取、裁剪、资料迁移、预测和训练共用此队列。暂停控制素材处理和后续任务；训练停止后需重新开始。',wraplength=850).pack(anchor='w',pady=7)
        self.tasks=self.host.tree(page,{'kind':('任务',120),'state':('状态',110),'progress':('进度',90),'detail':('目标与错误',520)},height=15)

    def refresh_tasks(self):
        selected=self.tasks.selection();self.tasks.delete(*self.tasks.get_children())
        for job in self.context.sources.status(limit=50,offset=self.task_offset)['jobs']:
            progress=f"{job['done']}/{job['total']}" if job['total'] else ''
            p=self.context.library.root/'jobs'/job['id']/'progress.json'
            if p.exists():
                data=load_json(p);progress=f"{data.get('epoch',0)}/{data.get('epochs',0)}轮"
            self.tasks.insert('','end',iid=job['id'],values=({'scan':'扫描目录','probe':'读取素材','position':'读取画面','sample':'生成样本','sample_frames':'批量选帧','train':'训练模型','predict':'模型预测','migration':'接续旧资料','rebind':'重绑目录','proxy':'预览片段'}.get(job['kind'],job['kind']),{'queued':'排队中','running':'处理中','done':'已完成','failed':'失败','cancelled':'已取消'}.get(job['state'],job['state']),progress,job['error'] or job['label']))
        if selected and self.tasks.exists(selected[0]):self.tasks.selection_set(selected[0])

    def page_tasks(self, delta):
        count=sum(self.context.sources.status()['states'].values())
        self.task_offset=min(max(0,(count-1)//50*50),max(0,self.task_offset+50*delta));self.refresh_tasks()

    def task_id(self):
        require(self.tasks.selection(),'请选择任务');return self.tasks.selection()[0]

    def retry(self):self.context.sources.retry(self.task_id());self.refresh_tasks()
    def cancel(self):self.context.sources.cancel(self.task_id());self.refresh_tasks()
    def task_details(self):
        jid=self.task_id();job=self.context.sources.job(jid);log=self.context.library.root/'jobs'/jid/'worker.log'
        self.host.details('任务记录',json.dumps(job,ensure_ascii=False,indent=2)+ ('\n\n'+log.read_text(encoding='utf-8')[-18000:] if log.exists() else ''))
