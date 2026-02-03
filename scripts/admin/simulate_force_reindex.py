import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_code_intelligence.core.relationships import RelationshipStore

async def main():
    project_root = Path(__file__).resolve().parents[2]
    rs = RelationshipStore(project_root)
    rs.invalidate()
    res = await rs.compute_and_store([], database=None, background=True)
    print('compute_and_store returned:', res)

if __name__ == '__main__':
    asyncio.run(main())
