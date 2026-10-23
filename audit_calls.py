from module_runtime import *
import types
def walk(co):
    yield co
    for c in co.co_consts:
        if isinstance(c,types.CodeType): yield from walk(c)
for name in TOC:
    if name.startswith('charter_quotes.') or name in ('hourly_reprice',):
        for co in walk(original_code(name)):
            if any(n in co.co_names for n in ('floor_settings','FLOORS','floor_value')):
                print(name, co.co_qualname, 'args=',co.co_varnames[:co.co_argcount], 'names=',co.co_names)
install()
import charter_quotes.auto_reprice as a
import hourly_reprice as h
import inspect
for m in (a,h):
    for n,v in vars(m).items():
        if inspect.isfunction(v) and v.__module__ == m.__name__:
            print(m.__name__,n,inspect.signature(v))
