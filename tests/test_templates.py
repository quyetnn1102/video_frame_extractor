"""Static checks on the HTML templates (no browser needed)."""
import re
import unittest
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / 'templates'
TEMPLATE_FILES = sorted(TEMPLATES_DIR.glob('*.html'))

ELEMENT_ID = re.compile(r'\bid="([^"]+)"')
SCRIPT_ID_LOOKUP = re.compile(r"""(?:getElementById\(|\$\()\s*['"]([^'"]+)['"]\s*\)""")
INTERPOLATED_INNER_HTML = re.compile(r'innerHTML\s*\+?=\s*`[^`]*\$\{')
INTERPOLATED_INLINE_HANDLER = re.compile(r'\bon\w+\s*=\s*"[^"]*\$\{')


class TestTemplates(unittest.TestCase):
    def test_templates_were_found(self):
        names = {path.name for path in TEMPLATE_FILES}
        self.assertEqual(names, {'index.html', 'create_short.html', 'trending.html', 'dashboard.html'})

    def test_nothing_follows_the_closing_html_tag(self):
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                text = path.read_text(encoding='utf-8')
                self.assertEqual(text.count('</html>'), 1)
                self.assertTrue(text.rstrip().endswith('</html>'),
                                'content after </html> is rendered as page text and never runs')

    def test_scripts_only_look_up_ids_that_exist_in_the_page(self):
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                text = path.read_text(encoding='utf-8')
                declared = set(ELEMENT_ID.findall(text))
                missing = sorted(set(SCRIPT_ID_LOOKUP.findall(text)) - declared)
                self.assertEqual(missing, [], f'script uses ids that are not in the page: {missing}')

    def test_data_is_never_interpolated_into_html_strings(self):
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                text = path.read_text(encoding='utf-8')
                self.assertIsNone(INTERPOLATED_INNER_HTML.search(text),
                                  'innerHTML built from a template literal with ${...}')
                self.assertIsNone(INTERPOLATED_INLINE_HANDLER.search(text),
                                  'inline event handler built from ${...}')

    def test_create_short_form_matches_the_api(self):
        text = (TEMPLATES_DIR / 'create_short.html').read_text(encoding='utf-8')
        for field in ['shortVideoUrl', 'startTime', 'selectedDuration', 'quality',
                      'overlayText', 'verticalFormat', 'loadingOverlay', 'resultsSection']:
            self.assertIn(f'id="{field}"', text)
        self.assertIn("'/api/create-short'", text)
        self.assertIn("'/api/upload-to-youtube'", text)
        self.assertNotIn('video_path', text, 'the upload API takes a file name, not a server path')
        self.assertNotIn('type="file"', text, 'the API takes a URL, not an uploaded file')

    def test_youtube_sign_in_flow_is_robust(self):
        text = (TEMPLATES_DIR / 'create_short.html').read_text(encoding='utf-8')
        self.assertIn("'/api/youtube-auth/start'", text)
        # The sign-in is awaited by polling the server; popup.closed is unreliable once
        # Google's pages sever the link to the opener
        wait_logic = text.split('async function ensureSignedIn')[1].split('function startYouTubeUpload')[0]
        self.assertNotIn('.closed', re.sub(r'//.*', '', wait_logic), 'code must not rely on popup.closed')
        # window.open has to run in the click handler, before any await
        handler = text.split('function startYouTubeUpload')[1].split('async function uploadToYouTube')[0]
        self.assertIn('openSignInWindow()', handler)
        self.assertNotIn('await', handler)
        self.assertIn('id="cancelLoadingBtn"', text)

    def test_loading_overlay_is_hidden_until_needed_and_covers_the_page(self):
        text = (TEMPLATES_DIR / 'create_short.html').read_text(encoding='utf-8')
        rule = re.search(r'\.loading-overlay\s*\{([^}]*)\}', text).group(1)
        for declaration in ['position: fixed', 'display: none', 'z-index']:
            self.assertIn(declaration, rule)

    def test_no_invented_reliability_percentages_are_shown(self):
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                self.assertNotIn('Reliability', path.read_text(encoding='utf-8'))

    def test_external_assets_come_from_hosts_allowed_by_the_csp(self):
        import app_enhanced
        allowed = ('https://cdn.jsdelivr.net', 'https://cdnjs.cloudflare.com')
        for path in TEMPLATE_FILES:
            text = path.read_text(encoding='utf-8')
            for url in re.findall(r'(?:src|href)="(https?://[^"]+)"', text):
                with self.subTest(template=path.name, url=url):
                    self.assertTrue(url.startswith(allowed))
        for origin in allowed:
            self.assertIn(origin, app_enhanced.CONTENT_SECURITY_POLICY)


if __name__ == '__main__':
    unittest.main()
