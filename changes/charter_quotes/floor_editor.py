"""Separate Shanghai and Hangzhou floor editors, preserving the launcher contract."""
import copy
from . import floor_settings
from .quote_fields import PACKAGES

def build(parent, controls, local):
    import tkinter as tk
    from tkinter import ttk, messagebox
    from hourly_reprice import run_lock
    valid = True
    try:
        saved = floor_settings.load()
        tip = '上海、杭州底价独立保存。首次升级沿用原共用底价；保存后下次启动任务生效。'
    except (ValueError, OSError) as exc:
        saved = floor_settings.defaults()
        valid = False
        tip = str(exc) + '。当前显示默认值，原文件尚未替换；请核对两城后修复保存。'

    ttk.Label(parent, text='按城市设置底价（元／整数）', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w', pady=(12, 4))
    ttk.Label(parent, text='选择城市后编辑、分别保存。杭州4小时/100公里尚无资源映射，设置底价不会启用该套餐。', wraplength=700).pack(anchor='w', pady=4)
    tabs = ttk.Notebook(parent)
    tabs.pack(fill='both', expand=True, pady=8)
    fields = {}
    notice = tk.StringVar(master=parent, value=tip)

    def values(city):
        return {vehicle: [v.get() for v in cells] for vehicle, cells in fields[city].items()}

    def all_values():
        return {city: values(city) for city in floor_settings.CITIES}

    def ready():
        try:
            return valid and floor_settings.validate(all_values()) == saved and floor_settings.load() == saved
        except (ValueError, OSError):
            return False

    def persist(city):
        nonlocal saved, valid
        try:
            if not valid:
                raise ValueError('原文件无效，请先核对两城，再点击“修复并保存两城底价”')
            with run_lock(local):
                saved = floor_settings.save_city(city, values(city))
            notice.set(f'{city}底价已保存，另一城市未修改。下次任务使用新底价；保存本身不会修改携程价格。')
        except (ValueError, OSError, RuntimeError) as exc:
            messagebox.showerror('底价未保存', str(exc), parent=parent)

    def reset(city):
        for vehicle, prices in floor_settings.DEFAULT_FLOORS.items():
            for variable, price in zip(fields[city][vehicle], prices):
                variable.set(str(price))
        notice.set(f'已填入{city}原始默认底价，尚未保存；另一城市未修改。')

    for city in floor_settings.CITIES:
        page = ttk.Frame(tabs, padding=6)
        tabs.add(page, text=city + '底价')
        actions = ttk.Frame(page)
        actions.pack(side='bottom', fill='x', pady=(8,0))
        viewport = ttk.Frame(page)
        viewport.pack(fill='both', expand=True)
        viewport.columnconfigure(0,weight=1)
        viewport.rowconfigure(0,weight=1)
        canvas = tk.Canvas(viewport,highlightthickness=0,background='#f3f6fa')
        vertical = ttk.Scrollbar(viewport,orient='vertical',command=canvas.yview)
        horizontal = ttk.Scrollbar(viewport,orient='horizontal',command=canvas.xview)
        canvas.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        canvas.grid(row=0,column=0,sticky='nsew')
        vertical.grid(row=0,column=1,sticky='ns')
        horizontal.grid(row=1,column=0,sticky='ew')
        frame = ttk.Frame(canvas,padding=4)
        window = canvas.create_window(0,0,window=frame,anchor='nw')
        frame.bind('<Configure>',lambda event,c=canvas:c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>',lambda event,c=canvas,w=window:c.itemconfigure(w,width=max(980,event.width)))
        fields[city] = {}
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text='车型').grid(row=0, column=0, padx=5, pady=4)
        for col, (h, km) in enumerate(PACKAGES, 1):
            frame.columnconfigure(col, weight=1)
            ttk.Label(frame, text=f'{h}小时/{km}公里').grid(row=0, column=col, padx=4)
        for row, (vehicle, prices) in enumerate(saved[city].items(), 1):
            ttk.Label(frame, text=vehicle).grid(row=row, column=0, sticky='w', padx=5, pady=3)
            fields[city][vehicle] = []
            for col, price in enumerate(prices, 1):
                variable = tk.StringVar(master=parent, value=str(price))
                fields[city][vehicle].append(variable)
                entry = ttk.Entry(frame, textvariable=variable, width=9, justify='right', font=('Microsoft YaHei UI', 16, 'bold'))
                entry.grid(row=row, column=col, padx=5, pady=3, sticky='ew')
                controls.append(entry)
        for col, (label, command) in enumerate(((f'保存{city}底价', lambda c=city: persist(c)), (f'填入{city}原底价', lambda c=city: reset(c)))):
            button = ttk.Button(actions, text=label, command=command)
            button.pack(side='left',padx=(4,16),pady=4)
            controls.append(button)

    if not valid:
        def repair():
            nonlocal saved, valid
            try:
                with run_lock(local):
                    saved = floor_settings.save(all_values())
                valid = True
                repair_button.configure(state='disabled')
                notice.set('已修复并保存两城底价，原文件已备份。保存本身不会修改携程价格。')
            except (ValueError, OSError, RuntimeError) as exc:
                messagebox.showerror('底价未保存', str(exc), parent=parent)
        repair_button = ttk.Button(parent, text='修复并保存两城底价', command=repair)
        repair_button.pack(anchor='w', pady=4)
        controls.append(repair_button)
    ttk.Label(parent, textvariable=notice, wraplength=700).pack(anchor='w', pady=8)
    # Local test handles: no network or VBK operations are invoked by this editor.
    parent.floor_editor_state = dict(fields=fields, tabs=tabs, save=persist, reset=reset, ready=ready)
    return ready
