import json

with open(r'd:\Wows Paragrams Unpack\data\split\Ship\PJSB520_Raiju.json','r',encoding='utf-8') as f:
    r = json.load(f)
with open(r'd:\Wows Paragrams Unpack\data\split\Ship\PRSB210_Admiral_Lazarev.json','r',encoding='utf-8') as f:
    l = json.load(f)

print('=== Raiju A_Hull top keys ===')
for k in sorted(r['A_Hull'].keys()):
    if not isinstance(r['A_Hull'][k], dict):
        print(f'  {k} = {r["A_Hull"][k]}')

print()
print('=== Keys present in Raiju but not Lazarev ===')
for k in sorted(set(r['A_Hull'].keys()) - set(l['A_Hull'].keys())):
    print(f'  {k}')

print()
print('=== Keys present in Lazarev but not Raiju ===')
for k in sorted(set(l['A_Hull'].keys()) - set(r['A_Hull'].keys())):
    print(f'  {k}')

print()
print('=== underwaterProtection check ===')
print(f'Raiju has underwaterProtection: {"underwaterProtection" in r["A_Hull"]}')
print(f'Lazarev has underwaterProtection: {"underwaterProtection" in l["A_Hull"]}')

print()
print('=== Raiju A_Hull keys with underwater/water/torpedo/protect/defense ===')
for k in r['A_Hull'].keys():
    kl = k.lower()
    if any(x in kl for x in ['underwater','water','torpedo','torp','protect','defense','bullet','ptz','птз']):
        print(f'  {k} = {r["A_Hull"][k]}')

print()
print('=== Lazarev A_Hull keys with underwater/water/torpedo/protect/defense ===')
for k in l['A_Hull'].keys():
    kl = k.lower()
    if any(x in kl for x in ['underwater','water','torpedo','torp','protect','defense','bullet','ptz','птз']):
        print(f'  {k} = {l["A_Hull"][k]}')

print()
print('=== Raiju ALL non-dict, non-list keys in A_Hull ===')
for k, v in r['A_Hull'].items():
    if not isinstance(v, (dict, list)):
        print(f'  {k}: {v}')

print()
print('=== Raiju health, draft, turningRadius, rudderTime, enginePower ===')
print(f'  health: {r["A_Hull"].get("health")}')
print(f'  draft: {r["A_Hull"].get("draft")}')
print(f'  turningRadius: {r["A_Hull"].get("turningRadius")}')
print(f'  rudderTime: {r["A_Hull"].get("rudderTime")}')
print(f'  enginePower: {r["A_Hull"].get("enginePower")}')

print()
print('=== Lazarev health, draft, turningRadius, rudderTime, enginePower ===')
print(f'  health: {l["A_Hull"].get("health")}')
print(f'  draft: {l["A_Hull"].get("draft")}')
print(f'  turningRadius: {l["A_Hull"].get("turningRadius")}')
print(f'  rudderTime: {l["A_Hull"].get("rudderTime")}')
print(f'  enginePower: {l["A_Hull"].get("enginePower")}')
