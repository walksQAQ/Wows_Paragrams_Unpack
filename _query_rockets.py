import json, os

proj_folder = 'D:/Wows Paragrams Unpack/data/split/Projectile'
air_folder = 'D:/Wows Paragrams Unpack/data/split/Aircraft'

# Map from projectile prefix to aircraft fighter prefix
# PR = Projectile Rocket -> AF = Attack Fighter (the plane that fires rockets)
nation_code = {
    'PAPR': 'PAAF',  # USA
    'PBPR': 'PBAF',  # UK
    'PJPR': 'PJAF',  # Japan
    'PGPR': 'PGAF',  # Germany
    'PFPR': 'PFAF',  # France
    'PIPR': 'PIAF',  # Italy
    'PRPR': 'PRAF',  # Russia
    'PZPR': 'PZAF',  # Pan-Asia
    'PUPR': 'PUAF',  # Commonwealth
    'PXPR': 'PXAF',  # Halloween/Event
    'PUPR': 'PUAF',  # Commonwealth
}

# All files with attackSequenceDurations
all_proj_files = sorted([f for f in os.listdir(proj_folder) if f.endswith('.json')])

found = 0
for fname in all_proj_files:
    pfile = os.path.join(proj_folder, fname)
    with open(pfile, 'r', encoding='utf-8') as fp:
        pdata = json.load(fp)
    
    seq = pdata.get('attackSequenceDurations')
    if seq is None:
        continue
    
    found += 1
    name = pdata.get('name', fname[:-5])
    pid = pdata.get('id', 'N/A')
    seq_str = ', '.join([str(s) for s in seq])
    
    prefix = name[:4]
    suffix = name[4:]
    air_prefix = nation_code.get(prefix)
    
    ac_count = 'N/A'
    air_name = 'N/A'
    
    if air_prefix:
        afile = air_prefix + suffix + '.json'
        apath = os.path.join(air_folder, afile)
        if os.path.exists(apath):
            with open(apath, 'r', encoding='utf-8') as fp:
                adata = json.load(fp)
            ac_count = adata.get('attackCount', 'N/A')
            air_name = afile
    
    if air_name == 'N/A':
        for af in os.listdir(air_folder):
            if af.endswith('.json') and af[4:] == suffix + '.json':
                with open(os.path.join(air_folder, af), 'r', encoding='utf-8') as fp:
                    adata = json.load(fp)
                ac_count = adata.get('attackCount', 'N/A')
                air_name = af
                break
    
    print(fname + ':')
    print('  proj.id=' + str(pid) + ', attackSequenceDurations=[' + seq_str + ']')
    print('  aircraft=' + air_name + ', attackCount=' + str(ac_count))
    print()

print('---')
print('Total projectile files with attackSequenceDurations: ' + str(found))
