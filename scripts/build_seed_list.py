from __future__ import annotations
import hashlib, json, re
from datetime import date
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'seed' / 'gem_raw' / 'GEM_GHPT_2026-03.xlsx'
OUT = ROOT / 'data' / 'seed'
OUT.mkdir(parents=True, exist_ok=True)

SOURCE_PAGE = 'https://globalenergymonitor.org/projects/global-hydropower-tracker'
DOWNLOAD_URL = 'https://zenodo.org/api/records/20843067/files/GEM_GHPT.xlsx/content'
DATASET_VERSION = 'GEM Global Hydropower Tracker - March 2026 release'
IMPORT_DATE = date.today().isoformat()

if not RAW.exists():
    raise FileNotFoundError(RAW)

# Main sheet is the primary >=30 MW universe; Below Threshold is retained as an explicit supplement.
frames = []
for sheet, scope in [('Data', 'primary_30MW_plus'), ('Below Threshold', 'below_threshold_supplement')]:
    df = pd.read_excel(RAW, sheet_name=sheet)
    df['_gem_sheet'] = sheet
    df['_seed_scope'] = scope
    frames.append(df)
raw = pd.concat(frames, ignore_index=True)

# Preserve the raw values in a deterministic row hash; IDs remain the authoritative trace-back keys.
def clean(v):
    if pd.isna(v): return ''
    if isinstance(v, float) and v.is_integer(): return str(int(v))
    return str(v).strip()

def slug(v):
    s = re.sub(r'[^A-Z0-9]+', '-', clean(v).upper()).strip('-')
    return s or 'UNKNOWN'

def num(v):
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except Exception:
        return None

def row_hash(row):
    payload = '|'.join(clean(row.get(c)) for c in [
        'GEM location ID','GEM unit ID','Project Name','Capacity (MW)','Status','Country/Area 1','Country/Area 2'
    ])
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()

operating = {'operating'}
retained_station_like = {'operating', 'retired', 'mothballed'}
future = {'pre-construction', 'announced', 'construction'}

records=[]
for _, r in raw.iterrows():
    status = clean(r.get('Status')).lower()
    cap = num(r.get('Capacity (MW)'))
    if status in retained_station_like:
        entity_type = 'station'
    elif status in future or status:
        entity_type = 'project'
    else:
        entity_type = 'unknown'
    if clean(r.get('Complex')):
        # Keep project/station semantics while exposing complex membership separately.
        pass
    if status == 'operating':
        tier = 'A' if (cap is not None and cap >= 1000) else ('B' if (cap is not None and cap >= 300) else 'C')
    else:
        tier = 'D'
    loc = clean(r.get('GEM location ID'))
    unit = clean(r.get('GEM unit ID'))
    base_id = unit or loc or f'ROW-{len(records)+1:06d}'
    records.append({
        'entity_id': f'GEM-{base_id}',
        'entity_type': entity_type,
        'gem_row_type': 'facility_or_project_row',
        'canonical_name': clean(r.get('Project Name')),
        'aliases': clean(r.get('Other name(s)')),
        'local_name': clean(r.get('Project Name (local lang/script)')),
        'country': clean(r.get('Country/Area 1')),
        'country_2': clean(r.get('Country/Area 2')),
        'region': clean(r.get('Region 1')),
        'subregion': clean(r.get('Subregion 1')),
        'state_province': clean(r.get('State/Province 1')),
        'city': clean(r.get('City 1')),
        'local_area': clean(r.get('Local Area 1')),
        'major_area': clean(r.get('Major Area 1')),
        'river': clean(r.get('River / Watercourse')),
        'latitude': num(r.get('Latitude')),
        'longitude': num(r.get('Longitude')),
        'location_accuracy': clean(r.get('Location Accuracy')),
        'capacity_mw': cap,
        'country_1_capacity_mw': num(r.get('Country/Area 1 Capacity (MW)')),
        'country_2_capacity_mw': num(r.get('Country/Area 2 Capacity (MW)')),
        'turbines': clean(r.get('Turbines')),
        'status': status,
        'technology': clean(r.get('Technology Type')),
        'operator': clean(r.get('Operator')),
        'owner': clean(r.get('Owner')),
        'commissioning_year': num(r.get('Start Year')),
        'retired_year': num(r.get('Retired Year')),
        'complex_name': clean(r.get('Complex')),
        'binational': clean(r.get('Binational')),
        'gem_location_id': loc,
        'gem_unit_id': unit,
        'gem_wiki_url': clean(r.get('Wiki URL')),
        'gem_sheet': clean(r.get('_gem_sheet')),
        'seed_scope': clean(r.get('_seed_scope')),
        'source_seed': 'GEM_GHT',
        'source_url': SOURCE_PAGE,
        'download_url': DOWNLOAD_URL,
        'source_date': clean(r.get('Date Last Researched')),
        'dataset_version': DATASET_VERSION,
        'registry_version': 'seed-v1',
        'raw_record_hash': row_hash(r),
        'priority_tier': tier,
        'collection_priority': {'A': 1, 'B': 2, 'C': 3, 'D': 4}[tier],
        'discovery_status': 'not_started',
        'generation_status': 'not_started' if entity_type == 'station' else 'not_applicable',
        'needs_review': 'yes' if (cap is None or not (-90 <= (num(r.get('Latitude')) or 0) <= 90) or not (-180 <= (num(r.get('Longitude')) or 0) <= 180)) else 'no',
        'notes': ''
    })

