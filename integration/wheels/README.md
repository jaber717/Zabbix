# Offline Python wheels

The selected runtime ABI is CPython 3.11 from RHEL AppStream. M1 deliberately
ships no third-party wheels because the M4 integration dependency set is not yet
defined. When requirements exist, lock every transitive dependency with hashes
and install only with:

```bash
python3.11 -m pip install --no-index --find-links=<wheel-directory> \
  --require-hashes -r requirements.lock
```
