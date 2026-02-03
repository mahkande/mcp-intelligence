
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path.cwd() / "src"))

from mcp_code_intelligence.utils.hashing import calculate_file_sha256, calculate_content_md5, calculate_id_hash
from mcp_code_intelligence.core.models import CodeChunk, Directory

def test_hashing_consistency():
    # 1. Test Content MD5
    content = "print('hello world')"
    h1 = calculate_content_md5(content)
    chunk = CodeChunk(content=content, file_path=Path("test.py"), start_line=1, end_line=1, language="python")
    assert chunk.content_hash == h1, f"Chunk hash mismatch: {chunk.content_hash} != {h1}"
    print("✅ Content MD5 consistency passed")
    
    # 2. Test ID Hashing (Sliced SHA-256)
    path_str = "src/main.py"
    # Use str(Path()) to ensure platform-native separators match dir_obj behavior
    h2 = calculate_id_hash(str(Path(path_str)))
    dir_obj = Directory(path=Path(path_str), name="main.py")
    assert dir_obj.id == h2, f"Directory ID mismatch: {dir_obj.id} != {h2}"
    assert len(dir_obj.id) == 16, f"Directory ID length mismatch: {len(dir_obj.id)}"
    print("✅ ID Hashing consistency passed")
    
    # 3. Test File SHA-256
    test_file = Path("test_hash_file.txt")
    test_file.write_bytes(b"some binary data")
    h3 = calculate_file_sha256(test_file)
    assert len(h3) == 64, "SHA-256 length should be 64"
    print("✅ File SHA-256 passed")
    test_file.unlink()

if __name__ == "__main__":
    test_hashing_consistency()
