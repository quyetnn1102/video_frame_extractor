"""The background job registry: states, progress, cancellation and cleanup."""
import threading
import time
import unittest
from unittest.mock import patch

import jobs
from jobs import (CANCELLED, FAILED, QUEUED, RUNNING, SUCCEEDED, JobCancelled, JobFailed,
                  JobQueueFull, JobRegistry, NullReporter)

WAIT_SECONDS = 5


def wait_until(condition, timeout=WAIT_SECONDS):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class TestJobRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = JobRegistry(max_workers=1)

    def tearDown(self):
        self.registry.shutdown()

    def test_a_job_reports_its_stages_progress_and_result(self):
        seen = []
        release = threading.Event()

        def work(reporter):
            reporter.stage('download', 'Downloading the video')
            reporter.progress(0.5)
            seen.append(self.registry.list()[0].to_dict())  # the only job (submit may not have returned yet)
            release.wait(WAIT_SECONDS)
            return {'frames': 3}

        job = self.registry.submit('extract', ['download', 'extract'], work)
        self.assertTrue(wait_until(lambda: seen))
        during = seen[0]
        self.assertEqual((during['state'], during['stage'], during['progress']), (RUNNING, 'download', 0.5))
        self.assertEqual((during['stage_index'], during['stage_count']), (1, 2))
        self.assertEqual(during['message'], 'Downloading the video')

        release.set()
        self.assertTrue(wait_until(lambda: job.state == SUCCEEDED))
        self.assertEqual(job.to_dict()['result'], {'frames': 3})
        self.assertIsNone(job.error)

    def test_progress_is_kept_between_zero_and_one(self):
        def work(reporter):
            reporter.progress(7)
            return {}
        job = self.registry.submit('extract', ['download'], work)
        self.assertTrue(wait_until(lambda: job.state == SUCCEEDED))
        self.assertEqual(job.progress, 1.0)

    def test_cancelling_a_running_job_stops_it_at_its_next_check(self):
        started = threading.Event()

        def work(reporter):
            started.set()
            while True:  # a download loop: progress() is where cancellation lands
                reporter.progress(None)
                time.sleep(0.01)

        job = self.registry.submit('short', ['download'], work)
        self.assertTrue(started.wait(WAIT_SECONDS))
        self.registry.cancel(job.id)
        self.assertTrue(wait_until(lambda: job.state == CANCELLED))
        self.assertIsNotNone(job.finished)

    def test_a_queued_job_is_cancelled_without_running(self):
        release = threading.Event()
        ran = []
        first = self.registry.submit('short', ['render'], lambda reporter: release.wait(WAIT_SECONDS) or {})
        second = self.registry.submit('short', ['render'], lambda reporter: ran.append(True) or {})
        self.assertEqual(second.state, QUEUED, 'one worker: the second job waits')
        self.assertEqual(second.message, jobs.WAITING_MESSAGE, 'only a job that really waits says so')

        self.registry.cancel(second.id)
        self.assertEqual(second.state, CANCELLED)
        release.set()
        self.assertTrue(wait_until(lambda: first.state == SUCCEEDED))
        time.sleep(0.05)
        self.assertEqual(ran, [])

    def test_expected_failures_show_their_message(self):
        def work(reporter):
            raise JobFailed('This video is private.')
        job = self.registry.submit('extract', ['download'], work)
        self.assertTrue(wait_until(lambda: job.state == FAILED))
        self.assertEqual(job.error, 'This video is private.')

    def test_unexpected_errors_are_logged_but_not_shown(self):
        def work(reporter):
            raise RuntimeError(r'C:\secret\path')
        with patch.object(jobs.app_logger, 'exception') as logged:
            job = self.registry.submit('extract', ['download'], work)
            self.assertTrue(wait_until(lambda: job.state == FAILED))
        self.assertEqual(job.error, jobs.UNEXPECTED_ERROR)
        self.assertNotIn('secret', job.to_dict()['error'])
        logged.assert_called_once()

    def test_cancelling_a_finished_or_unknown_job_changes_nothing(self):
        job = self.registry.submit('extract', ['download'], lambda reporter: {})
        self.assertTrue(wait_until(lambda: job.state == SUCCEEDED))
        self.assertEqual(self.registry.cancel(job.id)['state'], SUCCEEDED)
        self.assertIsNone(self.registry.cancel('no-such-job'))

    def test_jobs_are_listed_newest_first_and_old_ones_are_forgotten(self):
        first = self.registry.submit('extract', ['download'], lambda reporter: {})
        self.assertTrue(wait_until(lambda: first.state == SUCCEEDED))
        second = self.registry.submit('short', ['download'], lambda reporter: {})
        self.assertTrue(wait_until(lambda: second.state == SUCCEEDED))
        second.created = first.created + 1
        self.assertEqual([job.id for job in self.registry.list()], [second.id, first.id])

        first.finished -= jobs.KEEP_FINISHED_SECONDS + 1
        self.assertEqual([job.id for job in self.registry.list()], [second.id])
        self.assertIsNone(self.registry.get(first.id))

    def test_the_number_of_kept_jobs_is_capped(self):
        with patch.object(jobs, 'MAX_KEPT_JOBS', 3):
            for _ in range(5):
                job = self.registry.submit('extract', ['download'], lambda reporter: {})
                self.assertTrue(wait_until(lambda: job.state == SUCCEEDED))
            self.assertLessEqual(len(self.registry.list()), 3)


