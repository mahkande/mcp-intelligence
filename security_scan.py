#!/usr/bin/env python3
"""Security scan: Find all references to initialize() and call_tool() in server.py"""

import re
from pathlib import Path

server_file = Path("src/mcp_code_intelligence/mcp/server.py")

with open(server_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

print("=" * 80)
print("SECURITY SCAN: initialize() and call_tool() References in server.py")
print("=" * 80)

initialize_refs = []
call_tool_refs = []
internal_dependencies = []

for i, line in enumerate(lines, 1):
    # Look for initialize method definition and calls
    if re.search(r'def initialize\(', line):
        initialize_refs.append((i, "DEFINITION", line.rstrip()))
    elif re.search(r'await self\.initialize\(\)', line):
        initialize_refs.append((i, "CALL", line.rstrip()))
    elif re.search(r'self\._initialized', line):
        internal_dependencies.append((i, "_initialized state", line.rstrip()))

    # Look for call_tool method
    if re.search(r'def call_tool\(', line):
        call_tool_refs.append((i, "DEFINITION", line.rstrip()))
    elif re.search(r'await self\.call_tool\(', line):
        call_tool_refs.append((i, "CALL", line.rstrip()))

print("\n[1] initialize() References:")
print("-" * 80)
if initialize_refs:
    for line_no, ref_type, content in initialize_refs:
        print(f"  Line {line_no:4d} [{ref_type:10s}]: {content[:70]}")
else:
    print("  No references found")

print("\n[2] call_tool() References:")
print("-" * 80)
if call_tool_refs:
    for line_no, ref_type, content in call_tool_refs:
        print(f"  Line {line_no:4d} [{ref_type:10s}]: {content[:70]}")
else:
    print("  No references found")

print("\n[3] Internal State Dependencies (_initialized flag):")
print("-" * 80)
if internal_dependencies:
    for line_no, dep_type, content in internal_dependencies[:10]:
        print(f"  Line {line_no:4d} [{dep_type:20s}]: {content[:60]}")
    if len(internal_dependencies) > 10:
        print(f"  ... and {len(internal_dependencies) - 10} more")
else:
    print("  No internal state dependencies found")

# Check for private method access patterns
print("\n[4] Hidden Dependencies - Private Method Access Patterns:")
print("-" * 80)
private_patterns = [
    (r'self\._[a-z_]+\(', "Private method calls"),
    (r'self\._[a-z_]+\s*=', "Private attribute assignments"),
    (r'self\.indexer', "Direct indexer access"),
    (r'self\.database', "Direct database access"),
    (r'self\.search_engine', "Direct search_engine access"),
]

hidden_deps = {}
for pattern, desc in private_patterns:
    matches = []
    for i, line in enumerate(lines, 1):
        if re.search(pattern, line) and "def " not in line:
            matches.append(i)
    if matches:
        hidden_deps[desc] = matches[:5]

if hidden_deps:
    for dep_desc, line_nums in hidden_deps.items():
        print(f"  {dep_desc}: {len(line_nums)} occurrences (lines {line_nums})")
else:
    print("  No risky private method access patterns found!")

print("\n" + "=" * 80)
print("SECURITY SCAN SUMMARY")
print("=" * 80)
print(f"✓ initialize() references: {len(initialize_refs)}")
print(f"✓ call_tool() references: {len(call_tool_refs)}")
print(f"✓ Internal state dependencies: {len(internal_dependencies)}")
print(f"✓ Hidden dependencies (private access): {len(hidden_deps)}")
print("\n⚠️  CRITICAL: After service extraction, ensure:")
print("  1. All self._initialized access → SessionService.is_initialized")
print("  2. All self.call_tool() calls → RoutingService.route_tool_call()")
print("  3. All direct component access → Through service interfaces")
print("=" * 80)
