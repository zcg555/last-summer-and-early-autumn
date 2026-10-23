"""Build/runtime patch definitions shared by tests and the EXE packager."""
import types
from pathlib import Path
ROOT=Path(__file__).parent

def patch_hourly(code):
    functions={}
    for filename in ('collect.py','vbk_methods.py'):
        module=compile((ROOT/'changes'/filename).read_text(encoding='utf8'),filename,'exec')
        functions.update({c.co_name:c for c in module.co_consts if isinstance(c,types.CodeType)})
    def replace(co):
        constants=[]
        for c in co.co_consts:
            if isinstance(c,types.CodeType):
                if c.co_name in ('collect','error_reason') and c.co_name in functions:
                    c=functions[c.co_name]
                elif co.co_name=='VbkEditor' and c.co_name in ('verify_resource','merchant'):
                    c=functions[c.co_name]
                else:c=replace(c)
            constants.append(c)
        return co.replace(co_consts=tuple(constants))
    return replace(code)
