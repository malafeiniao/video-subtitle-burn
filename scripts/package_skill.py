#!/usr/bin/env python3
"""Create a clean, reproducible distributable without local media or fonts."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED


def main():
    root = Path(__file__).resolve().parents[1]
    allowed = {'SKILL.md', 'README.md', 'LICENSE'}
    folders = ('scripts', 'references', 'agents', 'examples')
    files = [root / name for name in allowed]
    for folder in folders:
        files += [p for p in (root / folder).rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and p.suffix in ('.py', '.md', '.yaml', '.srt', '.vtt', '.ass')]
    dest = root / 'dist' / 'video-subtitle-burn.zip'
    dest.parent.mkdir(exist_ok=True)
    with ZipFile(dest, 'w', compression=ZIP_DEFLATED) as archive:
        for file in sorted(files):
            info = ZipInfo('video-subtitle-burn/' + file.relative_to(root).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, file.read_bytes())
    print(dest)


if __name__ == '__main__':
    main()
