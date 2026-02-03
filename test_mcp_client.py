import subprocess
import json
import time
import os

def test_mcp_startup():
    env = os.environ.copy()
    env["PYTHONPATH"] = "c:/Users/mahir/Desktop/mcp-server/mcp-vector-search/src"
    env["MCP_PROJECT_ROOT"] = "C:/Users/mahir/Desktop/orm-drf"
    
    cmd = [
        r"C:\Users\mahir\AppData\Local\Programs\Python\Python312\python.exe",
        "-m", "mcp_code_intelligence.mcp"
    ]
    
    print(f"Starting MCP server: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True
    )
    
    # Wait a bit to see if it crashes
    time.sleep(5)
    
    if process.poll() is not None:
        print(f"Process exited with code {process.returncode}")
        stdout, stderr = process.communicate()
        print("STDOUT:", stdout)
        print("STDERR:", stderr)
        return
    
    print("Process still running. Sending initialize request...")
    
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        }
    }
    
    try:
        process.stdin.write(json.dumps(init_request) + "\n")
        process.stdin.flush()
        
        # Read response
        print("Waiting for response...")
        # Since we are using stdio, we need to be careful with reading.
        # Simple read for one line.
        response = process.stdout.readline()
        print("Response received:", response)
        
        # Close
        process.terminate()
    except Exception as e:
        print(f"Error during communication: {e}")
        process.kill()

if __name__ == "__main__":
    test_mcp_startup()
