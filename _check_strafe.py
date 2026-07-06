import json, glob

# Find planes with rocket ammo - check bombName that starts with rocket prefix
rocket_planes = []
for f in glob.glob('data/split/Aircraft/*.json'):
    d = json.loads(open(f, encoding='utf-8').read())
    bn = d.get('bombName') or ''
    if bn.startswith('PAPR'):
        rocket_planes.append((f, d.get('name'), d.get('postAttackInvulnerabilityDuration'),
                              d.get('typeinfo',{}).get('species')))
        if len(rocket_planes) >= 3:
            break

if rocket_planes:
    for fp, nm, dur, sp in rocket_planes:
        print(f'File: {fp}')
        print(f'  name: {nm}')
        print(f'  species: {sp}')
        print(f'  postAttackInvulnerabilityDuration: {dur}')
        print()
else:
    print('No rocket planes found with PAPR prefix')
    # Try other prefixes
    for f in glob.glob('data/split/Aircraft/*.json'):
        d = json.loads(open(f, encoding='utf-8').read())
        bn = d.get('bombName') or ''
        if bn and ('rocket' in bn.lower() or 'PAPR' in bn):
            print(f'Found: {f} bombName={bn}')
            break
    else:
        print('No rocket planes found at all')
        # Show a few planes with their bombName
        for f in sorted(glob.glob('data/split/Aircraft/*.json'))[:10]:
            d = json.loads(open(f, encoding='utf-8').read())
            print(f'{f}: bombName={d.get("bombName")} species={d.get("typeinfo",{}).get("species")}')
