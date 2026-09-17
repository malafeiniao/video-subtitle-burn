"""Static SFNT advances and conservative line wrapping, using the standard library.

libass remains the shaping/rendering authority. Widths here are an advance-width
estimate (not a substitute for visual QA), but avoid missing CJK break opportunities
in libass builds that do not enable Unicode wrapping for native ASS input.
"""
from pathlib import Path
import re
import struct
import unicodedata


class FontWidths:
    def __init__(self, path):
        data = Path(path).read_bytes()
        u16 = lambda n: struct.unpack_from('>H', data, n)[0]
        u32 = lambda n: struct.unpack_from('>I', data, n)[0]
        tables = {}
        for i in range(u16(4)):
            tag, _, offset, _ = struct.unpack_from('>4sIII', data, 12 + i * 16)
            tables[tag] = offset
        self.upem = u16(tables[b'head'] + 18)
        self.advances = [u16(tables[b'hmtx'] + i * 4) for i in range(u16(tables[b'hhea'] + 34))]
        cmap = tables[b'cmap']
        candidates = []
        for i in range(u16(cmap + 2)):
            base = cmap + 4 + i * 8
            platform, encoding, offset = struct.unpack_from('>HHI', data, base)
            sub = cmap + offset
            fmt = u16(sub)
            if (platform == 0 or (platform == 3 and encoding in (1, 10))) and fmt in (4, 12):
                candidates.append((fmt, sub))
        if not candidates:
            raise ValueError('Font has no supported Unicode cmap (format 4 or 12).')
        fmt, sub = max(candidates)
        self.glyphs = {}
        if fmt == 12:
            for i in range(u32(sub + 12)):
                start, end, first = struct.unpack_from('>III', data, sub + 16 + i * 12)
                if end > 0x10FFFF or end < start:
                    raise ValueError('Invalid font cmap range.')
                for cp in range(start, end + 1):
                    self.glyphs[cp] = first + cp - start
        else:
            count = u16(sub + 6) // 2
            ends = sub + 14
            starts = ends + 2 * count + 2
            deltas = starts + 2 * count
            ranges = deltas + 2 * count
            for i in range(count):
                start, end, delta, ro = (u16(base + 2 * i) for base in (starts, ends, deltas, ranges))
                for cp in range(start, end + 1):
                    glyph = u16(ranges + 2 * i + ro + 2 * (cp - start)) if ro else cp
                    if glyph or not ro:
                        self.glyphs[cp] = (glyph + delta) & 0xFFFF

    def width(self, text, em):
        units = 0
        for ch in text:
            if unicodedata.combining(ch) or unicodedata.category(ch) == 'Cf':
                continue
            glyph = self.glyphs.get(ord(ch), 0)
            units += (self.advances[min(glyph, len(self.advances) - 1)] if glyph else self.upem)
        return units / self.upem * em


def cjk(ch):
    cp = ord(ch)
    return (0x2E80 <= cp <= 0x9FFF or 0xAC00 <= cp <= 0xD7AF or
            0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x323AF or
            0xFF01 <= cp <= 0xFF60)


def tokens(text):
    """ASS emphasis tags have zero width; Latin words/URLs stay indivisible."""
    result = []
    for part in re.split(r'(\{[^}]*\})', text):
        if not part:
            continue
        if part.startswith('{'):
            result.append((part, ''))
            continue
        for ch in part:
            if (unicodedata.combining(ch) or unicodedata.category(ch) == 'Cf') and result:
                raw, visible = result.pop()
                result.append((raw + ch, visible + ch))
            elif ch in '，。！？、；：）》】」』’”' and result:
                raw, visible = result.pop()
                result.append((raw + ch, visible + ch))
            elif (not cjk(ch) and not ch.isspace() and result and result[-1][1]
                  and not cjk(result[-1][1][-1]) and not result[-1][1][-1].isspace()):
                raw, visible = result.pop()
                result.append((raw + ch, visible + ch))
            else:
                result.append((ch, ch))
    # Keep an opening CJK punctuation mark with the following character/token.
    joined = []
    for raw, visible in result:
        if joined and joined[-1][1] and joined[-1][1][-1] in '（《【「『“‘':
            prev, shown = joined.pop()
            joined.append((prev + raw, shown + visible))
        else:
            joined.append((raw, visible))
    return joined


def wrap(text, widths, em, usable):
    # Reserve extra room for outline, emphasis and shaping differences. Never split timing.
    limit = usable * 0.90
    paragraphs = []
    for paragraph in text.split('\\N'):
        parts = tokens(paragraph)
        lines, current, length = [], '', 0.0
        pending_space = ''
        for raw, visible in parts:
            if visible.isspace():
                pending_space += raw
                continue
            w = widths.width(visible, em)
            space_w = widths.width(pending_space, em)
            if w > limit:
                raise ValueError(f'An indivisible token is wider than the subtitle area: {visible[:60]!r}. Reduce font size or author ASS.')
            if length and length + space_w + w > limit:
                lines.append(current)
                current, length, pending_space = '', 0.0, ''
            current += pending_space + raw
            length += widths.width(pending_space, em) + w
            pending_space = ''
        lines.append(current + pending_space)
        paragraphs.append('\\N'.join(lines))
    return '\\N'.join(paragraphs)
