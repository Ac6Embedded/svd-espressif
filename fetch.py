#!/usr/bin/env python3
"""Fetch and organize Espressif CMSIS SVD files.

Sources:
  1. https://github.com/espressif/svd   (official, pristine)
  2. https://github.com/esp-rs/esp-pacs (community patched, gap fill only)

Incremental: every run first does a cheap metadata check (git ls-remote,
no artifact downloads) and compares each remote HEAD against the version
recorded in manifest.json. Unchanged sources are not re-cloned. If nothing
changed the script prints 'up to date' and touches no file. Deleting
manifest.json forces a full rebuild.

Run from anywhere: python fetch.py
Stdlib only. Needs git on PATH.
"""

import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".work"
# Family folders live directly at the repo root now, so the SVD output base
# is ROOT itself (was ROOT / "svd" before the flatten).
SVD_BASE = ROOT
LIC = ROOT / "LICENSES"
MANIFEST = ROOT / "manifest.json"

# Top-level entries that are never family output and must never be deleted by
# a full rebuild. Everything else at ROOT is a family dir we own.
PROTECTED = {".git", ".github", ".gitignore", ".work",
             "LICENSES", "README.md", "manifest.json", "fetch.py"}

ESPRESSIF_SVD_URL = "https://github.com/espressif/svd"
ESP_PACS_URL = "https://github.com/esp-rs/esp-pacs"

SRC_ESP = "espressif/svd"
SRC_PACS = "esp-rs/esp-pacs"


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("FAILED: %s\n%s" % (" ".join(cmd), r.stderr))
    return r.stdout.strip()


def ls_remote_head(url):
    """Metadata-only check: SHA of the remote HEAD, nothing downloaded."""
    out = run(["git", "ls-remote", url, "HEAD"])
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "HEAD":
            return parts[0]
    sys.exit("FAILED: cannot parse ls-remote output for %s:\n%s" % (url, out))


def clone(url, dest):
    if dest.exists():
        shutil.rmtree(dest, onerror=_rm_ro)
    print("DOWNLOAD: cloning %s" % url)
    run(["git", "clone", "--depth", "1", url, str(dest)])
    return run(["git", "rev-parse", "HEAD"], cwd=dest)


def _rm_ro(func, path, _exc):
    # git object files are read-only on Windows
    import os, stat
    os.chmod(path, stat.S_IWRITE)
    func(path)


def clean_family_dirs():
    """Full-rebuild reset: delete only family dirs, never protected entries.

    The output base is ROOT now, so a blanket rmtree(SVD_BASE) would wipe the
    whole repo including .git. Only remove top-level dirs we own.
    """
    for child in ROOT.iterdir():
        if child.is_dir() and child.name not in PROTECTED:
            shutil.rmtree(child, onerror=_rm_ro)


def iter_family_svds():
    """Yield every .svd file under a family dir, skipping protected entries
    (notably .work, which holds the source clones during a rebuild)."""
    for child in sorted(SVD_BASE.iterdir()):
        if child.is_dir() and child.name not in PROTECTED:
            yield from sorted(child.rglob("*.svd"))


def norm_chip(stem):
    return stem.lower().replace("-", "").replace("_", "")


def family_of(stem):
    # uppercase, no dashes: esp32s3 -> ESP32S3, esp32s2ulp -> ESP32S2ULP
    return stem.upper().replace("-", "").replace("_", "")


