import ast
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'mcp_code_intelligence' / 'core'
files = list(ROOT.rglob('*.py'))

modules = {}

for f in files:
    rel = f.relative_to(ROOT.parent.parent) if False else f
    text = f.read_text(encoding='utf-8')
    try:
        tree = ast.parse(text)
    except Exception:
        tree = None
    imports = set()
    classes = []
    funcs = []
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imports.add(n.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                imports.add(module)
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, ast.FunctionDef):
                funcs.append(node.name)
    modules[str(f)] = {
        'imports': sorted([i for i in imports if i]),
        'classes': classes,
        'functions': funcs,
        'lines': len(text.splitlines())
    }

out = Path(__file__).resolve().parent / 'arch_analysis.json'
out.write_text(json.dumps(modules, indent=2))
print('Wrote', out)
