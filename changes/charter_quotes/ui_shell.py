"""Desktop UI, separated from task execution and price-setting rules."""
import codecs
import json
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from .core import SHANGHAI
from .floor_editor import build as build_floors
from .night_mode import NightCycle, config, configure, CITIES, city_local, migrate_cities
from .release_info import newer_release, register_release
from hourly_reprice import run_lock

BG='#f3f6fa'
INK='#192b3d'
MUTED='#61758a'
TEAL='#087f79'

class LogTail:
    """Read bounded byte increments; keep UTF-8 characters across chunk boundaries."""
    def __init__(self, path):
        self.path=Path(path)
        self.reset()
    def reset(self):
        self.offset=0
        self.decoder=codecs.getincrementaldecoder('utf8')(errors='replace')
    def read(self, limit=65536):
        try:
            if self.path.stat().st_size < self.offset: self.reset()
            with self.path.open('rb') as stream:
                stream.seek(self.offset)
                raw=stream.read(limit)
                self.offset=stream.tell()
            return self.decoder.decode(raw)
        except FileNotFoundError:
            return ''

def configure_style(root):
    root.configure(bg=BG)
    s=ttk.Style(root)
    s.theme_use('clam')
    s.configure('.',font=('Microsoft YaHei UI',14),foreground=INK,background=BG)
    s.configure('TFrame',background=BG)
    s.configure('Card.TFrame',background='white')
    s.configure('TLabel',background=BG,foreground=INK)
    s.configure('Card.TLabel',background='white')
    s.configure('Muted.TLabel',foreground=MUTED,background='white')
    s.configure('Heading.TLabel',font=('Microsoft YaHei UI',24,'bold'))
    s.configure('CardHeading.TLabel',background='white',font=('Microsoft YaHei UI',16,'bold'))
    s.configure('Metric.TLabel',background='white',font=('Microsoft YaHei UI',20,'bold'),foreground=TEAL)
    s.configure('TButton',padding=(14,9),background='#e8eef4',borderwidth=0)
    s.map('TButton',background=[('active','#dce6f0'),('disabled','#edf0f4')],foreground=[('disabled','#9aa8b6')])
    s.configure('Primary.TButton',background=TEAL,foreground='white')
    s.map('Primary.TButton',background=[('active','#066b66'),('disabled','#b2cbc9')],foreground=[('disabled','#f6fafa')])
    s.configure('Stop.TButton',background='#fbe9e7',foreground='#a23b32')
    s.configure('Warm.TButton',background='#fff0d8',foreground='#835417')
    s.configure('TCheckbutton',padding=6,background='white')
    s.map('TCheckbutton',background=[('active','#f0f6f6')])
    s.configure('TEntry',fieldbackground='white',padding=6,font=('Microsoft YaHei UI',14))
    s.configure('TNotebook',background=BG,borderwidth=0)
    s.configure('TNotebook.Tab',padding=(22,9),background='#e5edf3')
    s.map('TNotebook.Tab',background=[('selected','white')],foreground=[('selected',TEAL)])
    s.layout('Navigation.TNotebook.Tab',[])
    s.configure('TProgressbar',background=TEAL,troughcolor='#e3edf0',borderwidth=0)