class TestJobLimitsAndRecords(unittest.TestCase):
    def setUp(self):
        self.registry = JobRegistry(max_workers=1, max_unfinished=2)
        self.release = threading.Event()
        self.addCleanup(self.registry.shutdown)
        self.addCleanup(self.release.set)

    def blocked(self, reporter):
        self.release.wait(WAIT_SECONDS)
        return {}

    def test_too_many_unfinished_jobs_are_refused(self):
        self.registry.submit('short', ['render'], self.blocked)
        self.registry.submit('short', ['render'], self.blocked)
        with self.assertRaises(JobQueueFull):
            self.registry.submit('short', ['render'], self.blocked)

    def test_cancelling_a_queued_job_tells_whoever_records_it(self):
        recorded = []
        self.registry.submit('short', ['render'], self.blocked)
        waiting = self.registry.submit('short', ['render'], self.blocked,
                                       on_cancel_while_queued=lambda: recorded.append('cancelled'))
        snapshot = self.registry.cancel(waiting.id)
        self.assertEqual((snapshot['state'], recorded), (CANCELLED, ['cancelled']))
        self.registry.cancel(waiting.id)
        self.assertEqual(recorded, ['cancelled'], 'recorded once')

    def test_a_job_that_starts_no_longer_has_a_queued_cancel_callback(self):
        recorded = []
        job = self.registry.submit('short', ['render'], self.blocked,
                                   on_cancel_while_queued=lambda: recorded.append('cancelled'))
        self.assertTrue(wait_until(lambda: job.state == RUNNING))
        self.registry.cancel(job.id)
        self.assertEqual(recorded, [], 'a running job records its own outcome')

    def test_snapshots_are_plain_dicts_newest_first(self):
        first = self.registry.submit('extract', ['download'], self.blocked)
        second = self.registry.submit('short', ['download'], self.blocked)
        second.created = first.created + 1
        self.assertEqual([job['id'] for job in self.registry.snapshots()], [second.id, first.id])
        self.assertEqual(self.registry.snapshot(first.id)['kind'], 'extract')
        self.assertIsNone(self.registry.snapshot('missing'))

    def test_workers_do_not_keep_the_app_from_stopping(self):
        workers = [thread for thread in threading.enumerate() if thread.name.startswith('job-')]
        self.assertTrue(workers)
        self.assertTrue(all(thread.daemon for thread in workers))


class TestNullReporter(unittest.TestCase):
    def test_does_nothing_and_never_cancels(self):
        reporter = NullReporter()
        reporter.stage('download', 'Downloading')
        reporter.progress(0.5)
        reporter.check_cancelled()


class TestJobCancelledIsAnException(unittest.TestCase):
    def test_cleanup_code_that_catches_exception_also_runs_on_cancel(self):
        self.assertTrue(issubclass(JobCancelled, Exception))


if __name__ == '__main__':
    unittest.main()
