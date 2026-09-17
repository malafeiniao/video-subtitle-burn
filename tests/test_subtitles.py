import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import burn_subtitles as burn
from font_layout import FontWidths, wrap


class SubtitleTests(unittest.TestCase):
    def parse(self, text, suffix='.srt'):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ('caption' + suffix)
            path.write_text(text, encoding='utf-8')
            return burn.parse_subtitles(path)

    def test_bom_crlf_and_approved_punctuation(self):
        cues = self.parse('\ufeff1\r\n00:00:00,005 --> 00:00:01,005\r\n保留，标点！\r\nSecond line.\r\n')
        self.assertEqual(cues[0], burn.Cue(5, 1005, '保留，标点！\nSecond line.'))

    def test_webvtt_ids_comments_and_short_timestamp(self):
        cues = self.parse('WEBVTT\n\nNOTE ignore me\n\nintro\n00:00.500 --> 00:02.000\nHello &amp; goodbye.\n', '.vtt')
        self.assertEqual(cues[0].start, 500)
        self.assertEqual(burn.ass_text(cues[0].text), 'Hello & goodbye.')

    def test_timing_failures(self):
        for text in ('1\n00:00:02,000 --> 00:00:01,000\nWrong',
                     '1\n00:00:00,000 --> 00:00:02,000\nA\n\n2\n00:00:01,000 --> 00:00:03,000\nB',
                     '1\n00:00:00,001 --> 00:00:00,004\nTiny',
                     '1\n00:61:00,000 --> 00:62:00,000\nBad minute'):
            with self.subTest(text=text), self.assertRaises(burn.SubtitleError):
                self.parse(text)

    def test_vtt_layout_is_not_silently_lost(self):
        for text in ('WEBVTT\n\nSTYLE\n::cue { color: red; }',
                     'WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00.000,MPEGTS:100\n\n',
                     'WEBVTT\n\n00:00.000 --> 00:01.000 position:30%\nHello'):
            with self.subTest(text=text), self.assertRaises(burn.SubtitleError):
                self.parse(text, '.vtt')

    def test_ass_injection_and_unknown_tags_fail(self):
        for text in ('{\\pos(1,1)}secret', r'Hello\Nworld', '<font color="red">text</font>', '<b>unclosed'):
            with self.subTest(text=text), self.assertRaises(burn.SubtitleError):
                burn.ass_text(text)
        self.assertEqual(burn.ass_text('<i>Hello</i>\nworld'), r'{\i1}Hello{\i0}\Nworld')

    def test_bilingual_sync_and_unicode(self):
        args = burn.parser().parse_args([])
        primary = [burn.Cue(101, 1006, '你好。')]
        secondary = [burn.Cue(101, 1006, 'Hello.')]
        ass = burn.make_ass(primary, secondary, 640, 360, 'Test Font', 1.4, args)
        self.assertIn('PlayResX: 640', ass)
        self.assertIn('你好。\\N', ass)
        self.assertIn('Hello.', ass)
        with self.assertRaises(burn.SubtitleError):
            burn.make_ass(primary, [burn.Cue(102, 1006, 'Hello.')], 640, 360, 'Test Font', 1.4, args)

    def test_centisecond_rounding_keeps_adjacent_order(self):
        for ms in range(1, 1000):
            # Decode generated timestamp; each boundary differs from input by <= 5 ms.
            h, m, s = burn.ass_time(ms).split(':')
            actual = int(h) * 3600000 + int(m) * 60000 + round(float(s) * 1000)
            self.assertLessEqual(abs(ms - actual), 5)
            next_h, next_m, next_s = burn.ass_time(ms + 1).split(':')
            after = int(next_h) * 3600000 + int(next_m) * 60000 + round(float(next_s) * 1000)
            self.assertLessEqual(actual, after)


FF = os.environ.get('SUBTITLE_TEST_FFMPEG')
FONT = os.environ.get('SUBTITLE_TEST_FONT')


