import marshal, struct, zlib, pathlib, dis, types
root = pathlib.Path(__file__).parent
pyz = (root/'recovered-v2.9/PYZ.pyz').read_bytes()
toc = dict(marshal.loads(pyz[struct.unpack('!i',pyz[8:12])[0]:]))
out = root/'bytecode-review'
out.mkdir(exist_ok=True)
print('\n'.join(name for name in toc if any(k in name for k in ('floor', 'reprice', 'night', 'quote_fields','price_history','daily_reset'))))
for name, (_,pos,length) in toc.items():
    if any(k in name for k in ('floor','reprice','quote_fields','daily_reset','night_editor')):
        co = marshal.loads(zlib.decompress(pyz[pos:pos+length]))
        with (out/(name+'.dis.txt')).open('w',encoding='utf-8') as f:
            print('FILE',co.co_filename,file=f)
            dis.dis(co,file=f)
        (out/(name+'.marshal')).write_bytes(marshal.dumps(co))
co = marshal.loads((root/'recovered-v2.9/portable_reprice').read_bytes())
with (out/'portable_reprice.dis.txt').open('w',encoding='utf-8') as f:
    dis.dis(co,file=f)
