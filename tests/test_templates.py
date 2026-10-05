"""Static checks on the HTML templates (no browser needed)."""
import re
import unittest
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / 'templates'
TEMPLATE_FILES = sorted(TEMPLATES_DIR.glob('*.html'))
STATIC_DIR = Path(__file__).resolve().parent.parent / 'static'
STYLESHEET = STATIC_DIR / 'css' / 'app.css'

ELEMENT_ID = re.compile(r'\bid="([^"]+)"')
SCRIPT_ID_LOOKUP = re.compile(r"""(?:getElementById\(|\$\()\s*['"]([^'"]+)['"]\s*\)""")
INTERPOLATED_INNER_HTML = re.compile(r'innerHTML\s*\+?=\s*`[^`]*\$\{')
INTERPOLATED_INLINE_HANDLER = re.compile(r'\bon\w+\s*=\s*"[^"]*\$\{')


class TestTemplates(unittest.TestCase):
    def test_templates_were_found(self):
        names = {path.name for path in TEMPLATE_FILES}
        self.assertEqual(names, {'index.html', 'extract.html', 'create_short.html', 'trending.html',
                                 'dashboard.html'})

    def test_pages_share_the_sidebar_and_top_bar_instead_of_copying_them(self):
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                text = path.read_text(encoding='utf-8')
                for include in ['partials/icons.html', 'partials/sidebar.html', 'partials/topbar.html']:
                    self.assertIn(f"{{% include '{include}' %}}", text)
                self.assertRegex(text, r"\{% set active_page = '(home|extract|create|trending|dashboard)' %\}")
                self.assertIn('src="/static/js/shell.js"', text)
        for partial in ['icons', 'sidebar', 'topbar']:
            self.assertTrue((TEMPLATES_DIR / 'partials' / f'{partial}.html').is_file())

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

    def test_earlier_shorts_are_listed_again_when_the_page_opens(self):
        """The result used to live only in the page, so leaving or refreshing it lost the short."""
        text = (TEMPLATES_DIR / 'create_short.html').read_text(encoding='utf-8')
        self.assertIn("fetch('/api/shorts')", text)
        self.assertIn("'/api/shorts/delete'", text)
        self.assertIn('loadLibrary();', text, 'the list must be requested on page load')
        section = re.search(r'<section[^>]*id="resultsSection"[^>]*>', text).group(0)
        self.assertNotIn('hidden', section, 'the list of shorts must be visible on a fresh page')

    def test_the_last_extraction_is_remembered_by_the_extract_page(self):
        text = (TEMPLATES_DIR / 'extract.html').read_text(encoding='utf-8')
        self.assertIn('localStorage.setItem', text)
        self.assertIn('savedExtraction()', text)

    def test_link_fields_show_a_preview_from_the_shared_script(self):
        script = STATIC_DIR / 'js' / 'link-preview.js'
        self.assertTrue(script.is_file())
        for page, slot in [('index.html', 'launchPreview'), ('extract.html', 'linkPreview'),
                           ('create_short.html', 'shortLinkPreview')]:
            with self.subTest(template=page):
                text = (TEMPLATES_DIR / page).read_text(encoding='utf-8')
                self.assertIn('src="/static/js/link-preview.js"', text)
                self.assertIn(f'id="{slot}"', text)
                self.assertIn(f"$('{slot}')", text)
        self.assertNotIn('innerHTML', script.read_text(encoding='utf-8'),
                         'titles and channel names come from other sites')

    def test_extraction_warnings_are_shown_to_the_user(self):
        """/api/extract reports timestamps it could not extract; the page must not drop them."""
        text = (TEMPLATES_DIR / 'extract.html').read_text(encoding='utf-8')
        self.assertIn('result.warnings', text)
        self.assertIn('id="extractWarnings"', text)

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

    def test_pages_share_one_stylesheet_and_its_fonts_exist(self):
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                self.assertIn('href="/static/css/app.css"', path.read_text(encoding='utf-8'))
        css = STYLESHEET.read_text(encoding='utf-8')
        font_files = re.findall(r'url\("([^"]+)"\)', css)
        self.assertTrue(font_files, 'the stylesheet should load its fonts from this origin')
        for relative in font_files:
            with self.subTest(font=relative):
                self.assertTrue((STYLESHEET.parent / relative).resolve().is_file())

    def test_loading_overlay_is_hidden_until_needed_and_covers_the_page(self):
        # the rule lives in the shared stylesheet; the page must contain the overlay it styles
        self.assertIn('id="loadingOverlay"', (TEMPLATES_DIR / 'create_short.html').read_text(encoding='utf-8'))
        text = STYLESHEET.read_text(encoding='utf-8')
        rule = re.search(r'\.loading-overlay\s*\{([^}]*)\}', text).group(1)
        for declaration in ['position: fixed', 'display: none', 'z-index']:
            self.assertIn(declaration, rule)

    def test_the_top_bar_button_keeps_its_name_on_small_screens(self):
        """display:none on the label left the icon-only "New short" link without a name."""
        css = STYLESHEET.read_text(encoding='utf-8')
        rule = re.search(r'\.topbar-actions \.btn-label\s*\{([^}]*)\}', css).group(1)
        self.assertNotIn('display: none', rule)
        self.assertIn('clip:', rule)

    def test_the_closed_mobile_drawer_cannot_be_reached_by_keyboard(self):
        css = STYLESHEET.read_text(encoding='utf-8')
        drawer = css.split('@media (max-width: 56rem)')[1]
        self.assertRegex(drawer, r'\.sidebar\s*\{[^}]*visibility: hidden')
        self.assertRegex(drawer, r'\.menu-open \.sidebar\s*\{[^}]*visibility: visible')
        shell = (STATIC_DIR / 'js' / 'shell.js').read_text(encoding='utf-8')
        self.assertIn('workspace.inert = open', shell)
        self.assertIn('menuButton.focus()', shell, 'closing the drawer must return focus to the menu button')

    def test_the_busy_overlay_is_a_modal_that_is_announced(self):
        ui = (STATIC_DIR / 'js' / 'ui.js').read_text(encoding='utf-8')
        self.assertIn(".inert = true", ui, 'the page behind the overlay must not be reachable')
        for page in ['extract.html', 'create_short.html']:
            with self.subTest(template=page):
                text = (TEMPLATES_DIR / page).read_text(encoding='utf-8')
                overlay = re.search(r'<div class="loading-overlay"[^>]*>', text).group(0)
                self.assertIn('role="dialog"', overlay)
                self.assertIn('aria-modal="true"', overlay)
                # a live region that is itself shown and hidden is not read out reliably
                self.assertNotIn('role="status"', overlay)
                self.assertIn('id="busyStatus" role="status"', text)
                self.assertIn('src="/static/js/ui.js"', text)
                self.assertIn('ui.showBusy(', text)
                self.assertIn('ui.hideBusy(', text)
        # Focus cannot move into the page while it is inert, so the results take focus via hideBusy
        extract = (TEMPLATES_DIR / 'extract.html').read_text(encoding='utf-8')
        self.assertIn('ui.hideBusy(focusAfter)', extract)

    def test_forms_show_their_own_errors_at_each_field(self):
        for page in ['extract.html', 'create_short.html']:
            with self.subTest(template=page):
                text = (TEMPLATES_DIR / page).read_text(encoding='utf-8')
                form = re.search(r'<form [^>]*>', text).group(0)
                self.assertIn('novalidate', form, 'browser tooltips would pre-empt the error summary')
                self.assertIn('id="errorSummary" class="error-summary" tabindex="-1" hidden', text)
                self.assertIn('ui.showErrors(', text)
                self.assertIn("ui.whileWorking($('validate", text, 'Check link needs a busy state')

    def test_the_timecode_limit_matches_the_server(self):
        from validators import MAX_TIMESTAMPS
        text = (TEMPLATES_DIR / 'extract.html').read_text(encoding='utf-8')
        self.assertEqual(int(re.search(r'MAX_TIMECODES = (\d+)', text).group(1)), MAX_TIMESTAMPS)
        self.assertIn(f'Up to {MAX_TIMESTAMPS}.', text)

    def test_deleting_a_short_is_confirmed_in_a_dialog_without_a_time_limit(self):
        text = (TEMPLATES_DIR / 'create_short.html').read_text(encoding='utf-8')
        self.assertNotIn('Click again', text)
        delete = text.split('function confirmDelete')[1].split('async function deleteShort')[0]
        self.assertIn('showModal()', delete)
        self.assertNotIn('setTimeout', delete)

    def test_dashboard_lists_put_each_label_before_its_value(self):
        text = (TEMPLATES_DIR / 'dashboard.html').read_text(encoding='utf-8')
        for group in re.findall(r'<dl[^>]*>(.*?)</dl>', text, re.S):
            for first_of_pair in re.findall(r'<(dt|dd)\b', group)[::2]:
                self.assertEqual(first_of_pair, 'dt', 'a <dd> before its <dt> is read out backwards')
        status = re.search(r'<p[^>]*id="lastUpdated"[^>]*>', text).group(0)
        self.assertNotIn('role="status"', status, 'a status rewritten every 5 s is announced every 5 s')
        self.assertIn('role="meter"', text)

    def test_no_invented_reliability_percentages_are_shown(self):
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                self.assertNotIn('Reliability', path.read_text(encoding='utf-8'))

    def test_every_third_party_asset_has_a_subresource_integrity_hash(self):
        """A compromised CDN file would otherwise run in the origin that can publish to YouTube."""
        # The pages currently load nothing from a CDN; this guards any asset added later
        tag = re.compile(r'<(?:script|link)\b[^>]*\b(?:src|href)="https?://[^"]+"[^>]*>')
        for path in TEMPLATE_FILES:
            for element in tag.findall(path.read_text(encoding='utf-8')):
                with self.subTest(template=path.name, element=element[:90]):
                    self.assertRegex(element, r'integrity="sha384-[A-Za-z0-9+/]{64}"')
                    self.assertIn('crossorigin="anonymous"', element)

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
