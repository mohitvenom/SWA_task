"""Language detection for repository files."""

import os

_EXTENSION_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".sh": "Shell",
    ".md": "Markdown",
    ".json": "JSON",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".html": "HTML",
    ".css": "CSS",
    ".toml": "TOML",
    ".xml": "XML",
}


def detect_language(file_path: str) -> str:
    """
    Detect the programming language based on the file extension.

    Args:
        file_path: The path or name of the file.

    Returns:
        The detected language name, or 'Unknown' if not recognized.
    """
    _, ext = os.path.splitext(file_path)
    return _EXTENSION_MAP.get(ext.lower(), "Unknown")
