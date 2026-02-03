# Deployment Guide

## 📦 Installation Methods

### PyPI Installation (Recommended)
```bash
# Install latest stable version
pip install mcp-code-intelligence

# Install specific version
pip install mcp-code-intelligence==0.0.3

# Upgrade to latest
pip install mcp-code-intelligence --upgrade
```

### UV Package Manager
```bash
# Add to project
uv add mcp-code-intelligence

# Install globally
uv tool install mcp-code-intelligence
```

### From Source
```bash
# Clone repository
git clone https://github.com/bobmatnyc/mcp-code-intelligence.git
cd mcp-code-intelligence

# Install with UV
uv sync && uv pip install -e .

# Or with pip
pip install -e .
```

---

## 🖥️ System Requirements

### Minimum Requirements
- **Python**: 3.11 or higher
- **Memory**: 512MB RAM
- **Storage**: 100MB free space
- **OS**: macOS, Linux, Windows

### Recommended Requirements
- **Python**: 3.12+
- **Memory**: 2GB RAM (for large codebases)
- **Storage**: 1GB free space
- **CPU**: Multi-core for faster indexing

### Dependencies
- **ChromaDB**: Vector database (auto-installed)
- **Sentence Transformers**: Embeddings (auto-installed)
- **Tree-sitter**: Code parsing (auto-installed)
- **Rich**: Terminal output (auto-installed)

---

## 🚀 Quick Start Deployment

### 1. Install Package
```bash
pip install mcp-code-intelligence
```

### 2. Verify Installation
```bash
mcp-code-intelligence version
mcp-code-intelligence --help
```

### 3. Initialize Project
```bash
cd /path/to/your/project
mcp-code-intelligence init
```

### 4. Index Codebase
```bash
mcp-code-intelligence index
```

### 5. Start Searching
```bash
mcp-code-intelligence search "authentication logic"
```

---

## 🏢 Production Deployment

### Docker Deployment
```dockerfile
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install mcp-code-intelligence
RUN pip install mcp-code-intelligence

# Set working directory
WORKDIR /workspace

# Copy your codebase
COPY . .

# Initialize and index
RUN mcp-code-intelligence init && mcp-code-intelligence index

# Default command
CMD ["mcp-code-intelligence", "search"]
```

### CI/CD Integration
```yaml
# .github/workflows/search-index.yml
name: Update Search Index
on:
  push:
    branches: [main]

jobs:
  update-index:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install mcp-code-intelligence
        run: pip install mcp-code-intelligence
      
      - name: Update search index
        run: |
          mcp-code-intelligence init
          mcp-code-intelligence index
      
      - name: Cache index
        uses: actions/cache@v3
        with:
          path: .mcp-code-intelligence/
          key: search-index-${{ github.sha }}
```

### Server Deployment
```bash
# Install on server
pip install mcp-code-intelligence

# Set up systemd service (optional)
sudo tee /etc/systemd/system/mcp-code-intelligence.service << EOF
[Unit]
Description=MCP Code Intelligence Watcher
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/project
ExecStart=/usr/local/bin/mcp-code-intelligence watch
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl enable mcp-code-intelligence
sudo systemctl start mcp-code-intelligence
```

---

## ⚙️ Configuration

### Environment Variables
```bash
# Optional: Custom embedding model
export MCP_EMBEDDING_MODEL="all-MiniLM-L6-v2"

# Optional: Custom database path
export MCP_DB_PATH="/custom/path/.mcp-code-intelligence"

# Optional: Logging level
export MCP_LOG_LEVEL="INFO"
```

### Configuration File
```yaml
# .mcp-code-intelligence/config.yaml
database:
  path: ".mcp-code-intelligence/db"
  collection_name: "code_chunks"

embedding:
  model: "all-MiniLM-L6-v2"
  batch_size: 32

indexing:
  chunk_size: 1000
  overlap: 200
  exclude_patterns:
    - "*.pyc"
    - "node_modules/"
    - ".git/"

search:
  max_results: 20
  similarity_threshold: 0.7
```

---

## 🔧 Troubleshooting

### Common Issues

#### Installation Problems
```bash
# Clear pip cache
pip cache purge

# Upgrade pip
pip install --upgrade pip

# Install with verbose output
pip install mcp-code-intelligence -v
```

#### Permission Errors
```bash
# Install for user only
pip install mcp-code-intelligence --user

# Or use virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install mcp-code-intelligence
```

#### Memory Issues
```bash
# Reduce batch size for large codebases
mcp-code-intelligence config set indexing.batch_size 16

# Index incrementally
mcp-code-intelligence index --incremental
```

#### Tree-sitter Issues
```bash
# Force regex fallback if Tree-sitter fails
mcp-code-intelligence config set parsing.force_regex true

# Check parser status
mcp-code-intelligence doctor
```

### Performance Optimization

#### Large Codebases
```bash
# Use parallel processing
mcp-code-intelligence index --parallel

# Exclude unnecessary files
mcp-code-intelligence config set indexing.exclude_patterns '["*.min.js", "dist/", "build/"]'

# Adjust chunk size
mcp-code-intelligence config set indexing.chunk_size 2000
```

#### Memory Usage
```bash
# Monitor memory usage
mcp-code-intelligence status --memory

# Reduce embedding dimensions (if supported)
mcp-code-intelligence config set embedding.dimensions 384
```

---

## 📊 Monitoring

### Health Checks
```bash
# Check system status
mcp-code-intelligence doctor

# Verify database integrity
mcp-code-intelligence status --detailed

# Test search functionality
mcp-code-intelligence search "test query" --dry-run
```

### Logging
```bash
# Enable debug logging
export MCP_LOG_LEVEL=DEBUG
mcp-code-intelligence index

# Log to file
mcp-code-intelligence index 2>&1 | tee indexing.log
```

### Metrics
```bash
# Show indexing statistics
mcp-code-intelligence status

# Performance metrics
mcp-code-intelligence status --performance
```

---

## 🔄 Updates

### Upgrading
```bash
# Check current version
mcp-code-intelligence version

# Upgrade to latest
pip install mcp-code-intelligence --upgrade

# Verify upgrade
mcp-code-intelligence version
```

### Migration
```bash
# Backup existing index
cp -r .mcp-code-intelligence .mcp-code-intelligence.backup

# Re-index after major updates
mcp-code-intelligence index --rebuild
```

---

## 🆘 Support

### Getting Help
- **Documentation**: [CLAUDE.md](../CLAUDE.md)
- **Issues**: [GitHub Issues](https://github.com/bobmatnyc/mcp-code-intelligence/issues)
- **Discussions**: [GitHub Discussions](https://github.com/bobmatnyc/mcp-code-intelligence/discussions)

### Reporting Issues
Include the following information:
- Operating system and version
- Python version
- mcp-code-intelligence version
- Error messages and logs
- Steps to reproduce


