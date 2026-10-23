import os, subprocess, tempfile
from pathlib import Path
from module_runtime import ROOT, install
install()
from charter_quotes.ui_shell import Application
from tests_v211 import Desktop
os.environ['TCL_LIBRARY']=str(ROOT/'recovered-v2.9/_tcl_data')
os.environ['TK_LIBRARY']=str(ROOT/'recovered-v2.9/_tk_data')
out=ROOT/'ui-preview'
out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=ROOT/'test-data') as td:
    os.environ['LOCALAPPDATA']=td
    local=Path(td)/'XiaMoChuQiuCharter';local.mkdir()
    g=dict(VERSION='2.12',LOCAL=local,SESSION=local/'portable-query.saz',STOP=local/'portable-reprice.stop',LOG=local/'portable-reprice.log',__file__=str(ROOT/'portable_reprice.py'))
    app=Application(g)
    app.root.attributes('-topmost',True)
    app.root.geometry('1360x940+20+20')
    try:
        for name,filename in [('运行工作台','dashboard'),('城市底价','floors'),('夜间模式','night')]:
            app.select_page(name)
            app.root.update()
            x,y=app.root.winfo_rootx(),app.root.winfo_rooty()
            w,h=app.root.winfo_width(),app.root.winfo_height()
            command=f"Add-Type -AssemblyName System.Drawing; $b=[Drawing.Bitmap]::new({w},{h}); $g=[Drawing.Graphics]::FromImage($b); $g.CopyFromScreen({x},{y},0,0,$b.Size); $b.Save('{out/filename}.png'); $g.Dispose(); $b.Dispose()"
            subprocess.run(['powershell.exe','-NoProfile','-Command',command],check=True)
        print('UI previews saved')
    finally:app.root.destroy()

