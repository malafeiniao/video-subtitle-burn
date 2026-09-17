#!/usr/bin/env python3
"""Portable, local subtitle burning. Python 3.10+, FFmpeg/libass/libx264."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

from font_layout import FontWidths, wrap


class SubtitleError(ValueError):
    pass


@dataclass(frozen=True)
class Cue:
    start: int
    end: int
    text: str


def run(argv, **kwargs):
    if kwargs.get('text'):
        kwargs.setdefault('encoding', 'utf-8')
        kwargs.setdefault('errors', 'replace')
    result = subprocess.run([str(a) for a in argv], stdin=subprocess.DEVNULL,
                            capture_output=True, **kwargs)
    if result.returncode:
        stderr = result.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode('utf-8', errors='replace')
        raise SubtitleError(f'{Path(str(argv[0])).name} failed ({result.returncode}):\n{stderr[-6000:]}')
    return result


def executable(value, name):
    candidate = value or os.environ.get('SUBTITLE_' + name.upper()) or name
    found = shutil.which(candidate)
    if not found:
        raise SubtitleError(f'{name} not found: {candidate}. See references/setup.md.')
    return str(Path(found).resolve())


def tools(args):
    ff = executable(args.ffmpeg, 'ffmpeg')
    adjacent = Path(ff).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    fp = executable(args.ffprobe or os.environ.get('SUBTITLE_FFPROBE') or
                    (str(adjacent) if adjacent.is_file() else None), 'ffprobe')
    filters = run([ff, '-hide_banner', '-filters'], text=True).stdout
    encoders = run([ff, '-hide_banner', '-encoders'], text=True).stdout
    if not re.search(r'^\s*\S+\s+ass\s', filters, re.M):
        raise SubtitleError('FFmpeg has no ass filter (libass). See references/setup.md.')
    if not re.search(r'^\s*\S+\s+libx264\s', encoders, re.M):
        raise SubtitleError('FFmpeg has no libx264 encoder.')
    run([fp, '-version'])
    return ff, fp


def timestamp(value):
    match = re.fullmatch(r'(?:(\d{2,}):)?(\d{2}):(\d{2})[.,](\d{3})', value)
    if not match:
        raise SubtitleError(f'Invalid timestamp: {value}')
    hours, minutes, seconds, millis = (int(x or 0) for x in match.groups())
    if minutes >= 60 or seconds >= 60:
        raise SubtitleError(f'Invalid timestamp: {value}')
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_subtitles(path):
    path = Path(path)
    if path.suffix.lower() not in ('.srt', '.vtt'):
        raise SubtitleError('Text subtitles must be UTF-8 SRT or basic WebVTT.')
    raw = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n[ \t]*\n', raw.strip())
    vtt = path.suffix.lower() == '.vtt'
    if vtt:
        if not blocks or not blocks[0].startswith('WEBVTT'):
            raise SubtitleError('VTT must start with WEBVTT.')
        header = blocks.pop(0).splitlines()
        if len(header) > 1:
            raise SubtitleError('VTT metadata/timestamp maps are not supported; convert to ASS first.')
    cues = []
    for block in blocks:
        lines = block.splitlines()
        if vtt and re.match(r'^NOTE(?:\s|$)', lines[0]):
            continue
        if vtt and lines[0] in ('STYLE', 'REGION'):
            raise SubtitleError('Styled/positioned VTT requires conversion to ASS; it will not be flattened silently.')
        time_index = 0 if '-->' in lines[0] else 1
        if len(lines) <= time_index + 1:
            raise SubtitleError(f'Missing timing/text near block {len(cues) + 1}.')
        if time_index and not vtt and not lines[0].strip().isdigit():
            raise SubtitleError('SRT cue identifiers must be numeric.')
        pieces = re.fullmatch(r'\s*(\S+)\s+-->\s+(\S+)\s*', lines[time_index])
        if not pieces:
            raise SubtitleError('Malformed timing or VTT position settings; use ASS for positioned subtitles.')
        start, end = map(timestamp, pieces.groups())
        text = '\n'.join(lines[time_index + 1:])
        if start >= end or not text.strip():
            raise SubtitleError(f'Cue {len(cues) + 1} is empty or has non-positive duration.')
        if cues and start < cues[-1].end:
            raise SubtitleError(f'Cue {len(cues) + 1} overlaps or is out of order. Resolve explicitly, or use authored ASS.')
        if (end + 5) // 10 <= (start + 5) // 10:
            raise SubtitleError(f'Cue {len(cues) + 1} vanishes at ASS centisecond precision.')
        cues.append(Cue(start, end, text))
    if not cues:
        raise SubtitleError('No subtitle cues found.')
    return cues


def ass_text(value):
    """Preserve text and supported emphasis; never interpret user ASS escapes."""
    parts = re.split(r'(<[^>]+>)', value)
    output, stack = [], []
    for part in parts:
        if re.fullmatch(r'</?[ibu]>', part, re.I):
            tag = part.strip('</>').lower()
            closing = part.startswith('</')
            if closing:
                if not stack or stack.pop() != tag:
                    raise SubtitleError('Unbalanced subtitle emphasis tags.')
            else:
                if tag in stack:
                    raise SubtitleError('Nested duplicate emphasis tags are not supported; use ASS.')
                stack.append(tag)
            output.append('{' + '\\' + tag + ('0' if closing else '1') + '}')
        elif part.startswith('<') and part.endswith('>'):
            raise SubtitleError(f'Unsupported subtitle markup {part!r}; use ASS to retain styling.')
        else:
            part = html.unescape(part)
            # libass uses backslash/braces as syntax. Reject ambiguity rather than alter approved text.
            if any(c in part for c in ('\\', '{', '}')):
                raise SubtitleError('Literal backslashes/braces require an explicitly authored ASS file.')
            if any(ord(c) < 32 and c not in '\n\t' for c in part):
                raise SubtitleError('Unsupported control character in subtitle.')
            output.append(part.replace('\n', '\\N').replace('\t', '    '))
    if stack:
        raise SubtitleError('Unclosed subtitle emphasis tag.')
    return ''.join(output)


def font_info(path):
    """Read family and libass size normalization from a standalone SFNT TTF/OTF."""
    data = Path(path).read_bytes()
    if data[:4] not in (b'OTTO', b'\x00\x01\x00\x00', b'true'):
        raise SubtitleError('Use a standalone static .ttf/.otf font, not TTC/WOFF.')
    u16 = lambda offset: struct.unpack_from('>H', data, offset)[0]
    tables = {}
    for i in range(u16(4)):
        tag, _, offset, length = struct.unpack_from('>4sIII', data, 12 + 16 * i)
        tables[tag] = (offset, length)
    if b'fvar' in tables:
        raise SubtitleError('Use a static font instance instead of a variable font.')
    head, hhea, name = (tables[tag][0] for tag in (b'head', b'hhea', b'name'))
    asc, desc = struct.unpack_from('>hh', data, hhea + 4)
    upem = u16(head + 18)
    if not upem:
        raise SubtitleError('Invalid font unitsPerEm.')
    factor = (asc - desc) / upem
    candidates = []
    for i in range(u16(name + 2)):
        platform, encoding, lang, name_id, length, offset = struct.unpack_from('>6H', data, name + 6 + i * 12)
        if name_id != 1:
            continue
        blob = data[name + u16(name + 4) + offset:name + u16(name + 4) + offset + length]
        try:
            value = blob.decode('utf-16-be' if platform in (0, 3) else 'mac_roman')
        except UnicodeError:
            continue
        candidates.append((int(platform == 3 and lang == 0x409), value))
    if not candidates or not math.isfinite(factor) or factor <= 0:
        raise SubtitleError('Cannot read font family/metrics; choose a valid static font.')
    family = max(candidates)[1]
    if any(c in family for c in ',\r\n{}\\'):
        raise SubtitleError('Font family contains unsupported ASS syntax.')
    return family, factor


def ass_time(ms):
    cs = (ms + 5) // 10
    return f'{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}'


def color(value):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise SubtitleError('Colors must use #RRGGBB.')
    return '&H00' + value[5:7] + value[3:5] + value[1:3]


def make_ass(cues, secondary, width, height, family, metric, style, widths=None):
    if secondary is not None:
        if len(cues) != len(secondary):
            raise SubtitleError(f'Bilingual cue counts differ: {len(cues)} vs {len(secondary)}. Align the subtitles first.')
        for index, (a, b) in enumerate(zip(cues, secondary), 1):
            if (a.start, a.end) != (b.start, b.end):
                raise SubtitleError(f'Bilingual cue {index} differs: {a.start}–{a.end} ms vs {b.start}–{b.end} ms. Boundaries must match exactly.')
    fs = height * style.font_size / 100 * metric
    second_fs = height * style.secondary_size / 100 * metric
    margin = round(width * style.margin / 100)
    bottom = round(height * style.bottom / 100)
    outline = height * style.outline / 100
    alignment = 8 if style.position == 'top' else 2
    lines = [
        '[Script Info]', 'ScriptType: v4.00+', f'PlayResX: {width}', f'PlayResY: {height}',
        f'WrapStyle: {2 if style.no_wrap else 0}', 'ScaledBorderAndShadow: yes', '', '[V4+ Styles]',
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
        f'Style: Default,{family},{fs:.3f},{color(style.color)},&H000000FF,{color(style.outline_color)},&H80000000,0,0,0,0,100,100,0,0,1,{outline:.3f},0,{alignment},{margin},{margin},{bottom},1',
        '', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
    ]
    for i, cue in enumerate(cues):
        text = ass_text(cue.text)
        if widths is not None and not style.no_wrap:
            text = wrap(text, widths, height * style.font_size / 100, width - margin * 2)
        estimated_height = (text.count('\\N') + 1) * fs
        if secondary is not None:
            second = ass_text(secondary[i].text)
            if widths is not None and not style.no_wrap:
                second = wrap(second, widths, height * style.secondary_size / 100, width - margin * 2)
            estimated_height += (second.count('\\N') + 1) * second_fs
            text += '\\N{\\rDefault\\fs' + f'{second_fs:.3f}' + '}' + second
        if estimated_height > height - bottom * 2:
            raise SubtitleError(f'Cue {i + 1} has too many display lines. Reduce font size or provide revised subtitles.')
        lines.append(f'Dialogue: 0,{ass_time(cue.start)},{ass_time(cue.end)},Default,,0,0,0,,{text}')
    return '\n'.join(lines) + '\n'


def probe(fp, video):
    data = json.loads(run([fp, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', video], text=True).stdout)
    videos = [s for s in data['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if not videos:
        raise SubtitleError('No video stream found.')
    stream = videos[0]
    if stream.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
        raise SubtitleError('HDR needs an explicit tone-mapping/HDR workflow; this SDR preset will not silently convert it.')
    duration = float(stream.get('duration') or data['format'].get('duration') or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise SubtitleError('Cannot determine a finite positive video duration.')
    return data, stream, duration


NORMALIZE = 'scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1'


def display_size(ff, video, stream_index):
    # Probe actual decoded/autorotated square-pixel geometry, rather than guess rotation/SAR.
    png = run([ff, '-v', 'error', '-i', video, '-map', f'0:{stream_index}', '-vf', NORMALIZE,
               '-frames:v', '1', '-c:v', 'png', '-f', 'image2pipe', '-']).stdout
    if png[:8] != b'\x89PNG\r\n\x1a\n':
        raise SubtitleError('Failed to inspect decoded video dimensions.')
    return struct.unpack('>II', png[16:24])


def verify_media(ff, fp, video, stream, duration):
    # Decode errors alone do not detect clean early EOF. Scan video packet coverage too.
    packet_args = [fp, '-v', 'error', '-select_streams', str(stream['index']), '-show_packets',
                   '-show_entries', 'packet=pts_time,duration_time', '-of', 'csv=p=0', video]
    latest, earliest = None, None
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(packet_args, stdout=subprocess.PIPE, stderr=errors,
                                   stdin=subprocess.DEVNULL, text=True, encoding='utf-8')
        for line in process.stdout:
            fields = line.strip().split(',')
            try:
                pts = float(fields[0])
                length = float(fields[1]) if len(fields) > 1 and fields[1] != 'N/A' else 0
            except ValueError:
                continue
            if math.isfinite(pts) and math.isfinite(length):
                earliest = pts if earliest is None else min(earliest, pts)
                latest = pts + length if latest is None else max(latest, pts + length)
        process.stdout.close()
        code = process.wait()
        errors.seek(0)
        message = errors.read().decode('utf-8', errors='replace')
        if code or message.strip():
            raise SubtitleError('Media packet scan failed: ' + message[-2000:])
    if latest is None or duration - (latest - earliest) > max(0.5, duration * 0.001):
        raise SubtitleError('Video packet coverage ends before declared duration; check the source download.')
    run([ff, '-v', 'error', '-xerror', '-err_detect', 'explode', '-i', video,
         '-map', f'0:{stream["index"]}', '-map', '0:a?', '-f', 'null', '-'])


def validate_ass(path):
    text = Path(path).read_text(encoding='utf-8-sig')
    if not all(section in text for section in ('[Script Info]', '[V4+ Styles]', '[Events]')):
        raise SubtitleError('Expected an Advanced SubStation Alpha (.ass) file with styles and events.')
    events = re.findall(r'^Dialogue:.*$', text, re.M)
    if not events:
        raise SubtitleError('ASS contains no dialogue events.')
    # Preserve layout, overlaps, drawings and text; normalize encoding/newlines only.
    return text, len(events)


def burn(args):
    ff, fp = tools(args)
    video, subtitle, output = map(lambda p: Path(p).expanduser().resolve(), (args.video, args.subtitles, args.output))
    if output.suffix.lower() != '.mp4':
        raise SubtitleError('This delivery preset outputs .mp4 (H.264 + AAC/copy).')
    if not video.is_file() or not subtitle.is_file():
        raise SubtitleError('Video/subtitle input does not exist.')
    fonts = [Path(p).expanduser().resolve() for p in args.font]
    if not fonts:
        raise SubtitleError('Provide at least one --font /path/to/font.ttf (or .otf) for reproducible rendering.')
    family, metric = font_info(fonts[0])
    for font in fonts[1:]:
        font_info(font)
    sources = [video, subtitle, *fonts]
    secondary_path = Path(args.secondary).expanduser().resolve() if args.secondary else None
    if secondary_path:
        sources.append(secondary_path)
    artifacts = [output, output.with_suffix('.ass'), output.with_suffix('.report.json'), output.with_suffix('.ffmpeg.log')]
    for path in artifacts:
        if path in sources:
            raise SubtitleError(f'Output would overwrite input: {path}')
        if path.exists() and not args.overwrite and not args.check:
            raise SubtitleError(f'Output exists: {path}. Choose another name or explicitly use --overwrite.')
    data, stream, duration = probe(fp, video)
    width, height = display_size(ff, video, stream['index'])
    warnings = []
    if subtitle.suffix.lower() == '.ass':
        if args.secondary:
            raise SubtitleError('For bilingual ASS, author both languages in the ASS input.')
        ass, count = validate_ass(subtitle)
        warnings.append('ASS preserved: caller must inspect authored timing, placement, font coverage and overlaps.')
    else:
        cues = parse_subtitles(subtitle)
        secondary = parse_subtitles(secondary_path) if secondary_path else None
        if cues[-1].end > duration * 1000 + 100:
            raise SubtitleError('Subtitles extend beyond the video duration; check the input/time base.')
        ass = make_ass(cues, secondary, width, height, family, metric, args, FontWidths(fonts[0]))
        count = len(cues)
        warnings.append('SRT/VTT timing is rounded to ASS centiseconds (at most 5 ms); text and punctuation are retained.')
        if args.no_wrap:
            warnings.append('Automatic wrapping disabled: inspect every long cue for clipping.')
        else:
            warnings.append('Font-advance wrapping adds display line breaks without retiming; libass shapes text. Inspect long cues, fallback fonts and complex scripts visually.')
    if args.start < 0 or args.start >= duration:
        raise SubtitleError('--start must fall within the video.')
    if args.start and args.preview is None:
        raise SubtitleError('--start requires --preview; full delivery always starts at zero.')
    if args.preview is not None and args.preview <= 0:
        raise SubtitleError('--preview must be a positive duration.')
    render_duration = min(args.preview, duration - args.start) if args.preview is not None else duration
    if args.verify_media:
        verify_media(ff, fp, video, stream, duration)
    report = dict(video=str(video), subtitles=str(subtitle), secondary=str(secondary_path) if secondary_path else None,
                  output=str(output), dimensions=[width, height], source_duration=duration,
                  render_start=args.start, render_duration=render_duration, cue_count=count,
                  font_family=family, media_verified=args.verify_media, warnings=warnings)
    if args.check:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.subtitle-', dir=output.parent) as temp:
        stage = Path(temp)
        (stage / 'captions.ass').write_text(ass, encoding='utf-8')
        (stage / 'fonts').mkdir()
        for i, font in enumerate(fonts):
            shutil.copyfile(font, stage / 'fonts' / f'{i}{font.suffix.lower()}')
        # Only fixed relative names enter the filter grammar. All user paths are argv entries.
        command = [ff, '-hide_banner', '-nostdin', '-v', 'info', '-xerror', '-i', str(video),
                   '-map', f'0:{stream["index"]}', '-map', '0:a?', '-sn', '-dn',
                   '-vf', NORMALIZE + ',ass=filename=captions.ass:fontsdir=fonts',
                   '-c:v', 'libx264', '-preset', args.preset, '-crf', str(args.crf), '-pix_fmt', 'yuv420p',
                   '-c:a', args.audio, '-movflags', '+faststart']
        if args.audio == 'aac':
            command += ['-b:a', '192k']
        if args.preview is not None:
            command += ['-ss', str(args.start)]
        command += ['-t', str(render_duration), '-y', 'render.mp4']
        with (stage / 'render.log').open('w', encoding='utf-8') as log:
            result = subprocess.run(command, cwd=stage, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, text=True)
        log_text = (stage / 'render.log').read_text(encoding='utf-8', errors='replace')
        if result.returncode:
            raise SubtitleError('Render failed (no final video replaced):\n' + log_text[-6000:])
        if re.search(r'fontselect: failed to find any fallback|failed to find.*glyph', log_text, re.I):
            raise SubtitleError('Font glyphs missing. Supply covering fallback fonts with additional --font arguments.')
        _, rendered_stream, actual_duration = probe(fp, stage / 'render.mp4')
        if abs(actual_duration - render_duration) > max(0.25, render_duration * 0.002):
            raise SubtitleError(f'Output duration mismatch: expected {render_duration:.3f}, got {actual_duration:.3f}.')
        report['actual_duration'] = actual_duration
        report['bytes'] = (stage / 'render.mp4').stat().st_size
        report['ffmpeg_version'] = run([ff, '-version'], text=True).stdout.splitlines()[0]
        report['font_selection'] = [line for line in log_text.splitlines() if 'fontselect:' in line]
        (stage / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        staged = [stage / 'render.mp4', stage / 'captions.ass', stage / 'report.json', stage / 'render.log']
        # Reserve names before publication so an unexpected existing file cannot be replaced by default.
        reserved = []
        try:
            if not args.overwrite:
                for dst in artifacts:
                    with dst.open('xb'):
                        pass
                    reserved.append(dst)
            for src, dst in zip(staged, artifacts):
                os.replace(src, dst)
                if dst in reserved:
                    reserved.remove(dst)
        finally:
            for dst in reserved:
                dst.unlink(missing_ok=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ffmpeg', help='Executable path; alternatively SUBTITLE_FFMPEG')
    p.add_argument('--ffprobe', help='Executable path; alternatively SUBTITLE_FFPROBE')
    p.add_argument('--doctor', action='store_true', help='Check FFmpeg/FFprobe capabilities and exit')
    p.add_argument('--video')
    p.add_argument('--subtitles', help='UTF-8 .srt, basic .vtt, or authored .ass')
    p.add_argument('--secondary', help='Second SRT/VTT with exactly matching cue times; shown below primary')
    p.add_argument('--output', help='Destination .mp4; sidecar ASS, report and log are also produced')
    p.add_argument('--font', action='append', default=[], help='Static .ttf/.otf; repeat for fallback fonts')
    p.add_argument('--font-size', type=float, default=3.8, help='Primary em height as %% of frame height (default 3.8)')
    p.add_argument('--secondary-size', type=float, default=2.8, help='Secondary em height %% (default 2.8)')
    p.add_argument('--margin', type=float, default=4.7, help='Left/right margin %% of frame width')
    p.add_argument('--bottom', type=float, default=5.8, help='Vertical margin %% of frame height; also applies to top placement')
    p.add_argument('--outline', type=float, default=0.22, help='Outline %% of frame height')
    p.add_argument('--color', default='#FFFFFF')
    p.add_argument('--outline-color', default='#000000')
    p.add_argument('--position', choices=['top', 'bottom'], default='bottom')
    p.add_argument('--no-wrap', action='store_true', help='Honor explicit line breaks only; inspect clipping')
    p.add_argument('--crf', type=int, default=20, help='x264 CRF, 0–51; lower is larger/higher quality')
    p.add_argument('--preset', choices=['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'], default='medium')
    p.add_argument('--audio', choices=['aac', 'copy'], default='aac', help='AAC for MP4 compatibility; copy only if compatible')
    p.add_argument('--preview', type=float, help='Render only this many seconds')
    p.add_argument('--start', type=float, default=0, help='Preview start in seconds; applied AFTER subtitle rendering')
    p.add_argument('--check', action='store_true', help='Validate inputs and show a report without writing outputs')
    p.add_argument('--verify-media', action='store_true', help='Full packet coverage and audio/video decode check (can be slow)')
    p.add_argument('--overwrite', action='store_true', help='Explicitly permit replacing destination artifacts')
    return p


def main():
    # A redirected Windows console may otherwise choose a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    p = parser()
    args = p.parse_args()
    try:
        if args.doctor:
            ff, fp = tools(args)
            print(json.dumps(dict(ffmpeg=ff, ffprobe=fp, ass=True, libx264=True), indent=2))
            return 0
        if not all((args.video, args.subtitles, args.output)):
            p.error('--video, --subtitles and --output are required unless using --doctor')
        for key in ('font_size', 'secondary_size', 'margin', 'bottom', 'outline', 'start', 'preview'):
            value = getattr(args, key)
            if value is not None and not math.isfinite(value):
                raise SubtitleError(f'--{key.replace("_", "-")} must be finite.')
        if not (0 <= args.crf <= 51 and 0 < args.font_size <= 30 and 0 < args.secondary_size <= 30
                and 0 <= args.margin < 45 and 0 <= args.bottom < 45 and 0 <= args.outline <= 5):
            raise SubtitleError('Style/CRF values are outside supported bounds; see --help.')
        burn(args)
        return 0
    except (ValueError, OSError, UnicodeError, KeyError, struct.error) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
