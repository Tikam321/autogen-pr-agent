import os
from pathlib import Path
from autogen_core.tools import FunctionTool

def read_file(path: str) -> str:
    data = Path(path).read_text(encoding="utf-8")
    return data

def write_file(path: str, content: str) -> str:
    Path(path).write_text(content, encoding="utf-8")
    return f"Written to {path}"

def edit_file(path: str, old_string: str, new_string: str) -> str:
    data = Path(path).read_text(encoding="utf-8")
    if old_string not in data:
        return f"Error: old_string not found in {path}"
    data = data.replace(old_string, new_string, 1)
    Path(path).write_text(data, encoding="utf-8")
    return f"Edited {path}"

def grep_search(pattern: str, path: str) -> list:
    import re
    matches = []
    for file_path in Path(path).rglob("*"):
        if file_path.is_file() and file_path.suffix in {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".env"}:
            try:
                for i, line in enumerate(file_path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if re.search(pattern, line):
                        matches.append(f"{file_path}:{i}: {line.strip()}")
            except Exception:
                pass
    return matches


def list_directory(path: str) -> list:
    entries = os.listdir(path)
    return [e + "/" if os.path.isdir(os.path.join(path, e)) else e for e in sorted(entries)]


file_tools = [
    FunctionTool(read_file, description="Read a file from the local filesystem and return its contents as a string"),
    FunctionTool(write_file, description="Write content to a file, overwriting if it exists"),
    FunctionTool(edit_file, description="Find and replace the first occurrence of a string in a file"),
    FunctionTool(grep_search, description="Search for a regex pattern in files under a directory (code/text files only)"),
    FunctionTool(list_directory, description="List files and directories in a given path, with trailing / for directories"),
]
