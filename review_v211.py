import dis, marshal, types
from module_runtime import original_code, ROOT
out=ROOT/'review'
out.mkdir(exist_ok=True)
def walk(co):
    for c in co.co_consts:
        if isinstance(c,types.CodeType):
            name=c.co_qualname.replace('<','_').replace('>','_')
            (out/(name+'.txt')).write_text(str(c.co_varnames)+'\n'+dis.Bytecode(c).dis(),encoding='utf8')
            walk(c)
for co in [original_code('charter_quotes.async_probe'),original_code('charter_quotes.saz_provider'),marshal.loads((ROOT/'recovered-v2.9/portable_reprice').read_bytes())]:
    walk(co)
