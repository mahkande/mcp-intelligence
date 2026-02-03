# MCP Code Intelligence - Development Workflow

## 🔄 Three-Stage Development Process

### Stage A: Local Development & Testing 🛠️
*Test and fix in the current project environment*

#### Setup Development Environment
```bash
# Install in development mode (includes editable install)
make dev

# Install pre-commit hooks
uv run pre-commit install

# Run tests
make test-unit

# Run type checking and linting
make quality

# Auto-fix formatting and linting issues
make fix
```

#### Available Make Targets
The project uses a modular Makefile system with 97+ targets:

```bash
# View all available targets
make help

# Development
make dev                    # Install development environment
make test-unit             # Run unit tests
make test-integration      # Run integration tests
make quality               # Run all quality checks (ruff + mypy)
make fix                   # Auto-fix linting issues

# Dependencies
make lock-deps             # Lock dependencies (uv.lock)
make lock-update           # Update dependencies
make lock-info             # Show dependency information

# Release
make release-patch         # Create patch release
make release-minor         # Create minor release
make release-build         # Build distribution packages
```

#### Development Commands
```bash
# Test CLI locally
uv run mcp-code-intelligence --help
uv run mcp-code-intelligence version

# Test on this project
uv run mcp-code-intelligence init
uv run mcp-code-intelligence index
uv run mcp-code-intelligence search "semantic search"

# Run comprehensive tests with coverage
make test-coverage

# Debug commands
make debug-search QUERY="your search term"
make debug-mcp
make debug-health
```

#### Pre-commit Workflow
```bash
# Run quality checks before committing
make quality

# Auto-fix issues
make fix

# Run pre-commit hooks
uv run pre-commit run --all-files

# Commit changes
git add .
git commit -m "feat: your feature description"
```

---

### Stage B: Local Deployment Testing 🧪
*Deploy to this machine to test clean deployed version on other projects*

#### Install Clean Version Locally
```bash
# Uninstall development version
pip uninstall mcp-code-intelligence -y

# Install from local build
uv run python -m build
pip install dist/mcp_code_intelligence-*.whl

# Or install from PyPI (latest published)
pip install mcp-code-intelligence --upgrade
```

#### Test on Other Projects
```bash
# Navigate to a different project
cd ~/Projects/some-other-project

# Test initialization
mcp-code-intelligence init

# Test indexing
mcp-code-intelligence index

# Test search functionality
mcp-code-intelligence search "function definition"
mcp-code-intelligence search "error handling"

# Test file watching
mcp-code-intelligence watch &
# Make some file changes and verify updates

# Check status
mcp-code-intelligence status
```

#### Validation Checklist
- [ ] CLI commands work from any directory
- [ ] Can initialize new projects
- [ ] Indexing works on different codebases
- [ ] Search returns relevant results
- [ ] File watching detects changes
- [ ] No import errors or missing dependencies
- [ ] Performance is acceptable

---

### Stage C: PyPI Publication 🌍
*Publish to PyPI for others to test*

#### Pre-publication Checklist
- [ ] All tests pass locally
- [ ] Local deployment testing successful
- [ ] Version number updated
- [ ] CHANGELOG.md updated
- [ ] README.md reflects current features
- [ ] No sensitive data in code

#### Publication Process
```bash
# Update version in src/mcp_code_intelligence/__init__.py
# Update CHANGELOG.md

# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build package
uv run python -m build

# Check package
uv run twine check dist/*

# Upload to PyPI
uv run twine upload dist/*
```

#### Post-publication Testing
```bash
# Test fresh installation
python -m venv test-env
source test-env/bin/activate
pip install mcp-code-intelligence

# Verify installation
mcp-code-intelligence version
mcp-code-intelligence --help

# Test on sample project
mkdir test-project && cd test-project
mcp-code-intelligence init
echo "def hello(): pass" > test.py
mcp-code-intelligence index
mcp-code-intelligence search "hello"
```

---

## 🔧 Development Scripts

### Quick Development Test
```bash
#!/bin/bash
# scripts/dev-test.sh
set -e

echo "🧪 Running development tests..."
uv run pytest -v
uv run mypy src/
uv run mcp-code-intelligence version
echo "✅ Development tests passed!"
```

### Local Deployment Test
```bash
#!/bin/bash
# scripts/deploy-test.sh
set -e

echo "📦 Building and testing local deployment..."
uv run python -m build
pip uninstall mcp-code-intelligence -y || true
pip install dist/mcp_code_intelligence-*.whl
mcp-code-intelligence version
echo "✅ Local deployment test passed!"
```

### PyPI Publication
```bash
#!/bin/bash
# scripts/publish.sh
set -e

echo "🚀 Publishing to PyPI..."
rm -rf dist/ build/ *.egg-info
uv run python -m build
uv run twine check dist/*
uv run twine upload dist/*
echo "✅ Published to PyPI!"
```

---

## 🐛 Debugging Common Issues

### Stage A Issues
- **Import errors**: Check `uv sync` and virtual environment
- **Test failures**: Run `uv run pytest -v` for detailed output
- **Type errors**: Run `uv run mypy src/` to check types

### Stage B Issues
- **Command not found**: Check if package installed correctly
- **Permission errors**: Use virtual environment or `--user` flag
- **Different behavior**: Clear any cached files or configs

### Stage C Issues
- **Upload failures**: Check PyPI credentials and network
- **Installation failures**: Verify package dependencies
- **Version conflicts**: Ensure version number is incremented

---

## 📋 Version Management

### Semantic Versioning
- **0.0.x**: Alpha releases (breaking changes expected)
- **0.x.0**: Beta releases (feature additions)
- **x.0.0**: Stable releases (production ready)

### Release Process
1. Update version in `src/mcp_code_intelligence/__init__.py`
2. Update `CHANGELOG.md` with changes
3. Commit: `git commit -m "bump: version 0.0.x"`
4. Tag: `git tag v0.0.x`
5. Push: `git push && git push --tags`
6. Publish to PyPI

---

## 🎯 Best Practices

1. **Always test locally first** (Stage A)
2. **Verify clean deployment** (Stage B) before publishing
3. **Use semantic versioning** for clear expectations
4. **Keep CHANGELOG.md updated** for users
5. **Test on multiple projects** to ensure compatibility
6. **Monitor PyPI downloads** and user feedback



