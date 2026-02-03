"""Setup main module for MCP Code Intelligence."""

from mcp_code_intelligence.core.languages import SUPPORTED_LANGUAGES

# Define available language servers
available_lsps = {
    "python": "pyright",
    "javascript": "typescript-language-server",
    "typescript": "typescript-language-server",
    "java": "jdtls",
    "csharp": "omnisharp",
    "ruby": "solargraph",
    "php": "intelephense",
    "go": "gopls",
    "rust": "rust-analyzer",
    "kotlin": "kotlin-language-server",
}

# Example function to print supported languages
def print_supported_languages():
    print("Supported languages:")
    for lang in SUPPORTED_LANGUAGES:
        print(f"- {lang}")

if __name__ == "__main__":
    print_supported_languages()
