# Vendored SQLite (S3.1 D16)

`sqlite3.dll` here replaces the one Python 3.11 bundles in the frozen program's `_internal\` (`package_app.py`,
`swap_sqlite`), so the program runs SQLite at or above the floor in `packaging/build_config.json` (`sqlite_min`,
3.51.3). A post-build check loads the frozen `_internal\sqlite3.dll` and reads `sqlite3_libversion`; below the floor the
build fails.

| | |
| --- | --- |
| Version | 3.53.4 (2026-07-24; the 3.53 line's latest, the version Python 3.15's Windows build bundles) |
| Source | https://sqlite.org/2026/sqlite-dll-win-x64-3530400.zip ("Precompiled Binaries for Windows", 64-bit DLL (x64)) |
| The zip's SHA3-256 | `deddee963c810d1eeac3ce5e15c7c41da21a1c54d7a39cf54fbf577d2f50de3a` (1,370,147 bytes), as sqlite.org/download.html published it while 3.53.4 was current (snapshot https://web.archive.org/web/20260919165441/https://sqlite.org/download.html); checked on download 2026-10-12 |
| `sqlite3.dll`'s sha256 | `ab57d0437795ecc757cb693f32ea224173fa9856594d95cfa6b5033e645cd1ec` (3,285,504 bytes; also `sqlite_dll_sha256` in build_config.json, checked before every swap) |
| Licence | Public domain (https://sqlite.org/copyright.html) |

**Updating it:** download the new `sqlite-dll-win-x64-<n>.zip` from https://sqlite.org/download.html, check its SHA3-256
against the one printed there (`python -c "import hashlib,sys; print(hashlib.sha3_256(open(sys.argv[1],'rb').read()).hexdigest())" <zip>`),
put its `sqlite3.dll` here, and record the version, URL and both hashes in this file and the new sha256 in
`build_config.json`. 3.54.0 (2026-10-09) was three days old at this vendoring and was not taken.