def validate(path):
    """Return None if well-formed with root 'device', else error string."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        return "XML parse error: %s" % e
    tag = root.tag.split("}")[-1]
    if tag != "device":
        return "root element is '%s', expected 'device'" % tag
    return None


def load_manifest():
    if not MANIFEST.is_file():
        return None
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def source_entry(manifest, name):
    for s in manifest.get("sources", []):
        if s.get("name") == name:
            return s
    return None


def source_files(manifest, name):
    return [m for m in manifest.get("files", []) if m.get("source") == name]


def files_intact(manifest, name):
    return all((ROOT / m["path"]).is_file() for m in source_files(manifest, name))


def remove_source_files(manifest, name):
    for m in source_files(manifest, name):
        p = ROOT / m["path"]
        if p.is_file():
            p.unlink()


def build_espressif(esp_dir, issues):
    """Copy svd/*.svd from the official repo. Returns (files, covered)."""
    files = []
    covered = set()  # chip stems provided by the official repo
    for f in sorted((esp_dir / "svd").glob("*.svd")):
        err = validate(f)
        if err:
            issues.append("skipped espressif/svd %s: %s" % (f.name, err))
            continue
        fam = family_of(f.stem)
        covered.add(norm_chip(f.stem))
        dest = SVD_BASE / fam / (f.stem + ".svd")
        dest.parent.mkdir(exist_ok=True)
        shutil.copy2(f, dest)
        files.append({
            "path": dest.relative_to(ROOT).as_posix(),
            "device": f.stem,
            "family": fam,
            "source": SRC_ESP,
            "provenance": "pristine",
        })
    print("copied %d files from espressif/svd" % len(files))

    lic_src = esp_dir / "LICENSE"
    if lic_src.exists():
        shutil.copy2(lic_src, LIC / "espressif-svd-LICENSE.txt")
    else:
        issues.append("espressif/svd: LICENSE file not found in repo")
    return files, covered


def build_pacs(pacs_dir, covered, issues):
    """Gap fill: copy SVDs only for chips absent from espressif/svd."""
    files = []
    for chip_dir in sorted(pacs_dir.iterdir()):
        if not chip_dir.is_dir() or not re.fullmatch(r"esp32[a-z0-9-]*", chip_dir.name):
            continue
        if norm_chip(chip_dir.name) in covered:
            continue
        # committed file is <chip>.base.svd; a patched variant would win if present
        cands = sorted((chip_dir / "svd").glob("*.svd*")) if (chip_dir / "svd").is_dir() else []
        cands += sorted(chip_dir.glob("*.svd*"))
        if not cands:
            issues.append("esp-pacs %s: no svd file found, chip not covered" % chip_dir.name)
            continue
        cands.sort(key=lambda p: ("patched" not in p.name, len(p.name)))
        src = cands[0]
        err = validate(src)
        if err:
            issues.append("skipped esp-pacs %s (%s): %s" % (chip_dir.name, src.name, err))
            continue
        fam = family_of(chip_dir.name)
        dest = SVD_BASE / fam / (chip_dir.name + ".svd")
        dest.parent.mkdir(exist_ok=True)
        shutil.copy2(src, dest)
        files.append({
            "path": dest.relative_to(ROOT).as_posix(),
            "device": chip_dir.name,
            "family": fam,
            "source": SRC_PACS,
            # the repo commits only the unpatched <chip>.base.svd (its yaml
            # patches are applied at PAC build time), so this is a vendor base
            # file redistributed by a community repo, not a patched file
            "provenance": "community",
        })
        print("gap fill from esp-pacs: %s (%s)" % (chip_dir.name, src.name))
    print("copied %d files from esp-rs/esp-pacs" % len(files))

    for name in ("LICENSE-APACHE", "LICENSE-MIT"):
        src = pacs_dir / name
        if src.exists():
            shutil.copy2(src, LIC / ("esp-pacs-%s.txt" % name))
        else:
            issues.append("esp-pacs: %s not found in repo" % name)
    return files


def main():
    manifest = load_manifest()
    full = manifest is None

    # ---- cheap metadata check, no artifact downloads ----
    print("checking upstream (metadata only)")
    esp_remote = ls_remote_head(ESPRESSIF_SVD_URL)
    pacs_remote = ls_remote_head(ESP_PACS_URL)

    if full:
        need_esp = need_pacs = True
    else:
        esp_src = source_entry(manifest, SRC_ESP)
        pacs_src = source_entry(manifest, SRC_PACS)
        need_esp = (esp_src is None
                    or esp_src.get("version") != esp_remote
                    or not files_intact(manifest, SRC_ESP))
        need_pacs = (pacs_src is None
                     or pacs_src.get("version") != pacs_remote
                     or not files_intact(manifest, SRC_PACS))

    if not need_esp and not need_pacs:
        print("espressif/svd    unchanged at %s" % esp_remote)
        print("esp-rs/esp-pacs  unchanged at %s" % pacs_remote)
        print("up to date")
        return

    # ---- rebuild only what changed ----
    if full:
        clean_family_dirs()  # no trusted manifest, start from scratch
    WORK.mkdir(exist_ok=True)
    SVD_BASE.mkdir(exist_ok=True)
    LIC.mkdir(exist_ok=True)

    issues = []
    old_esp_files = [] if manifest is None else source_files(manifest, SRC_ESP)
    old_pacs_files = [] if manifest is None else source_files(manifest, SRC_PACS)

    # ---- source 1: espressif/svd (pristine) ----
    if need_esp:
        esp_dir = WORK / "espressif-svd"
        esp_sha = clone(ESPRESSIF_SVD_URL, esp_dir)
        print("espressif/svd HEAD:", esp_sha)
        remove_source_files(manifest or {}, SRC_ESP)
        esp_files, covered = build_espressif(esp_dir, issues)
        # if official coverage shrank, esp-pacs may have new gaps to fill
        old_covered = {norm_chip(m["device"]) for m in old_esp_files}
        if old_covered - covered and not need_pacs:
            print("espressif/svd coverage shrank, rebuilding esp-rs/esp-pacs too")
            need_pacs = True
    else:
        esp_sha = esp_remote
        esp_files = old_esp_files
        covered = {norm_chip(m["device"]) for m in esp_files}
        print("espressif/svd unchanged, keeping %d files" % len(esp_files))

    # ---- source 2: esp-rs/esp-pacs (patched, gap fill only) ----
    if need_pacs:
        pacs_dir = WORK / "esp-pacs"
        pacs_sha = clone(ESP_PACS_URL, pacs_dir)
        print("esp-rs/esp-pacs HEAD:", pacs_sha)
        remove_source_files(manifest or {}, SRC_PACS)
        pacs_files = build_pacs(pacs_dir, covered, issues)
    else:
        pacs_sha = pacs_remote
        # chips the official repo now covers are no longer gap fill
        esp_paths = {m["path"] for m in esp_files}
        pacs_files = []
        for m in old_pacs_files:
            if norm_chip(m["device"]) in covered:
                p = ROOT / m["path"]
                if m["path"] not in esp_paths and p.is_file():
                    p.unlink()
                print("dropped esp-pacs gap fill, now official: %s" % m["device"])
            else:
                pacs_files.append(m)
        print("esp-rs/esp-pacs unchanged, keeping %d files" % len(pacs_files))

    manifest_files = esp_files + pacs_files

    # prune family dirs left empty by removals (never touch protected entries)
    for d in sorted(SVD_BASE.iterdir()):
        if d.is_dir() and d.name not in PROTECTED and not any(d.iterdir()):
            d.rmdir()

    # ---- final validation pass over the output tree ----
    total_bytes = 0
    for f in iter_family_svds():
        err = validate(f)
        if err:
            issues.append("removed %s: %s" % (f.relative_to(ROOT).as_posix(), err))
            rel = f.relative_to(ROOT).as_posix()
            manifest_files = [m for m in manifest_files if m["path"] != rel]
            f.unlink()
        else:
            total_bytes += f.stat().st_size

    n1 = len([m for m in manifest_files if m["source"] == SRC_ESP])
    n2 = len([m for m in manifest_files if m["source"] == SRC_PACS])

    out_manifest = {
        "vendor": "Espressif",
        "generated": date.today().isoformat(),
        "sources": [
            {
                "name": SRC_ESP,
                "url": ESPRESSIF_SVD_URL,
                "version": esp_sha,
                "license": "Apache-2.0",
                "files": n1,
            },
            {
                "name": SRC_PACS,
                "url": ESP_PACS_URL,
                "version": pacs_sha,
                "license": "MIT OR Apache-2.0",
                "files": n2,
            },
        ],
        "files": sorted(manifest_files, key=lambda m: m["path"]),
        "stats": {
            "total_files": len(manifest_files),
            "total_bytes": total_bytes,
        },
    }
    if issues:
        out_manifest["issues"] = issues
    MANIFEST.write_text(json.dumps(out_manifest, indent=2) + "\n", encoding="utf-8")

    print("total: %d files, %.1f MB" % (len(manifest_files), total_bytes / 1e6))
    for i in issues:
        print("ISSUE:", i)

    if "--keep-work" not in sys.argv and WORK.exists():
        shutil.rmtree(WORK, onerror=_rm_ro)
        print("removed .work/")


if __name__ == "__main__":
    main()
