"""Check staged product changes without printing private content.

Run before committing/pushing. This guard reduces accidental publication; it
cannot establish customer consent or prove arbitrary source code is anonymous.
"""
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT_FILES = {".gitignore", ".gitattributes", "README.md", "AI_INSTRUCTIONS.md",
              "pyproject.toml", "requirements.txt", "LICENSE", "MANIFEST.in", "start.bat"}
PUBLIC_ROOTS = {"src", "tests", "scripts", "docs", ".github"}
TEXT_SUFFIXES = {".py", ".md", ".html", ".css", ".js", ".toml", ".yml", ".yaml", ".txt"}
PRIVATE_PARTS = {"data", "cache", "imports", "exports", "logs", "release", "dist",
                 "reference-outputs", "original-tools", ".workbuddy"}


def local_secrets(root: Path) -> list[bytes]:
    values = []
    for path in (root / ".env", root / ".env.local"):
        if path.exists():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                key, sep, value = line.partition("=")
                value = value.strip().strip('"\'')
                if sep and re.search(r"password|passwd|secret|token|api_key", key, re.I) and len(value) >= 8:
                    values.append(value.encode())
    return values


def inspect(path: str, content: bytes, secrets: list[bytes]) -> list[str]:
    name = PurePosixPath(path)
    reasons = []
    if any(part.lower() in PRIVATE_PARTS or part.startswith(".env") for part in name.parts):
        reasons.append("private path")
    if path not in ROOT_FILES and (name.parts[0] not in PUBLIC_ROOTS or name.suffix.lower() not in TEXT_SUFFIXES):
        reasons.append("outside product source allowlist")
    if len(content) > 2_000_000 or b"\x00" in content:
        reasons.append("binary or oversized content")
    if any(value in content for value in secrets):
        reasons.append("contains a local credential value")
    if re.search(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", content):
        reasons.append("private key")
    if re.search(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})", content):
        reasons.append("credential token")
    return reasons


def main() -> int:
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    names = subprocess.check_output(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"])
    secrets = local_secrets(root)
    failures = []
    for encoded in names.split(b"\0"):
        if not encoded:
            continue
        path = encoded.decode("utf-8")
        blob = subprocess.check_output(["git", "show", ":" + path])
        reasons = inspect(path, blob, secrets)
        if reasons:
            failures.append((path, reasons))
    for path, reasons in failures:
        print(f"BLOCKED {path}: {', '.join(reasons)}")
    count = len([name for name in names.split(bytes([0])) if name])
    print(f"Publication guard: {'blocked' if failures else 'passed'} ({count} staged files).")
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
