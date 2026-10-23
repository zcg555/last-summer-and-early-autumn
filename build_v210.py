"""Rebuild the supplied PyInstaller archive, preserving untouched payload bytes."""
import hashlib, json, marshal, struct, types, zlib
from pathlib import Path
from module_runtime import ROOT, ARCHIVE, TOC, original_code

destination = ROOT/'dist/夏末初秋-自动改价循环V2.10'
destination.mkdir(parents=True, exist_ok=True)
original = next((ROOT/'input-v2.9').rglob('*.exe')).read_bytes()
magic, pkglen, tocpos, toclen, pyver, pylib = struct.unpack('!8sIIII64s', original[-88:])
start = len(original)-pkglen
position = start+tocpos
entries=[]
while position < start+tocpos+toclen:
    size, offset, length, rawlen, compressed, kind = struct.unpack('!IIIIBc', original[position:position+18])
    name = original[position+18:position+size].rstrip(b'\0').decode('utf8')
    entries.append((name,compressed,kind,rawlen,original[start+offset:start+offset+length]))
    position += size

floor_fn_code = compile((ROOT/'changes/floor_value.py').read_text(encoding='utf8'),'charter_quotes/quote_fields.py','exec')
floor_fn = next(c for c in floor_fn_code.co_consts if isinstance(c,types.CodeType))
pyzdata = bytearray(ARCHIVE[:12])
newtoc=[]
changed=[]
for name,(kind,offset,length) in TOC.items():
    source = ROOT/'changes'/Path(*name.split('.')).with_suffix('.py')
    if source.exists():
        code = compile(source.read_text(encoding='utf8'),name.replace('.','/')+'.py','exec')
        payload = zlib.compress(marshal.dumps(code),6)
        changed.append(name)
    elif name == 'charter_quotes.quote_fields':
        code = original_code(name)
        code = code.replace(co_consts=tuple(floor_fn if isinstance(c,types.CodeType) and c.co_name=='floor_value' else c for c in code.co_consts))
        payload = zlib.compress(marshal.dumps(code),6)
        changed.append(name)
    else:
        payload = ARCHIVE[offset:offset+length]
    newtoc.append((name,(kind,len(pyzdata),len(payload))))
    pyzdata.extend(payload)
newtocpos = len(pyzdata)
pyzdata.extend(marshal.dumps(newtoc))
pyzdata[8:12] = struct.pack('!i',newtocpos)

entrycode = marshal.loads((ROOT/'recovered-v2.9/portable_reprice').read_bytes())
original_test = next(c for c in entrycode.co_consts if isinstance(c,types.CodeType) and c.co_name=='self_test')
selftest_source = '''
def self_test(path):
    import types, marshal, tempfile, copy
    import tkinter as tk
    from tkinter import ttk
    from charter_quotes import floor_settings as fs
    from charter_quotes.floor_editor import build
    from charter_quotes.quote_fields import floor_value, FLOORS
    from hourly_reprice import resources_today
    original_test = types.FunctionType(marshal.loads(ORIGINAL_TEST_BYTES), globals())
    original_test(path)
    previous = os.environ.get('LOCALAPPDATA')
    active = fs._active
    with tempfile.TemporaryDirectory(prefix='xm-cities-') as td:
        os.environ['LOCALAPPDATA'] = td
        fs._active = None
        root = tk.Tk()
        root.withdraw()
        try:
            local = Path(td)/'XiaMoChuQiuCharter'
            local.mkdir()
            frame = ttk.Frame(root)
            controls = []
            ready = build(frame, controls, local)
            s = frame.floor_editor_state
            assert len(s['tabs'].tabs()) == 2 and ready()
            s['fields']['上海']['经济5座'][0].set('900')
            assert not ready()
            s['save']('上海')
            s['tabs'].select(1)
            s['fields']['杭州']['经济5座'][0].set('700')
            s['save']('杭州')
            assert ready()
            fs.activate(fs.load())
            items = resources_today(list(FLOORS))
            assert len(items) == 90
            for city, expected in [('上海',900),('杭州',700)]:
                assert floor_value(dict(city=city,vehicle_name='经济5座',hours=4,kilometers=50)) == expected
                assert next(r for r in items if r['city']==city and r['vehicle_name']=='经济5座' and r['hours']==4 and r['kilometers']==50)['floor_price']==expected
            result = json.loads(Path(path).read_text(encoding='utf8'))
            result.update(city_floor_ui=True, city_floor_save_reload=True, city_floor_resource_count=len(items), city_floor_isolation=True)
            Path(path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        finally:
            root.destroy()
            fs._active = active
            if previous is None: os.environ.pop('LOCALAPPDATA',None)
            else: os.environ['LOCALAPPDATA'] = previous
'''.replace('ORIGINAL_TEST_BYTES',repr(marshal.dumps(original_test)))
newtest = next(c for c in compile(selftest_source,'portable_self_test_v210.py','exec').co_consts if isinstance(c,types.CodeType))
def update_constants(co):
    values=[]
    for c in co.co_consts:
        if isinstance(c,types.CodeType):
            c = newtest if c.co_name=='self_test' else update_constants(c)
        elif isinstance(c,str):
            c = c.replace('V2.9','V2.10')
            if c == '2.9': c = '2.10'
        values.append(c)
    return co.replace(co_consts=tuple(values))
entrycode=update_constants(entrycode)

data = bytearray()
toc = bytearray()
for name, compressed, kind, rawlen, payload in entries:
    if name == 'PYZ.pyz':
        raw = bytes(pyzdata)
        rawlen = len(raw)
        payload = zlib.compress(raw,9) if compressed else raw
    elif name == 'portable_reprice':
        raw = marshal.dumps(entrycode)
        rawlen = len(raw)
        payload = zlib.compress(raw,9) if compressed else raw
    encoded = name.encode('utf8')+b'\0'
    size = (18+len(encoded)+15)//16*16
    toc.extend(struct.pack('!IIIIBc',size,len(data),len(payload),rawlen,compressed,kind))
    toc.extend(encoded.ljust(size-18,b'\0'))
    data.extend(payload)
tocpos = len(data)
data.extend(toc)
data.extend(struct.pack('!8sIIII64s',magic,len(data)+88,tocpos,len(toc),pyver,pylib))
output=destination/'夏末初秋-自动改价循环V2.10.exe'
output.write_bytes(original[:start]+data)
manifest = dict(version='2.10', original_sha256=hashlib.sha256(original).hexdigest(), exe_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),changed_modules=changed+['portable_reprice'],preserved_pyz_modules=len(TOC)-len(changed),preserved_other_archive_entries=len(entries)-2)
(destination/'build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
print(json.dumps(manifest,indent=2))
print(str(output))
