#!/usr/bin/env python3
"""Syntax gate: every Python file in the repository must compile, and every shell script must pass `bash -n`.

    python3 scripts/check-syntax.py            exit 0 = all files OK, 1 = at least one failure (file:line:message printed)

Files come from `git ls-files` when run inside a Git checkout (so the whole repository is covered, not just this project);
otherwise from walking the project directory. Standard library only. Python files are also parsed with the Python 3.8 grammar
(the minimum supported interpreter), so newer-only syntax cannot slip into a release.
v1.0.1 shipped with an unterminated string in scripts/ingest-handover.py because nothing compiled every file; this is that check.
"""
import ast
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.normpath(os.path.join(HERE, ".."))
MIN_GRAMMAR = (3, 8)
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "state"}


def tracked_files():
    try:
        top = subprocess.check_output(["git", "-C", PROJECT, "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL).decode().strip()
        out = subprocess.check_output(["git", "-C", top, "ls-files", "-z"], stderr=subprocess.DEVNULL).decode("utf-8", "replace")
        listed = [f for f in out.split("\0") if f]
        if listed:
            return top, listed
    except (OSError, subprocess.CalledProcessError):
        pass
    files = []                                    # not a Git checkout (or nothing tracked): walk the project directory
    for root, dirs, names in os.walk(PROJECT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        files += [os.path.relpath(os.path.join(root, n), PROJECT) for n in names]
    return PROJECT, files


def check_python(path):
    with open(path, "rb") as fh:
        src = fh.read()
    try:
        compile(src, path, "exec")                                   # same interpreter as the one running the gate
        ast.parse(src, path, feature_version=MIN_GRAMMAR)            # and the oldest supported grammar
    except SyntaxError as exc:
        return "%s:%s: %s" % (path, exc.lineno, exc.msg)
    except ValueError as exc:                                        # e.g. null bytes
        return "%s: %s" % (path, exc)
    return None


def check_bash(path, bash):
    res = subprocess.run([bash, "-n", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        return "%s: %s" % (path, res.stderr.decode("utf-8", "replace").strip().splitlines()[0] if res.stderr else "bash -n failed")
    return None


def main():
    top, files = tracked_files()
    failures, n_py, n_sh = [], 0, 0
    bash = shutil.which("bash")
    for rel in sorted(files):
        path = os.path.join(top, rel)
        if not os.path.isfile(path):
            continue
        if rel.endswith(".py"):
            n_py += 1
            err = check_python(path)
        elif rel.endswith(".sh"):
            n_sh += 1
            if bash is None:
                continue
            err = check_bash(path, bash)
        else:
            continue
        if err:
            failures.append(err)
    for f in failures:
        print("SYNTAX FAIL  " + f)
    print("syntax gate: %d python file(s) (grammar %d.%d+), %d shell script(s)%s - %s" % (
        n_py, MIN_GRAMMAR[0], MIN_GRAMMAR[1], n_sh, "" if bash else " (bash not found: shell syntax NOT checked)",
        "FAIL (%d)" % len(failures) if failures else "OK"))
    if bash is None and n_sh:
        return 1                                                      # a gate that silently skips is not a gate
    if n_py == 0:
        print("SYNTAX FAIL  no Python files were found: the gate would pass vacuously")
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