@unittest.skipUnless(FF and FONT, 'Set SUBTITLE_TEST_FFMPEG and SUBTITLE_TEST_FONT to run real rendering tests.')
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='subtitle tests [unicode]-')
        cls.root = Path(cls.temp.name)
        # Colons are deliberately excluded on Windows, where they cannot be filenames.
        name = "原片 [a,b] 'quoted'" + (':' if os.name != 'nt' else '') + '.mp4'
        cls.video = cls.root / name
        cls.font = cls.root / ('字体 ' + Path(FONT).name)
        cls.font.write_bytes(Path(FONT).read_bytes())
        burn.run([FF, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=640x360:r=25:d=6',
                  '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6', '-c:v', 'libx264',
                  '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', cls.video])
        cls.srt = cls.root / '字幕 [a,b].srt'
        cls.srt.write_text('1\n00:00:00,500 --> 00:00:02,500\nFirst caption.\n\n2\n00:00:03,000 --> 00:00:05,500\nSecond caption!\n', encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def call(self, output, *extra, subtitle=None, video=None):
        cmd = [sys.executable, str(ROOT / 'scripts/burn_subtitles.py'), '--ffmpeg', FF,
               '--video', str(video or self.video), '--subtitles', str(subtitle or self.srt),
               '--font', str(self.font), '--output', str(output), '--preset', 'ultrafast', *extra]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        return result

    def output(self, name):
        return self.root / (name + '.mp4')

    def test_real_render_font_loaded_audio_and_burned_pixels(self):
        output = self.output('full')
        result = self.call(output, '--verify-media')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['dimensions'], [640, 360])
        self.assertTrue(report['media_verified'])
        self.assertTrue(report['font_selection'])
        fp = str(Path(FF).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe'))
        info = json.loads(burn.run([fp, '-v', 'error', '-show_streams', '-of', 'json', output], text=True).stdout)
        self.assertTrue(any(s['codec_type'] == 'audio' for s in info['streams']))
        def pixels(t):
            return burn.run([FF, '-v', 'error', '-i', output, '-ss', str(t), '-frames:v', '1', '-pix_fmt', 'gray', '-f', 'rawvideo', '-']).stdout
        before, during = pixels(0.1), pixels(1.0)
        self.assertLess(sum(x > 150 for x in before), 10)
        self.assertGreater(sum(x > 150 for x in during), 100)

    def test_check_only_and_existing_output_protection(self):
        output = self.output('check')
        result = self.call(output, '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(output.exists())
        output.write_bytes(b'DO NOT REPLACE')
        result = self.call(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_bytes(), b'DO NOT REPLACE')

    def test_shifted_preview_and_bilingual(self):
        output = self.output('preview')
        result = self.call(output, '--secondary', str(self.srt), '--preview', '1', '--start', '3')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(json.loads(result.stdout)['actual_duration'], 1.0, delta=0.1)
        pixels = burn.run([FF, '-v', 'error', '-i', output, '-frames:v', '1', '-pix_fmt', 'gray', '-f', 'rawvideo', '-']).stdout
        self.assertGreater(sum(x > 150 for x in pixels), 100)

    def test_vtt_and_ass_passthrough(self):
        vtt = self.root / 'basic.vtt'
        vtt.write_text('WEBVTT\n\n00:00.500 --> 00:02.500\n<i>Styled.</i>\n', encoding='utf-8')
        first = self.output('vtt')
        result = self.call(first, subtitle=vtt, *['--preview', '1'])
        self.assertEqual(result.returncode, 0, result.stderr)
        source_ass = first.with_suffix('.ass')
        second = self.output('ass')
        result = self.call(second, subtitle=source_ass, *['--preview', '1'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source_ass.read_bytes(), second.with_suffix('.ass').read_bytes())

    def test_portrait_silent_video(self):
        video = self.root / 'portrait.mp4'
        burn.run([FF, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=white:s=360x640:r=25:d=6',
                  '-c:v', 'libx264', '-pix_fmt', 'yuv420p', video])
        result = self.call(self.output('portrait-out'), '--preview', '1', video=video)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['dimensions'], [360, 640])

    def test_truncated_media_fails(self):
        video = self.root / 'truncated.mp4'
        # faststart keeps headers at the front, so probing can succeed despite missing media.
        complete = self.root / 'faststart.mp4'
        burn.run([FF, '-v', 'error', '-i', self.video, '-c', 'copy', '-movflags', '+faststart', complete])
        raw = complete.read_bytes()
        video.write_bytes(raw[:len(raw) // 2])
        result = self.call(self.output('truncated-out'), '--verify-media', '--check', video=video)
        self.assertNotEqual(result.returncode, 0)

    def test_missing_glyph_preserves_existing_video_on_failure(self):
        subtitle = self.root / 'missing-glyph.srt'
        subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nMissing: \U0010ffff\n', encoding='utf-8')
        output = self.output('protected-failure')
        output.write_bytes(b'EXISTING VIDEO')
        result = self.call(output, '--overwrite', '--preview', '1', subtitle=subtitle)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('glyph', result.stderr.lower())
        self.assertEqual(output.read_bytes(), b'EXISTING VIDEO')

    def test_rotated_video_uses_display_dimensions(self):
        video = self.root / 'rotated.mp4'
        burn.run([FF, '-v', 'error', '-display_rotation:v:0', '90', '-i', self.video, '-c', 'copy', video])
        result = self.call(self.output('rotated-out'), '--preview', '1', video=video)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['dimensions'], [360, 640])

    def test_cjk_line_breaks_preserve_words_and_timing(self):
        text = '这是一条较长字幕，用于检查自动换行并保留器件型号TPS548B28和英文单词Export。' * 3
        subtitle = self.root / 'long-cjk.srt'
        subtitle.write_text('1\n00:00:00,500 --> 00:00:05,500\n' + text + '\n', encoding='utf-8')
        result = self.call(self.output('long-cjk'), '--check', subtitle=subtitle)
        self.assertEqual(result.returncode, 0, result.stderr)
        widths = FontWidths(self.font)
        wrapped = wrap(text, widths, 24, 580)
        self.assertIn('\\N', wrapped)
        self.assertIn('TPS548B28', wrapped)
        self.assertIn('Export', wrapped)
        self.assertEqual(wrapped.replace('\\N', ''), text)
        for line in wrapped.split('\\N'):
            self.assertLessEqual(widths.width(line, 24), 580)


if __name__ == '__main__':
    unittest.main()
