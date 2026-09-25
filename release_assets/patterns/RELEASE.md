# Surasura's shared パターン data (Japanese)

`patterns_ja_shared.zip` is what the app downloads when a user presses **Get data… → Download** in the
Anki Backfill window. The app accepts **only this exact file**:

    https://github.com/SonicSandbox/surasura/releases/download/patterns-ja-1/patterns_ja_shared.zip
    sha256 0d7146aa97d02409c552c3e44f7d97d221d0680713f057095c7276274102c985   (26.8 MB)

Made from RealPersonaChat, Aozora Bunko and Japanese Wikipedia — CC BY-SA 4.0, credits in
`CREDITS.txt` (also inside the zip). This folder is not part of the app build.

## Publish it (once, before the app release that has "Get data…")

It must be a **pre-release**: the app's update check reads the repository's latest release, which skips
pre-releases — a normal release here would look like a new app version. From the repository root:

```
gh release create patterns-ja-1 "release_assets/patterns/patterns_ja_shared.zip" --prerelease --title "パターン data (ja) 1" --notes "Surasura's shared パターン data, downloaded by the app (Anki Backfill → Get data…). Made from RealPersonaChat, Aozora Bunko and Japanese Wikipedia — CC BY-SA 4.0; CREDITS.txt inside. sha256 0d7146aa97d02409c552c3e44f7d97d221d0680713f057095c7276274102c985"
```

Check: open the release page, download the zip, and compare its sha256
(`certutil -hashfile patterns_ja_shared.zip SHA256`) with the one above.

## A new version of the data

1. `python docs/assets/corpora/build_shared.py` — it writes the new zip here and prints its
   `zip_sha256`.
2. Put that hash in `modules/junban/patterns_package.py` (`SHARED_SHA256`), and a new tag in
   `SHARED_URL` (`patterns-ja-2`), so older apps keep the file they were pinned to.
3. Publish the new zip under the new tag as above, then ship the app release that carries the new pin.
