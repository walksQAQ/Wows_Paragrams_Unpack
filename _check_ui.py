import json, glob

# Find ships with AirSupport in their modules
for sf in glob.glob('data/split/Ships/PASA*.json'):
    data = json.loads(open(sf, encoding='utf-8').read())
    modules = data.get('Modules', {})
    for mk, mv in modules.items():
        if 'AirSupport' in mk:
            print(f'{sf}')
            for k, v in mv.items():
                if isinstance(v, dict):
                    for ak, av in v.items():
                        if 'Armament' in ak:
                            print(f'  {ak}:')
                            for kk, vv in av.items():
                                print(f'    {kk}: {vv!r}')
            break
    else:
        continue
    break