cols = list(records[0].keys())
out_df = pd.DataFrame(records, columns=cols)
# Stable and reproducible ordering: priority first, then capacity descending, then ID.
out_df = out_df.sort_values(['collection_priority','capacity_mw','entity_id'], ascending=[True,False,True], na_position='last').reset_index(drop=True)

station_df = out_df[out_df.entity_type == 'station'].copy()
project_df = out_df[out_df.entity_type == 'project'].copy()

# Excel-friendly UTF-8 BOM while keeping CSV interoperable.
for name, df in [('master_registry.csv', out_df), ('station_seed_list.csv', station_df), ('project_seed_list.csv', project_df)]:
    df.to_csv(OUT / name, index=False, encoding='utf-8-sig')

status_counts = {str(k): int(v) for k,v in out_df['status'].value_counts(dropna=False).items()}
tech_counts = {str(k) if str(k) else '(blank)': int(v) for k,v in out_df['technology'].value_counts(dropna=False).items()}
country_counts = {str(k) if str(k) else '(blank)': int(v) for k,v in out_df['country'].value_counts(dropna=False).items()}
report = {
    'generated_at': IMPORT_DATE,
    'source': {'dataset_version': DATASET_VERSION, 'source_page': SOURCE_PAGE, 'download_url': DOWNLOAD_URL, 'local_raw_file': str(RAW), 'license_note': 'GEM data is distributed under CC BY 4.0; retain attribution when redistributing.'},
    'input': {'sheets': {'Data': int(sum(raw['_gem_sheet']=='Data')), 'Below Threshold': int(sum(raw['_gem_sheet']=='Below Threshold'))}, 'raw_total_records': int(len(raw))},
    'output': {'master_registry_records': int(len(out_df)), 'station_seed_records': int(len(station_df)), 'project_seed_records': int(len(project_df))},
    'status_distribution': status_counts,
    'technology_distribution': tech_counts,
    'country_count': int(out_df['country'].replace('', pd.NA).nunique()),
    'country_distribution_top20': dict(sorted(country_counts.items(), key=lambda kv: kv[1], reverse=True)[:20]),
    'quality_checks': {
        'duplicate_gem_location_id': int(out_df['gem_location_id'].replace('', pd.NA).duplicated().sum()),
        'duplicate_gem_unit_id': int(out_df['gem_unit_id'].replace('', pd.NA).duplicated().sum()),
        'missing_name': int((out_df['canonical_name']=='').sum()),
        'missing_capacity': int(out_df['capacity_mw'].isna().sum()),
        'capacity_nonpositive': int((out_df['capacity_mw'].fillna(0) <= 0).sum()),
        'capacity_below_zero': int((out_df['capacity_mw'].fillna(0) < 0).sum()),
        'invalid_latitude': int(((out_df['latitude'].notna()) & ~out_df['latitude'].between(-90,90)).sum()),
        'invalid_longitude': int(((out_df['longitude'].notna()) & ~out_df['longitude'].between(-180,180)).sum()),
        'complex_membership_rows': int((out_df['complex_name']!='').sum()),
        'needs_review_rows': int((out_df['needs_review']=='yes').sum()),
    },
    'priority_distribution': {str(k): int(v) for k,v in out_df['priority_tier'].value_counts().sort_index().items()},
    'rules': [
        'Data sheet is the primary >=30 MW universe in the March 2026 release.',
        'Below Threshold sheet is retained as a supplement and is not discarded.',
        'GEM unit ID is preferred for entity_id because one GEM location can contain multiple unit/project rows.',
        'Operating, retired, and mothballed rows are station-like; future statuses are project rows.',
        'Tier A/B/C apply to operating rows by capacity (>=1000 MW, 300-999.99 MW, <300 MW); all non-operating rows are Tier D.',
        'Seed List is not an annual generation ranking; generation records will be collected separately.'
    ]
}
(OUT/'seed_import_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

readme = f'''# GEM Master Seed List (V1)\n\n- 数据源：Global Energy Monitor（GEM）Global Hydropower Tracker，March 2026 release。\n- 原始文件：`{RAW.relative_to(ROOT).as_posix()}`\n- 生成日期：{IMPORT_DATE}\n- 主表记录：{len(out_df)}；其中 station：{len(station_df)}，project：{len(project_df)}。\n\n## 文件\n\n- `master_registry.csv`：完整主注册表，包含 Data 和 Below Threshold 两个工作表。\n- `station_seed_list.csv`：Operating/Retired/Mothballed 等 station-like 记录。\n- `project_seed_list.csv`：Announced/Construction/Pre-construction 及其他非 station-like 记录。\n- `seed_import_report.json`：导入统计和质量检查。\n- `gem_raw/`：不可修改的原始下载文件。\n\n## 重要说明\n\n1. 一行保留为一个 GEM unit/project row；同一 `gem_location_id` 出现多行时不擅自合并，因为它可能对应不同容量、状态或机组。\n2. `entity_id` 优先由 GEM unit ID 生成，`gem_location_id` 和 `gem_unit_id` 都保留以便回溯。\n3. 该列表是候选实体基础，不是年度发电量 Ground Truth，也不是最终 Top 100。\n4. GEM 数据许可为 CC BY 4.0；对外发布时应保留 GEM 署名。\n5. 年度发电量应写入独立的 GenerationRecord 表，并关联来源和证据。\n\n来源页面：{SOURCE_PAGE}\n下载地址（本次原始文件获取地址）：{DOWNLOAD_URL}\n'''
(OUT/'README.md').write_text(readme, encoding='utf-8')
print(json.dumps({'master':len(out_df),'station':len(station_df),'project':len(project_df),'report':str(OUT/'seed_import_report.json')},ensure_ascii=False))