class Application:
    def __init__(self, context, root=None):
        self.g=context
        if root is None and os.name=='nt':
            import ctypes
            try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except (AttributeError,OSError):pass
        self.root=root or tk.Tk()
        # Keep controls within the window on Windows displays with 125–200% scaling.
        self.root.tk.call('tk','scaling',4/3)
        self.root.title('夏末初秋 · 自动改价工作台 V'+context['VERSION'])
        logo=Path(context.get('BASE',Path(__file__).parent))/'assets/logo.png'
        if logo.is_file():
            self.root._brand_icon=tk.PhotoImage(master=self.root,file=str(logo))
            self.root.iconphoto(True,self.root._brand_icon)
        width=min(1360,max(960,self.root.winfo_screenwidth()-100))
        height=min(940,max(700,self.root.winfo_screenheight()-100))
        self.root.geometry(f'{width}x{height}')
        self.root.minsize(960,700)
        configure_style(self.root)
        self.local=context['LOCAL']
        self.proc=self.stream=self.current_mode=None
        self.buttons=[]
        self.status=tk.StringVar(self.root,value='准备就绪。先检查会话，再预览行情。')
        self.runtime=tk.StringVar(self.root,value='空闲')
        self.query_date=tk.StringVar(self.root)
        self.session_status=tk.StringVar(self.root)
        self.release_status=tk.StringVar(self.root,value='当前 V'+context['VERSION'])
        self.release=None
        self.release_checked=0
        if getattr(sys,'frozen',False):
            try:register_release(context['VERSION'],sys.executable)
            except OSError:pass
        self.selected_label=tk.StringVar(self.root,value='上海 + 杭州')
        self.autoscroll=tk.BooleanVar(self.root,value=True)
        self.city_vars={c:tk.BooleanVar(self.root,value=True) for c in CITIES}
        for v in self.city_vars.values(): v.trace_add('write',lambda *_: self.update_selection())
        self.tail=LogTail(context['LOG'])
        self._poll_id=None
        self._last_day=None
        self._running=False
        self.night_cycles={}
        self.night_enabled={}
        self.night_status={}
        with run_lock(self.local): migrate_cities(self.local)
        for city in CITIES:
            self.night_cycles[city]=NightCycle(city_local(self.local,city))
            self.night_enabled[city]=tk.BooleanVar(self.root,value=config(city_local(self.local,city))['enabled'])
            self.night_status[city]=tk.StringVar(self.root,value=self.night_cycles[city].description())
        self.build()
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.app_controller=self
        self.update_header()

    def card(self,parent,title=None,**pack):
        frame=ttk.Frame(parent,style='Card.TFrame',padding=16)
        frame.pack(fill='x',pady=(0,12),**pack)
        if title: ttk.Label(frame,text=title,style='CardHeading.TLabel').pack(anchor='w',pady=(0,10))
        return frame

    def button(self,parent,text,command,style='TButton',lock=True,**pack):
        b=ttk.Button(parent,text=text,command=command,style=style)
        b.pack(side='left',padx=(0,8),**pack)
        if lock:self.buttons.append(b)
        return b

    def build(self):
        sidebar=tk.Frame(self.root,bg='#132f40',width=210)
        sidebar.pack(side='left',fill='y')
        sidebar.pack_propagate(False)
        tk.Label(sidebar,text='夏末初秋',font=('Microsoft YaHei UI',21,'bold'),fg='white',bg='#132f40').pack(anchor='w',padx=20,pady=(28,3))
        tk.Label(sidebar,text='小时包车 · 改价工作台',fg='#b1c5d0',bg='#132f40',font=('Microsoft YaHei UI',12)).pack(anchor='w',padx=20,pady=(0,28))
        body=ttk.Frame(self.root,padding=(20,18))
        body.pack(side='left',fill='both',expand=True)
        self.book=ttk.Notebook(body,style='Navigation.TNotebook')
        self.book.pack(fill='both',expand=True)
        self.pages={}
        self.nav={}
        for label in ('运行工作台','城市底价','夜间模式','规则说明'):
            page=ttk.Frame(self.book)
            self.book.add(page,text=label)
            self.pages[label]=page
            button=tk.Button(sidebar,text=label,font=('Microsoft YaHei UI',14),anchor='w',padx=18,pady=12,bg='#132f40',fg='#d8e5ed',activebackground='#205365',activeforeground='white',relief='flat',borderwidth=0,command=lambda n=label:self.select_page(n))
            button.pack(fill='x',padx=10,pady=3)
            self.nav[label]=button
        version_box=tk.Frame(sidebar,bg='#132f40')
        version_box.pack(side='bottom',fill='x',padx=16,pady=18)
        tk.Label(version_box,textvariable=self.release_status,justify='left',wraplength=176,fg='#c5d9e4',bg='#132f40',font=('Microsoft YaHei UI',12)).pack(anchor='w')
        self.release_button=ttk.Button(version_box,text='打开新版位置',command=self.open_release)
        tk.Label(version_box,text='上海 / 杭州 · 9座及以下',fg='#9db6c4',bg='#132f40',font=('Microsoft YaHei UI',10)).pack(anchor='w',pady=(8,0))
        footer=ttk.Frame(body)
        footer.pack(fill='x',pady=(8,0))
        ttk.Label(footer,textvariable=self.status,wraplength=1000,font=('Microsoft YaHei UI',12),foreground=MUTED).pack(anchor='w')
        self.build_dashboard(self.pages['运行工作台'])
        floor=self.pages['城市底价']
        self.page_heading(floor,'城市底价','按城市保存，任务启动后固定使用本次底价快照。')
        self.floors_ready=build_floors(floor,self.buttons,self.local)
        self.build_night(self.pages['夜间模式'])
        self.build_rules(self.pages['规则说明'])
        self.select_page('运行工作台')

    def page_heading(self,parent,title,subtitle):
        ttk.Label(parent,text=title,style='Heading.TLabel').pack(anchor='w')
        ttk.Label(parent,text=subtitle,foreground=MUTED,wraplength=870).pack(anchor='w',pady=(4,16))

    def build_dashboard(self,parent):
        self.page_heading(parent,'运行工作台','次日行情查询、基础改价和运行日志集中在这里。')
        metrics=ttk.Frame(parent)
        metrics.pack(fill='x',pady=(0,12))
        for index,(label,var) in enumerate((('查询日期 · 北京时间',self.query_date),('运行范围',self.selected_label),('任务状态',self.runtime))):
            metrics.columnconfigure(index,weight=1)
            frame=ttk.Frame(metrics,style='Card.TFrame',padding=14)
            frame.grid(row=0,column=index,sticky='nsew',padx=(0,10 if index<2 else 0))
            ttk.Label(frame,text=label,style='Muted.TLabel').pack(anchor='w')
            ttk.Label(frame,textvariable=var,style='Metric.TLabel').pack(anchor='w',pady=(6,0))
        setup=self.card(parent,'连接与运行范围')
        row=ttk.Frame(setup,style='Card.TFrame');row.pack(fill='x')
        self.button(row,'获取查价会话',lambda:self.start('capture'))
        self.button(row,'游客端登录',lambda:self.start('login'))
        self.button(row,'VBK 后台登录',lambda:self.start('night-login'))
        self.button(row,'导入 SAZ',self.import_saz)
        ttk.Label(row,textvariable=self.session_status,style='Muted.TLabel').pack(side='right')
        row=ttk.Frame(setup,style='Card.TFrame');row.pack(fill='x',pady=(12,0))
        for city in CITIES:
            check=ttk.Checkbutton(row,text=city,variable=self.city_vars[city]);check.pack(side='left',padx=(0,8));self.buttons.append(check)
        for label,city in (('只跑上海','上海'),('只跑杭州','杭州'),('两城都跑',None)):
            self.button(row,label,lambda c=city:self.select_city(c))
        actions=self.card(parent,'执行任务')
        row=ttk.Frame(actions,style='Card.TFrame');row.pack(fill='x')
        self.button(row,'预览行情',lambda:self.start('preview'))
        self.button(row,'按规则改价一次',lambda:self.start('once'))
        self.button(row,'启动 1 小时循环',lambda:self.start('apply'),'Primary.TButton')
        self.button(row,'停止任务',self.stop,'Stop.TButton',lock=False)
        row=ttk.Frame(actions,style='Card.TFrame');row.pack(fill='x',pady=(10,0))
        self.button(row,'手动抬价后重新查价',lambda:self.start('reset'),'Warm.TButton')
        ttk.Label(row,text='独立执行一次；小时循环不会自动抬价。',style='Muted.TLabel').pack(side='left')
        self.progress=ttk.Progressbar(actions,mode='indeterminate')
        self.progress.pack(fill='x',pady=(12,0))
        logcard=ttk.Frame(parent,style='Card.TFrame',padding=12)
        logcard.pack(fill='both',expand=True)
        toolbar=ttk.Frame(logcard,style='Card.TFrame');toolbar.pack(fill='x',pady=(0,8))
        ttk.Label(toolbar,text='运行日志',style='CardHeading.TLabel').pack(side='left')
        ttk.Checkbutton(toolbar,text='自动滚动',variable=self.autoscroll).pack(side='right')
        ttk.Button(toolbar,text='清空显示',command=self.clear_log).pack(side='right',padx=8)
        self.text=ScrolledText(logcard,height=6,wrap='word',bg='#112b3a',fg='#dce8f0',insertbackground='white',relief='flat',borderwidth=0,padx=12,pady=10,font=('Microsoft YaHei UI',13),state='disabled')
        self.text.pack(fill='both',expand=True)
        self.text.tag_configure('error',foreground='#ffb1a7')
        self.text.tag_configure('success',foreground='#87dcc5')

    def build_night(self,parent):
        self.page_heading(parent,'夜间模式','上海、杭州分别开关；仅暂停对应城市的基础改价。')
        for city in CITIES:
            frame=self.card(parent,city+'夜间溢价')
            ttk.Label(frame,text='23:00 设置次日系数 2.0 / 固定加价 0 元，07:00 恢复原规则。',style='Muted.TLabel').pack(anchor='w',pady=(0,10))
            row=ttk.Frame(frame,style='Card.TFrame');row.pack(fill='x')
            ttk.Checkbutton(row,text='开启'+city+'夜间模式',variable=self.night_enabled[city],command=lambda c=city:self.toggle_night(c)).pack(side='left')
            ttk.Button(row,text='重试'+city,command=lambda c=city:self.toggle_night(c)).pack(side='left',padx=12)
            ttk.Label(frame,textvariable=self.night_status[city],style='Muted.TLabel',wraplength=830).pack(anchor='w',pady=(10,0))
        row=ttk.Frame(parent);row.pack(fill='x',pady=8)
        self.button(row,'检查 VBK 登录',lambda:self.start('night-login'))
        ttk.Label(parent,text='关闭城市开关后恢复该城市原日期规则。请保持软件运行、电脑不休眠、VBK 登录有效。',foreground=MUTED,wraplength=850).pack(anchor='w',pady=12)

    def build_rules(self,parent):
        self.page_heading(parent,'执行规则','基础改价、手动抬价、夜间溢价分别运行。')
        for title,body in (
            ('目标基础套餐费','max（外网价 × 0.83 − 1 四舍五入取整数，该城市底价）。修改基础套餐费可能影响多个用车日期。'),
            ('城市判断','上海：核实为夏末初秋则跳过，服务商无法核实时也跳过。杭州：换算参考价与上轮成功保存价一致且后台核对一致时跳过，同价不代表供应商身份已确认。'),
            ('查询与保存','报价请求复用连接、同请求合并，最多两路协程。服务商仍逐条生成未提交记录再核实，最多两路。后台改价逐条保存、回读核验。'),
            ('抬价与恢复','手动抬价先备份原价，设置 max（2000 元，该城市底价），全部完成后重新查询。无有效行情等异常按原规则恢复。小时循环不会自动抬价。'),
            ('夜间与退出','23:00 设置次日日期溢价，07:00 恢复原规则。存在待恢复记录时先恢复。运行期间关闭窗口会先请求停止，不能中断保存核验。'),
        ):
            card=self.card(parent,title)
            ttk.Label(card,text=body,style='Muted.TLabel',wraplength=830).pack(anchor='w')

    def select_page(self,name):
        self.book.select(self.pages[name])
        for key,button in self.nav.items():button.configure(bg='#205365' if key==name else '#132f40',fg='white' if key==name else '#d8e5ed')

    def select_city(self,city):
        for name,var in self.city_vars.items():var.set(city is None or city==name)

    def update_selection(self):
        self.selected_label.set(' + '.join(c for c,v in self.city_vars.items() if v.get()) or '未选择城市')

    def update_header(self):
        now=datetime.now(SHANGHAI)
        self.query_date.set((now.date()+timedelta(days=1)).isoformat())
        self.session_status.set('已有本机会话 · 待查询验证' if self.g['SESSION'].exists() else '尚未获取会话')
        if time.monotonic()-self.release_checked>=5:
            self.release_checked=time.monotonic()
            self.release=newer_release(self.g['VERSION'])
            if self.release:
                self.release_status.set('当前 V'+self.g['VERSION']+'\n发现本机新版 V'+self.release['version'])
                self.release_button.pack(anchor='w',pady=(8,0))
            else:
                self.release_status.set('当前 V'+self.g['VERSION']+'\n本机未发现更高版本')
                self.release_button.pack_forget()

    def open_release(self):
        release=newer_release(self.g['VERSION'])
        if release:os.startfile(str(Path(release['executable']).parent))

    def start(self,mode):
        if self.proc and self.proc.poll() is None:return
        pending=False
        pending_path=self.local/'data/auto_reprice/daily-reset-state.json'
        if mode in ('apply','once','reset') and pending_path.exists():
            try:pending=json.loads(pending_path.read_text(encoding='utf8')).get('status')=='pending'
            except Exception:
                messagebox.showerror('恢复记录异常','请保留恢复记录并检查，勿继续重置。',parent=self.root);return
        if mode not in ('capture','login','night','night-login') and not pending:
            if not self.g['SESSION'].exists():
                messagebox.showinfo('先获取查价会话','请先获取查价会话，或导入有效 SAZ。',parent=self.root);return
            if not self.floors_ready():
                self.select_page('城市底价')
                messagebox.showinfo('请先保存底价','存在未保存或已变化的底价，请核对两城并保存。',parent=self.root);return
        selected=[c for c in CITIES if self.city_vars[c].get()]
        if mode in ('preview','apply','once','reset') and not selected:
            messagebox.showinfo('请选择城市','请选择上海、杭州或两城。',parent=self.root);return
        self.g['STOP'].unlink(missing_ok=True)
        args=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(self.g['__file__']).resolve())]
        args+=['--job',mode]
        for city in selected:args+=['--city',city]
        stream=None
        try:
            stream=self.g['LOG'].open('w',encoding='utf8')
            proc=subprocess.Popen(args,stdout=stream,stderr=stream,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except OSError as exc:
            if stream:stream.close()
            messagebox.showerror('启动失败',str(exc),parent=self.root);return
        self.stream,self.proc,self.current_mode=stream,proc,mode
        self.tail.reset()
        self.clear_log()
        for b in self.buttons:b.configure(state='disabled')
        names={'apply':'小时循环','once':'单轮改价','reset':'手动抬价','preview':'预览行情','night':'夜间任务','capture':'捕获会话','login':'游客端登录','night-login':'VBK 登录'}
        self.runtime.set(names.get(mode,'运行中'))
        self.progress.start(14)
        self.status.set('启动中。实际改价模式登录 VBK 后会自动开始，请保留浏览器窗口。' if mode in ('apply','once','reset') else '正在处理，请查看运行日志。')

    def import_saz(self):
        from .saz_provider import load_saz
        filename=filedialog.askopenfilename(parent=self.root,filetypes=[('SAZ文件','*.saz')])
        if not filename:return
        try:
            load_saz(filename)
            if Path(filename).resolve()!=self.g['SESSION'].resolve():shutil.copyfile(filename,self.g['SESSION'])
            self.status.set('SAZ 已导入；请预览查询验证会话是否有效。')
            self.update_header()
        except Exception:
            messagebox.showerror('导入失败','未找到可用包车查询请求，请重新捕获。',parent=self.root)

    def toggle_night(self,city):
        try:configure(city_local(self.local,city),self.night_enabled[city].get())
        except Exception as exc:messagebox.showerror('夜间设置未保存',str(exc),parent=self.root)

    def stop(self):
        if self.current_mode=='night' and self.proc and self.proc.poll() is None:
            for city in CITIES:
                configure(city_local(self.local,city),False)
                self.night_enabled[city].set(False)
        self.g['STOP'].touch()
        self.status.set('已请求停止；等待当前核验及必要恢复完成。请保留浏览器窗口。')

    def clear_log(self):
        self.text.configure(state='normal');self.text.delete('1.0','end');self.text.configure(state='disabled')

    def append_log(self,content):
        if not content:return
        self.text.configure(state='normal')
        for line in content.splitlines(keepends=True):
            tag='error' if any(k in line for k in ('失败','异常','Traceback','Error')) else 'success' if any(k in line for k in ('成功','已保存','核验通过')) else ''
            self.text.insert('end',line,tag)
        lines=int(self.text.index('end-1c').split('.')[0])
        if lines>5000:self.text.delete('1.0',f'{lines-5000}.0')
        self.text.configure(state='disabled')
        if self.autoscroll.get():self.text.see('end')

    def poll(self):
        if not self.root.winfo_exists():return
        try:
            self.append_log(self.tail.read())
            if self.proc and self.proc.poll() is not None:
                code=self.proc.returncode
                if self.current_mode=='night' and code!=0:
                    for city,cycle in self.night_cycles.items():
                        if cycle.due():
                            state=cycle.state()
                            state.update(blocked_revision=config(city_local(self.local,city))['revision'],error='夜间进程未完成，请检查日志及 VBK 登录后重试')
                            cycle.save(state)
                self.status.set('本次操作结束，请查看日志。' if code==0 else '已停止，请查看日志，处理后再启动。')
                if self.stream:self.stream.close()
                self.stream=self.proc=None
                self.current_mode=None
                self.runtime.set('空闲' if code==0 else '待处理')
                self.progress.stop()
                for b in self.buttons:b.configure(state='normal')
            for city,cycle in self.night_cycles.items():self.night_status[city].set(cycle.description())
            if self.proc is None and any(c.due() for c in self.night_cycles.values()):self.start('night')
            self.update_header()
        except Exception as exc:
            self.status.set('状态更新异常：'+str(exc))
        self._poll_id=self.root.after(500,self.poll)

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.stop();messagebox.showinfo('正在停止','请等操作结束后关闭，避免打断保存核验。',parent=self.root);return
        if any(c.state().get('phase') in ('active','applying','restoring') for c in self.night_cycles.values()):
            messagebox.showinfo('请先恢复夜间溢价','请关闭夜间开关并等待恢复完成后退出。',parent=self.root);return
        if self._poll_id is not None:self.root.after_cancel(self._poll_id)
        self.root.destroy()

def launch(context):
    try:
        app=Application(context)
    except Exception as exc:
        messagebox.showerror('暂时无法启动','请先停止旧版任务，再重试。\n'+str(exc))
        return
    app.poll()
    app.root.mainloop()
