import json

with open(r'd:\Wows Paragrams Unpack\data\split\Ship\PJSB520_Raiju.json', 'r', encoding='utf-8') as f:
    raiju = json.load(f)

with open(r'd:\Wows Paragrams Unpack\data\split\Ship\PRSB210_Admiral_Lazarev.json', 'r', encoding='utf-8') as f:
    lazarev = json.load(f)

# Print top-level keys
print('=== Raiju top keys ===')
for k in raiju.keys():
    print(f'  {k}')
print()

print('=== Lazarev top keys ===')
for k in lazarev.keys():
    print(f'  {k}')
print()

# Model
print('=== MODELS ===')
print(f'Raiju model: {raiju.get("model", "N/A")}')
print(f'Lazarev model: {lazarev.get("model", "N/A")}')
print()

# A_Hull model
if 'A_Hull' in raiju:
    print(f'Raiju A_Hull.model: {raiju["A_Hull"].get("model", "N/A")}')
if 'A_Hull' in lazarev:
    print(f'Lazarev A_Hull.model: {lazarev["A_Hull"].get("model", "N/A")}')
print()

# Level
print(f'Raiju level: {raiju.get("level")}')
print(f'Lazarev level: {lazarev.get("level")}')
print()

# Type info
print(f'Raiju typeinfo: {raiju.get("typeinfo")}')
print(f'Lazarev typeinfo: {lazarev.get("typeinfo")}')
print()

# Find torpedo-related keys
def find_torpedo_keys(d, path=''):
    results = []
    if isinstance(d, dict):
        for k, v in d.items():
            kl = k.lower()
            if any(x in kl for x in ['torpedo', 'torp', 'bulge', 'anti_torpedo', 'tb_skip']):
                results.append((f'{path}.{k}', v))
            results.extend(find_torpedo_keys(v, f'{path}.{k}'))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            results.extend(find_torpedo_keys(v, f'{path}[{i}]'))
    return results

print('=== Raiju torpedo-related keys ===')
for k, v in find_torpedo_keys(raiju):
    print(f'  {k} = {v}')
print()
print('=== Lazarev torpedo-related keys ===')
for k, v in find_torpedo_keys(lazarev):
    print(f'  {k} = {v}')
print()

# Compare A_Hull key values
print('=== A_HULL COMPARISON ===')
raiju_hull = raiju.get('A_Hull', {})
lazarev_hull = lazarev.get('A_Hull', {})

# Size
print(f'Raiju size: {raiju_hull.get("size")}')
print(f'Lazarev size: {lazarev_hull.get("size")}')
print(f'Raiju mass: {raiju_hull.get("mass")}')
print(f'Lazarev mass: {lazarev_hull.get("mass")}')
print(f'Raiju tonnage: {raiju_hull.get("tonnage")}')
print(f'Lazarev tonnage: {lazarev_hull.get("tonnage")}')
print(f'Raiju health: {raiju_hull.get("health")}')
print(f'Lazarev health: {lazarev_hull.get("health")}')
print(f'Raiju maxSpeed: {raiju_hull.get("maxSpeed")}')
print(f'Lazarev maxSpeed: {lazarev_hull.get("maxSpeed")}')
print(f'Raiju draft: {raiju_hull.get("draft")}')
print(f'Lazarev draft: {lazarev_hull.get("draft")}')
print(f'Raiju turningRadius: {raiju_hull.get("turningRadius")}')
print(f'Lazarev turningRadius: {lazarev_hull.get("turningRadius")}')
print()

# Check for torpedoDamageReduction or similar at ship level
print('=== SHIP LEVEL TORPEDO PROTECTION ===')
for key in ['torpedoProtection', 'torpedoDamageCoeff', 'antiTorpedoProtection', 'torpedoDamageReduction']:
    if key in raiju:
        print(f'Raiju.{key}: {raiju[key]}')
    if key in lazarev:
        print(f'Lazarev.{key}: {lazarev[key]}')
print()

# Check all hull hitlocations for something related to torpedo
print('=== HULL HITLOCATIONS (first few) ===')
for hl_name in ['Hull', 'Cit', 'Bow', 'St', 'Cas', 'SS', 'SG', 'Ammo_1', 'Ammo_2']:
    if hl_name in raiju_hull:
        hl = raiju_hull[hl_name]
        print(f'Raiju {hl_name}: maxHP={hl.get("maxHP")}, volume={hl.get("volume")}, volumeCoeff={hl.get("volumeCoeff")}')
    if hl_name in lazarev_hull:
        hl = lazarev_hull[hl_name]
        print(f'Lazarev {hl_name}: maxHP={hl.get("maxHP")}, volume={hl.get("volume")}, volumeCoeff={hl.get("volumeCoeff")}')

print()

# Print ALL keys in A_Hull that differ or are interesting
print('=== ALL A_HULL KEYS ===')
all_keys = set(list(raiju_hull.keys()) + list(lazarev_hull.keys()))
for k in sorted(all_keys):
    if k in ['armor', 'splashBoxes', 'effects', 'customMiscs', 'burnNodes', 'floodNodes', 
             'sinkStartTime', 'sinkTime', 'deathSettings', 'sinkingEffects',
             'buoyancyStates', 'armorSegments', 'exteriorDecalsData',
             'barbettes', 'crackNodes', 'chimneyMaxAngle', 'deathBubblesEffect',
             'deathFaultEffect', 'deathFireEffect', 'deathFoamEffect',
             'deathFountainsEffect', 'deathFumingEffect', 'deathPlaneEffect',
             'deathPostFireEffect', 'deathShellEffect', 'deathTorpedoEffect',
             'deathUnderWaterBubblesEffects']:
        continue
    rv = raiju_hull.get(k, '<<MISSING>>')
    lv = lazarev_hull.get(k, '<<MISSING>>')
    if str(rv) != str(lv):
        print(f'  {k}:')
        print(f'    Raiju:   {rv}')
        print(f'    Lazarev: {lv}')
print()

# Armor comparison - just the keys
print('=== ARMOR KEYS COUNT ===')
raiju_armor = raiju_hull.get('armor', {})
lazarev_armor = lazarev_hull.get('armor', {})
print(f'Raiju armor entries: {len(raiju_armor)}')
print(f'Lazarev armor entries: {len(lazarev_armor)}')

# Compare common armor keys
common = set(raiju_armor.keys()) & set(lazarev_armor.keys())
only_raiju = set(raiju_armor.keys()) - set(lazarev_armor.keys())
only_lazarev = set(lazarev_armor.keys()) - set(raiju_armor.keys())
print(f'Common armor keys: {len(common)}')
print(f'Only in Raiju: {len(only_raiju)}')
print(f'Only in Lazarev: {len(only_lazarev)}')

# Show differences in common keys
diffs = 0
for k in sorted(common):
    if raiju_armor[k] != lazarev_armor[k]:
        diffs += 1
        if diffs <= 20:
            print(f'  ARMOR DIFF {k}: Raiju={raiju_armor[k]}, Lazarev={lazarev_armor[k]}')
print(f'Total armor value diffs: {diffs}')

# Check for citadel HP difference
print()
print(f'Raiju Cit.maxHP: {raiju_hull.get("Cit", {}).get("maxHP")}')
print(f'Lazarev Cit.maxHP: {lazarev_hull.get("Cit", {}).get("maxHP")}')
print(f'Raiju Hull.maxHP: {raiju_hull.get("Hull", {}).get("maxHP")}')
print(f'Lazarev Hull.maxHP: {lazarev_hull.get("Hull", {}).get("maxHP")}')
