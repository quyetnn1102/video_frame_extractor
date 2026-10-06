"""Static checks on the HTML templates (no browser needed)."""
import re
import unittest
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / 'templates'
TEMPLATE_FILES = sorted(TEMPLATES_DIR.glob('*.html'))
STATIC_DIR = Path(__file__).resolve().parent.parent / 'static'
STYLESHEET = STATIC_DIR / 'css' / 'app.css'
SHELL_STYLESHEET = STATIC_DIR / 'css' / 'shell.css'

ELEMENT_ID = re.compile(r'\bid="([^"]+)"')
SCRIPT_ID_LOOKUP = re.compile(r"""(?:getElementById\(|\$\()\s*['"]([^'"]+)['"]\s*\)""")
INTERPOLATED_INNER_HTML = re.compile(r'innerHTML\s*\+?=\s*`[^`]*\$\{')
INTERPOLATED_INLINE_HANDLER = re.compile(r'\bon\w+\s*=\s*"[^"]*\$\{')
PAGE_SCRIPT = re.compile(r'<script src="/static/js/pages/([\w-]+\.js)"></script>')


def page_source(path):
    """A page's markup followed by its own script, which lives in static/js/pages/."""
    text = path.read_text(encoding='utf-8')
    for name in PAGE_SCRIPT.findall(text):
        text += '\n' + (STATIC_DIR / 'js' / 'pages' / name).read_text(encoding='utf-8')
    return text


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
                text = page_source(path)
                declared = set(ELEMENT_ID.findall(text))
                missing = sorted(set(SCRIPT_ID_LOOKUP.findall(text)) - declared)
                self.assertEqual(missing, [], f'script uses ids that are not in the page: {missing}')

    def test_data_is_never_interpolated_into_html_strings(self):
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                text = page_source(path)
                self.assertIsNone(INTERPOLATED_INNER_HTML.search(text),
                                  'innerHTML built from a template literal with ${...}')
                self.assertIsNone(INTERPOLATED_INLINE_HANDLER.search(text),
                                  'inline event handler built from ${...}')

    def test_create_short_form_matches_the_api(self):
        text = page_source(TEMPLATES_DIR / 'create_short.html')
        for field in ['shortVideoUrl', 'startTime', 'selectedDuration', 'quality',
                      'overlayText', 'verticalFormat', 'loadingOverlay', 'resultsSection']:
            self.assertIn(f'id="{field}"', text)
        self.assertIn("'/api/jobs/create-short'", text)
        self.assertIn("'/api/upload-to-youtube'", text)
        self.assertNotIn('video_path', text, 'the upload API takes a file name, not a server path')
        self.assertNotIn('type="file"', text, 'the API takes a URL, not an uploaded file')

    def test_earlier_shorts_are_listed_again_when_the_page_opens(self):
        """The result used to live only in the page, so leaving or refreshing it lost the short."""
        text = page_source(TEMPLATES_DIR / 'create_short.html')
        self.assertIn("fetch('/api/shorts')", text)
        self.assertIn("'/api/shorts/delete'", text)
        self.assertIn('loadLibrary();', text, 'the list must be requested on page load')
        section = re.search(r'<section[^>]*id="resultsSection"[^>]*>', text).group(0)
        self.assertNotIn('hidden', section, 'the list of shorts must be visible on a fresh page')

    def test_the_last_extraction_is_remembered_by_the_extract_page(self):
        text = page_source(TEMPLATES_DIR / 'extract.html')
        self.assertIn('localStorage.setItem', text)
        self.assertIn('savedExtraction()', text)

    def test_link_fields_are_analyzed_by_the_shared_script(self):
        """One "Analyze video" step on every page: the same check, wording and errors."""
        script = STATIC_DIR / 'js' / 'video-source.js'
        self.assertTrue(script.is_file())
        for page, slot in [('index.html', 'launchPreview'), ('extract.html', 'linkPreview'),
                           ('create_short.html', 'shortLinkPreview')]:
            with self.subTest(template=page):
                text = page_source(TEMPLATES_DIR / page)
                self.assertIn('src="/static/js/video-source.js"', text)
                self.assertLess(text.index('src="/static/js/ui.js"'), text.index('src="/static/js/video-source.js"'),
                                'video-source.js uses ui.js')
                self.assertIn('videoSource.attach(', text)
                self.assertIn(f'id="{slot}"', text)
                self.assertIn(f"$('{slot}')", text)
                self.assertNotIn('Check link', text, 'the button is called "Analyze video"')
        self.assertNotIn('innerHTML', script.read_text(encoding='utf-8'),
                         'titles and channel names come from other sites')

    def test_extraction_warnings_are_shown_to_the_user(self):
        """/api/extract reports timestamps it could not extract; the page must not drop them."""
        text = page_source(TEMPLATES_DIR / 'extract.html')
        self.assertIn('result.warnings', text)
        self.assertIn('id="extractWarnings"', text)

    def test_youtube_sign_in_flow_is_robust(self):
        text = page_source(TEMPLATES_DIR / 'create_short.html')
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
        self.assertIn('id="loadingOverlay"', page_source(TEMPLATES_DIR / 'create_short.html'))
        text = STYLESHEET.read_text(encoding='utf-8')
        rule = re.search(r'\.loading-overlay\s*\{([^}]*)\}', text).group(1)
        for declaration in ['position: fixed', 'display: none', 'z-index']:
            self.assertIn(declaration, rule)

    def test_the_top_bar_button_keeps_its_name_on_small_screens(self):
        """display:none on the label left the icon-only "New short" link without a name."""
        css = SHELL_STYLESHEET.read_text(encoding='utf-8')
        rule = re.search(r'\.topbar-actions \.btn-label\s*\{([^}]*)\}', css).group(1)
        self.assertNotIn('display: none', rule)
        self.assertIn('clip:', rule)

    def test_the_closed_mobile_drawer_cannot_be_reached_by_keyboard(self):
        css = SHELL_STYLESHEET.read_text(encoding='utf-8')
        drawer = css.split('@media (max-width: 56rem)')[1]
        self.assertRegex(drawer, r'\.sidebar\s*\{[^}]*visibility: hidden')
        self.assertRegex(drawer, r'\.menu-open \.sidebar\s*\{[^}]*visibility: visible')
        shell = (STATIC_DIR / 'js' / 'shell.js').read_text(encoding='utf-8')
        self.assertIn('workspace.inert = open', shell)
        self.assertIn('menuButton.focus()', shell, 'closing the drawer must return focus to the menu button')

    def test_the_busy_overlay_is_a_modal_that_is_announced(self):
        """Only the YouTube sign-in and upload still block the page; renders are background jobs."""
        ui = (STATIC_DIR / 'js' / 'ui.js').read_text(encoding='utf-8')
        self.assertIn(".inert = true", ui, 'the page behind the overlay must not be reachable')
        text = page_source(TEMPLATES_DIR / 'create_short.html')
        overlay = re.search(r'<div class="loading-overlay"[^>]*>', text).group(0)
        self.assertIn('role="dialog"', overlay)
        self.assertIn('aria-modal="true"', overlay)
        # a live region that is itself shown and hidden is not read out reliably
        self.assertNotIn('role="status"', overlay)
        self.assertIn('id="busyStatus" role="status"', text)
        self.assertIn('ui.showBusy(', text)
        self.assertIn('ui.hideBusy(', text)
        self.assertNotIn('loading-overlay', page_source(TEMPLATES_DIR / 'extract.html'))

    def test_long_work_runs_as_a_background_job_with_progress_and_cancel(self):
        for page, route, kind in [('extract.html', '/api/jobs/extract', "'extract'"),
                                  ('create_short.html', '/api/jobs/create-short', "'short'")]:
            with self.subTest(template=page):
                text = page_source(TEMPLATES_DIR / page)
                self.assertIn(f"jobs.start('{route}'", text)
                self.assertIn(f'jobs.latest({kind})', text, 'a job started earlier is picked up again')
                self.assertIn('id="jobPanel"', text)
                self.assertIn('href="/static/css/jobs.css"', text)
                self.assertLess(text.index('src="/static/js/ui.js"'), text.index('src="/static/js/job-progress.js"'))
                # the progress card and the focus in it go away when the job ends
                self.assertRegex(text, r"\$\('(extractSubmit|createSubmit)'\)\.focus\(\)")
        script = (STATIC_DIR / 'js' / 'job-progress.js').read_text(encoding='utf-8')
        self.assertIn("element('progress'", script, 'a real progressbar for assistive technology')
        self.assertIn("setAttribute('role', 'status')", script)
        self.assertIn("'/cancel'", script)

    def test_forms_show_their_own_errors_at_each_field(self):
        for page in ['extract.html', 'create_short.html']:
            with self.subTest(template=page):
                text = page_source(TEMPLATES_DIR / page)
                form = re.search(r'<form [^>]*>', text).group(0)
                self.assertIn('novalidate', form, 'browser tooltips would pre-empt the error summary')
                self.assertIn('id="errorSummary" class="error-summary" tabindex="-1" hidden', text)
                self.assertIn('ui.showErrors(', text)
                self.assertIn('>Analyze video</button>', text)

    def test_the_timecode_limit_matches_the_server(self):
        from validators import MAX_TIMESTAMPS
        text = page_source(TEMPLATES_DIR / 'extract.html')
        self.assertEqual(int(re.search(r'MAX_TIMECODES = (\d+)', text).group(1)), MAX_TIMESTAMPS)
        self.assertIn(f'Up to {MAX_TIMESTAMPS}.', text)

    def test_deleting_a_short_is_confirmed_in_a_dialog_without_a_time_limit(self):
        text = page_source(TEMPLATES_DIR / 'create_short.html')
        self.assertNotIn('Click again', text)
        delete = text.split('function confirmDelete')[1].split('async function deleteShort')[0]
        self.assertIn('showModal()', delete)
        self.assertNotIn('setTimeout', delete)

    def test_dashboard_lists_put_each_label_before_its_value(self):
        text = page_source(TEMPLATES_DIR / 'dashboard.html')
        for group in re.findall(r'<dl[^>]*>(.*?)</dl>', text, re.S):
            for first_of_pair in re.findall(r'<(dt|dd)\b', group)[::2]:
                self.assertEqual(first_of_pair, 'dt', 'a <dd> before its <dt> is read out backwards')
        status = re.search(r'<p[^>]*id="lastUpdated"[^>]*>', text).group(0)
        self.assertNotIn('role="status"', status, 'a status rewritten every 5 s is announced every 5 s')
        self.assertIn('role="meter"', text)

    def test_pages_have_no_inline_scripts_styles_or_handlers(self):
        """The CSP has no 'unsafe-inline', so any of these would be blocked by the browser."""
        import app_enhanced
        markup = [(path.name, path.read_text(encoding='utf-8'))
                  for path in [*TEMPLATE_FILES, *sorted((TEMPLATES_DIR / 'partials').glob('*.html'))]]
        markup.append(('OAUTH_RESULT_PAGE', app_enhanced.OAUTH_RESULT_PAGE))
        for name, text in markup:
            with self.subTest(template=name):
                self.assertNotIn('<style', text)
                self.assertIsNone(re.search(r'<script(?![^>]*\bsrc=)[^>]*>', text), 'inline <script>')
                self.assertNotIn('style="', text)
                self.assertIsNone(re.search(r'\son[a-z]+="', text), 'inline event handler')
        policy = app_enhanced.CONTENT_SECURITY_POLICY
        self.assertNotIn("'unsafe-inline'", policy)

    def test_page_assets_exist_and_every_page_loads_the_shell(self):
        asset = re.compile(r'(?:src|href)="/static/([^"]+)"')
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                text = path.read_text(encoding='utf-8')
                self.assertIn('href="/static/css/shell.css"', text)
                for relative in asset.findall(text):
                    self.assertTrue((STATIC_DIR / relative).is_file(), relative)

    def test_page_scripts_use_the_shared_helpers_instead_of_copies(self):
        for script in sorted((STATIC_DIR / 'js' / 'pages').glob('*.js')):
            with self.subTest(script=script.name):
                text = script.read_text(encoding='utf-8')
                for helper in ['element', 'notice', 'scrollBehavior', 'relativeTime', 'postJson', 'isLink']:
                    self.assertNotIn(f'function {helper}(', text, 'use the one in static/js/ui.js')
                self.assertNotIn("'/api/video-info'", text, 'links are analyzed by video-source.js')

    def test_each_page_has_at_most_one_primary_button(self):
        """The top bar shortcut is secondary, so it never competes with the page's own action."""
        self.assertNotIn('btn-primary', (TEMPLATES_DIR / 'partials' / 'topbar.html').read_text(encoding='utf-8'))
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                self.assertLessEqual(path.read_text(encoding='utf-8').count('btn-primary'), 1)

    def test_colours_are_tokens_defined_once(self):
        """Hex and rgba colours live in the :root block of app.css; everything else uses var(--...)."""
        colour = re.compile(r'#[0-9a-fA-F]{3,6}\b|rgba?\(')
        app = STYLESHEET.read_text(encoding='utf-8')
        root_end = app.index('\n}\n', app.index(':root {'))
        stylesheets = [('app.css (after :root)', app[root_end:])]
        stylesheets += [(css.name, css.read_text(encoding='utf-8'))
                        for css in sorted((STATIC_DIR / 'css').rglob('*.css')) if css != STYLESHEET]
        for name, text in stylesheets:
            with self.subTest(stylesheet=name):
                self.assertEqual(colour.findall(text), [])

    def test_stylesheets_and_scripts_stay_under_800_lines(self):
        files = [*(STATIC_DIR / 'css').rglob('*.css'), *(STATIC_DIR / 'js').rglob('*.js')]
        for path in files:
            with self.subTest(file=path.name):
                self.assertLess(len(path.read_text(encoding='utf-8').splitlines()), 800)

    def test_every_page_has_a_favicon(self):
        self.assertTrue((STATIC_DIR / 'favicon.svg').is_file())
        for path in TEMPLATE_FILES:
            with self.subTest(template=path.name):
                self.assertIn('<link rel="icon" href="/static/favicon.svg"', path.read_text(encoding='utf-8'))

    def test_page_level_improvements(self):
        home = page_source(TEMPLATES_DIR / 'index.html')
        self.assertIn("'/create-short?short=' + encodeURIComponent(item.filename)", home, 'a recent short opens itself')
        self.assertIn("$('startSection').hidden", home, 'the first-visit steps go once there are shorts')

        trending = page_source(TEMPLATES_DIR / 'trending.html')
        self.assertNotIn('platformSelect', trending, 'only YouTube exists: no dead select')
        self.assertNotIn('setInterval', trending, 'no list rebuilt under the user; Refresh is manual')
        self.assertIn("$('categorySelect').addEventListener('change'", trending)
        self.assertIn("openWith('/create-short'", trending)
        self.assertIn('data.sample', trending, 'sample data is called sample data')

        create = page_source(TEMPLATES_DIR / 'create_short.html')
        self.assertIn("'/api/clip-suggestions'", create, 'Suggest moments asks the server')
        self.assertIn("$('createSubmit').focus()", create)
        self.assertNotIn('resetFormBtn', create, 'no Reset beside the main action')
        self.assertIn('function reviewUpload', create, 'title, description and privacy are reviewed first')
        self.assertIn("privacy: details.privacy", create)

        extract = page_source(TEMPLATES_DIR / 'extract.html')
        self.assertIn("'/api/frames/archive'", extract)
        self.assertIn('id="startOverBtn"', extract)

        dashboard = page_source(TEMPLATES_DIR / 'dashboard.html')
        self.assertIn('id="requestRows"', dashboard)
        self.assertIn("'/api/cleanup'", dashboard)
        self.assertIn('document.hidden', dashboard, 'no polling in a background tab')
        self.assertIn('showPlatforms(data.analytics.platform_outcomes)', dashboard, 'success and failure per platform')
        cleanup = dashboard.split('function confirmCleanup')[1].split("addEventListener('click', confirmCleanup)")[0]
        self.assertIn('showModal()', cleanup, 'deleting shorts is confirmed first')
        self.assertIn('Shorts, frames and downloads', dashboard, 'the button says what it deletes')
        self.assertIn('reloadWhenDone', trending, 'a filter changed while loading is not dropped')
        self.assertIn('if (busy) return;  // an extraction is running', extract)

    def test_touch_screens_get_44px_targets(self):
        self.assertRegex(STYLESHEET.read_text(encoding='utf-8'), r'@media \(pointer: coarse\) \{\s*\.btn-sm')
        self.assertIn('@media (pointer: coarse)', SHELL_STYLESHEET.read_text(encoding='utf-8'))

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
