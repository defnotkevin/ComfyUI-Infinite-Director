"""Deterministic timecodes and reference binding around the creative agent."""
from __future__ import annotations
import copy
import re
from .core import plan, validate_project, digest, identifier

RANGE = re.compile(r'^\s*\(?\s*(\d+(?:\.\d+)?)\s*(?:s|seconds?)?\s*[-–—]\s*(\d+(?:\.\d+)?)\s*(?:s|seconds?)?\s*\)?\s*[:\-]?\s*(.+)$', re.I)
ROLES = ('general', 'environment', 'prop', 'camera', 'wardrobe', 'depth', 'pose', 'motion')


def migrate(project):
    """Read-time migration; legacy scene assets remain available without losing media."""
    project.setdefault('other_references', [])
    project.setdefault('designs', [])
    project.setdefault('plan_notes', [])
    legacy = project.get('assets', {}).get('scene')
    if legacy and not any(r['id'] == 'ref_legacy_scene' for r in project['other_references']):
        project['other_references'].append(dict(legacy, id='ref_legacy_scene', label='Previous scene reference', role='environment', media_type='image', notes=''))
    return project


def reference_catalog(project):
    return [{k:r.get(k) for k in ('id','label','role','media_type','notes','duration')} for r in project.get('other_references', [])]


def bound_references(project, item):
    ids = item.get('reference_ids', [])
    catalog = {r['id']: r for r in project.get('other_references', [])}
    if not isinstance(ids, list) or any(not isinstance(i,str) for i in ids) or len(ids) != len(set(ids)) or any(i not in catalog for i in ids):
        raise ValueError('Unknown or duplicate reference binding')
    return [catalog[i] for i in ids]


def plan_direction(project, target_seconds=6):
    """Preserve explicit intervals; fill holes with separate, auditable holds."""
    migrate(project)
    lines = project.get('direction', '').splitlines()
    timed, common = [], []
    for line in lines:
        match = RANGE.match(line)
        if match:
            start, end, instruction = match.groups()
            start, end = round(float(start)*project['fps']), round(float(end)*project['fps'])
            if start < 0 or end <= start or end > project['total_frames']:
                raise ValueError('A direction time range is empty or extends beyond the performance duration')
            if timed and start < timed[-1][1]:
                raise ValueError('Direction time ranges must be ordered and non-overlapping')
            timed.append((start,end,instruction))
        elif line.strip():
            common.append(line.strip())
    if not timed:
        plan(project,target_seconds)
        for shot in project['shots']:
            shot['direction_text'] = project.get('direction','')
            shot['reference_ids'] = []
        project['plan_notes'] = ['Automatic cut timing; no explicit time ranges supplied.']
        return project
    catalog = {r['id']:r for r in project['other_references']}
    notes, spans, cursor, previous = [], [], 0, 'Hold the default camera angle and position.'
    for start,end,instruction in timed:
        if start > cursor:
            spans.append((cursor,start,previous,True))
            notes.append(f'{cursor/project["fps"]:g}–{start/project["fps"]:g}s: hold preceding setup (unspecified interval).')
        spans.append((start,end,instruction,False));cursor=end;previous=instruction
    if cursor < project['total_frames']:
        spans.append((cursor,project['total_frames'],previous,True))
        notes.append('Hold the last setup to the end of the performance.')
    plan(project,target_seconds)
    base=project['shots'][0]
    bounded=[]
    limit=round(float(target_seconds)*project['fps'])
    for start,end,instruction,hold in spans:
        cursor=start
        while cursor<end:
            stop=min(end,cursor+limit)
            bounded.append((cursor,stop,instruction,hold))
            cursor=stop
        if end-start>limit:
            notes.append(f'{start/project["fps"]:g}–{end/project["fps"]:g}s split into bounded renders; maintain this setup across cuts.')
    spans=bounded
    shots=[]
    for i,(start,end,instruction,hold) in enumerate(spans):
        ids=re.findall(r'@(ref_[A-Za-z0-9_-]+)', instruction)
        if any(r not in catalog for r in ids):
            raise ValueError('Direction mentions an unknown reference ID; use the IDs displayed in Other References')
        if re.search(r'\bthis\s+(image|video|reference)\b',instruction,re.I) and not ids:
            if len(catalog)==1: ids=list(catalog)
            else: raise ValueError('“THIS IMAGE/VIDEO” is ambiguous. Insert its @ref_… ID from Other References.')
        shot=copy.deepcopy(base)
        shot.update(id=f'shot_{i+1:04d}',start=start,end=end,seed=1000+i,direction_text=instruction,
                    purpose='Hold preceding setup' if hold else 'Follow timed direction',
                    reference_ids=list(dict.fromkeys(ids)),is_hold=hold,
                    notes='Hold this setup; do not replay its camera movement.' if hold else '')
        shots.append(shot)
    project.update(shots=shots,plan_notes=notes,global_direction='\n'.join(common),planner='timecode')
    return validate_project(project)


def design_key(project, design):
    return digest({'id':design['id'],'prompt':design['prompt'],'references':bound_references(project,design),
                   'bible':project.get('bible',''), 'character':project.get('assets',{}).get('character'),
                   'source':project.get('assets',{}).get('source'),
                   'template':project.get('templates',{}).get('reference'),'canvas':project.get('canvas_design_signature'),'seed':design.get('seed',100)})


def current_designs(project):
    return [d for d in project.get('designs',[]) if d.get('file') and d.get('key') == design_key(project,d)]
