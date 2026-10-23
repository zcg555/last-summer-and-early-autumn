"""Read the supplied executable's Python modules without starting its launcher."""
import importlib.abc, importlib.util, marshal, struct, sys, zlib
from pathlib import Path
ROOT = Path(__file__).parent
ARCHIVE = (ROOT/'recovered-v2.9/PYZ.pyz').read_bytes()
TOC = dict(marshal.loads(ARCHIVE[struct.unpack('!i', ARCHIVE[8:12])[0]:]))

def original_code(name):
    kind, pos, length = TOC[name]
    return marshal.loads(zlib.decompress(ARCHIVE[pos:pos+length]))

class BundleFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, patched=True): self.patched = patched
    def find_spec(self, fullname, path=None, target=None):
        source = ROOT/'changes'/Path(*fullname.split('.')).with_suffix('.py')
        if self.patched and (source.exists() or fullname == 'charter_quotes._legacy_async_probe'):
            return importlib.util.spec_from_loader(fullname, self, is_package=False)
        if fullname in TOC:
            return importlib.util.spec_from_loader(fullname, self, is_package=TOC[fullname][0] == 1)
    def create_module(self, spec): return None
    def exec_module(self, module):
        source = ROOT/'changes'/Path(*module.__name__.split('.')).with_suffix('.py')
        original_name = 'charter_quotes.async_probe' if module.__name__ == 'charter_quotes._legacy_async_probe' else module.__name__
        code = compile(source.read_text(encoding='utf-8'), str(source), 'exec') if self.patched and source.exists() else original_code(original_name)
        module.__file__ = str(ROOT/'recovered-v2.9'/Path(*module.__name__.split('.')).with_suffix('.pyc'))
        if hasattr(module,'__path__'):
            module.__path__=[str(ROOT/'recovered-v2.9'/Path(*module.__name__.split('.')))]
            module.__file__=str(Path(module.__path__[0])/'__init__.pyc')
        if module.__name__ == 'charter_quotes.quote_fields' and self.patched:
            replacement = compile((ROOT/'changes/floor_value.py').read_text(encoding='utf8'), 'floor_value.py', 'exec')
            fn = next(c for c in replacement.co_consts if hasattr(c, 'co_name') and c.co_name == 'floor_value')
            code = code.replace(co_consts=tuple(fn if hasattr(c,'co_name') and c.co_name=='floor_value' else c for c in code.co_consts))
        if module.__name__ == 'hourly_reprice' and self.patched:
            from bytecode_patches import patch_hourly
            code = patch_hourly(code)
        exec(code, module.__dict__)

def install(patched=True):
    sys.path.append(str(ROOT/'recovered-v2.9'))
    sys.meta_path.insert(0, BundleFinder(patched))
