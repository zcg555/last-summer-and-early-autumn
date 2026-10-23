"""City-specific floor settings; immutable worker snapshots and legacy migration."""
import copy
import json
import os
import re
from pathlib import Path
from .quote_fields import FLOORS, PACKAGES

CITIES = ('上海', '杭州')
DEFAULT_FLOORS = copy.deepcopy(FLOORS)
_active = None

def settings_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'XiaMoChuQiuCharter' / 'floor-prices-by-city.json'

def defaults():
    return {city: copy.deepcopy(DEFAULT_FLOORS) for city in CITIES}

def validate_table(values):
    if not isinstance(values, dict) or set(values) != set(DEFAULT_FLOORS):
        raise ValueError('底价表车型不完整，请填写全部车型')
    result = {}
    for vehicle, prices in values.items():
        if not isinstance(prices, list) or len(prices) != len(PACKAGES):
            raise ValueError(vehicle + '的5组套餐底价不完整')
        result[vehicle] = []
        for index, price in enumerate(prices):
            value = str(price).strip()
            if not re.fullmatch(r'[0-9]{1,7}', value) or not 1 <= int(value) <= 1000000:
                h, km = PACKAGES[index]
                raise ValueError(f'{vehicle} {h}小时/{km}公里：请输入1至1000000元的整数')
            result[vehicle].append(int(value))
    return result

def validate(values):
    if not isinstance(values, dict) or set(values) != set(CITIES):
        raise ValueError('底价表必须分别包含上海、杭州')
    result = {}
    for city in CITIES:
        try:
            result[city] = validate_table(values[city])
        except ValueError as exc:
            raise ValueError(f'{city}：{exc}') from exc
    return result

def load(path=None):
    target = Path(path) if path is not None else settings_path()
    if not target.exists() and path is None:
        legacy = target.with_name('floor-prices.json')
        if legacy.exists():
            target = legacy
    if not target.exists():
        return defaults()
    try:
        data = json.loads(target.read_text(encoding='utf8'))
        if data.get('packages') != [list(p) for p in PACKAGES]:
            raise ValueError('套餐格式不匹配')
        if data.get('version') == 1:
            table = validate_table(data['floors'])
            return {city: copy.deepcopy(table) for city in CITIES}
        if data.get('version') != 2:
            raise ValueError('底价版本不匹配')
        return validate(data['floors'])
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('已保存底价文件无效，请检查后使用“修复并保存两城底价”') from exc

def save(values, path=None):
    values = validate(values)
    target = Path(path) if path is not None else settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the previous city configuration before the first update of this release.
    if target.exists():
        backup = target.with_suffix('.pre-v2.10.bak')
        if not backup.exists():
            with backup.open('xb') as stream:
                stream.write(target.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
    temp = target.with_suffix('.tmp')
    with temp.open('w', encoding='utf8') as stream:
        json.dump(dict(version=2, packages=PACKAGES, floors=values), stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, target)
    return values

def save_city(city, values, path=None):
    if city not in CITIES:
        raise ValueError('不支持的底价城市')
    table = validate_table(values)
    current = load(path)
    current[city] = table
    return save(current, path)

def activate(values):
    global _active
    _active = validate(values)

def table_for_city(city):
    if city not in CITIES:
        raise ValueError('城市缺失或不支持，不能选择底价：' + str(city))
    if _active is not None:
        return _active[city]
    return load()[city]
