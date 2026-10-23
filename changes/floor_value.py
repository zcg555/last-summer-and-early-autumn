def floor_value(row):
    from .floor_settings import table_for_city
    table = table_for_city(row.get('city'))
    package = (int(row['hours']), int(row['kilometers']))
    values = table.get(row['vehicle_name'])
    return values[PACKAGES.index(package)] if values and package in PACKAGES else ''
