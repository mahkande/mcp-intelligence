import json
from pathlib import Path
from difflib import SequenceMatcher
import ast

root = Path(__file__).resolve().parents[1]
meta = json.loads((root / 'scripts' / 'arch_analysis.json').read_text(encoding='utf-8'))

# Build mapping from short module name to files
files = list(meta.keys())
short_to_files = {}
for f in files:
    name = Path(f).stem
    short_to_files.setdefault(name, []).append(f)

# Build import edges
edges = []
for f, info in meta.items():
    for imp in info['imports']:
        # map imports like 'database' or 'services.reranker' to file paths
        imp_base = imp.split('.')[0]
        targets = short_to_files.get(imp_base, [])
        for t in targets:
            edges.append((f, t))

# Compute fan-in/out
outbound = {}
inbound = {}
for a,b in edges:
    outbound.setdefault(a, set()).add(b)
    inbound.setdefault(b, set()).add(a)

# Metrics per file
metrics = {}
for f, info in meta.items():
    metrics[f] = {
        'lines': info['lines'],
        'imports_count': len(info['imports']),
        'classes': info['classes'],
        'functions': info['functions'],
        'fan_out': len(outbound.get(f,[])),
        'fan_in': len(inbound.get(f,[])),
    }

# Identify top central nodes by fan_in and fan_out
by_fan_out = sorted(metrics.items(), key=lambda x: x[1]['fan_out'], reverse=True)[:10]
by_fan_in = sorted(metrics.items(), key=lambda x: x[1]['fan_in'], reverse=True)[:10]
by_imports = sorted(metrics.items(), key=lambda x: x[1]['imports_count'], reverse=True)[:10]
by_lines = sorted(metrics.items(), key=lambda x: x[1]['lines'], reverse=True)[:10]

# Extract function/method bodies
def extract_functions(file_path):
    src = Path(file_path).read_text(encoding='utf-8')
    try:
        tree = ast.parse(src)
    except Exception:
        return []
    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            try:
                start = node.lineno - 1
                end = node.end_lineno
                body = '\n'.join(src.splitlines()[start:end])
                qual = node.name
                # If method, try to get class parent
                parent = None
                for p in ast.walk(tree):
                    if isinstance(p, ast.ClassDef):
                        if node in p.body:
                            parent = p.name
                            break
                if parent:
                    qual = f"{parent}.{node.name}"
                funcs.append({'file': file_path, 'name': qual, 'body': body})
            except Exception:
                continue
    return funcs

all_funcs = []
for f in files:
    all_funcs.extend(extract_functions(f))

# Compute pairwise similarity (threshold 0.85), but limit comparisons to reasonable size
pairs = []
N = len(all_funcs)
for i in range(N):
    a = all_funcs[i]
    if len(a['body'].splitlines()) < 3:
        continue
    for j in range(i+1, N):
        b = all_funcs[j]
        if len(b['body'].splitlines()) < 3:
            continue
        # Skip same file trivial duplicates
        if a['file'] == b['file'] and a['name'] == b['name']:
            continue
        s = SequenceMatcher(None, a['body'], b['body']).ratio()
        if s >= 0.85:
            pairs.append({'a': a, 'b': b, 'score': round(s,3)})

# Heuristic God object detection: many methods + high fan_out/in + large lines
god_candidates = []
for f, m in metrics.items():
    method_count = sum(1 for fn in all_funcs if fn['file']==f)
    score = (m['fan_in'] + m['fan_out']) * 2 + method_count + (m['lines']/200)
    if method_count >= 10 or m['fan_in']+m['fan_out'] >= 8 or m['lines'] > 800:
        god_candidates.append((f, {'methods':method_count, 'fan_in':m['fan_in'],'fan_out':m['fan_out'],'lines':m['lines'],'score':score}))

god_candidates = sorted(god_candidates, key=lambda x: x[1]['score'], reverse=True)

report = {
    'top_fan_out': [(p[0],p[1]) for p in by_fan_out],
    'top_fan_in': [(p[0],p[1]) for p in by_fan_in],
    'top_imports': [(p[0],p[1]) for p in by_imports],
    'top_lines': [(p[0],p[1]) for p in by_lines],
    'god_candidates': god_candidates,
    'semantic_duplicates': pairs[:50],
}

out = root / 'reports'
out.mkdir(exist_ok=True)
(out / 'arch_report.json').write_text(json.dumps(report, indent=2))
print('Wrote report to', out / 'arch_report.json')
