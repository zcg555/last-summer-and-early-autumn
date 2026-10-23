"""Local release discovery. No download, network check, or automatic execution."""
import json
import os
import re
from pathlib import Path

def version_key(version):
    if not isinstance(version,str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}',version):
        raise ValueError('版本号无效')
    values=tuple(int(n) for n in version.split('.'))
    return values+(0,)*(4-len(values))

def catalog_path():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'XiaMoChuQiuCharter'/'latest-release.json'

def latest_release(path=None):
    target=Path(path) if path is not None else catalog_path()
    try:
        data=json.loads(target.read_text(encoding='utf8'))
        version_key(data['version'])
        executable=Path(data['executable'])
        if not executable.is_absolute() or executable.suffix.lower()!='.exe' or not executable.is_file():return None
        return dict(version=data['version'],executable=str(executable))
    except (OSError,ValueError,TypeError,KeyError):return None

def newer_release(current,path=None):
    current_key=version_key(current)
    release=latest_release(path)
    return release if release and version_key(release['version'])>current_key else None

def register_release(version,executable,path=None):
    key=version_key(version)
    executable=Path(executable).resolve()
    if executable.suffix.lower()!='.exe' or not executable.is_file():return False
    target=Path(path) if path is not None else catalog_path()
    previous=latest_release(target)
    if previous and version_key(previous['version'])>=key:return False
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name(target.name+f'.{os.getpid()}.tmp')
    try:
        with temp.open('w',encoding='utf8') as stream:
            json.dump(dict(version=version,executable=str(executable)),stream,ensure_ascii=False,indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp,target)
        return True
    finally:
        temp.unlink(missing_ok=True)
