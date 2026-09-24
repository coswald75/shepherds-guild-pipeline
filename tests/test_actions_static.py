"""Static checks for the GitHub Actions move.

These tests do not call Supabase, Anthropic, Resend, or GitHub.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

sys.path.insert(0, str(ROOT / "scripts"))
import check_stuck_sermons as stuck  # noqa: E402


def _load_plan():
    path = ROOT / ".github" / "scripts" / "plan_weekly_run.py"
    spec = importlib.util.spec_from_file_location("plan_weekly_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan = _load_plan()
NOW = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)


def _sermon(**overrides):
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Grace upon grace",
        "created_at": (NOW - timedelta(days=3)).isoformat(),
        "audio_url": "https://cdn.example/sermon.mp3",
        "hosted_audio_url": None,
        "decomposed_at": None,
        "last_rendered_at": None,
    }
    row.update(overrides)
    return row


class ScheduleOffTests(unittest.TestCase):
    def test_every_workflow_is_dispatch_only(self):
        files = list(WORKFLOWS.glob("*.yml"))
        self.assertGreaterEqual(len(files), 3)
        for path in files:
            text = path.read_text()
            self.assertIn("workflow_dispatch:", text, path.name)
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                self.assertNotIn("schedule:", stripped, f"{path.name}:{lineno}")
                self.assertNotIn("cron:", stripped, f"{path.name}:{lineno}")

    def test_long_jobs_document_the_six_hour_cap(self):
        weekly = (WORKFLOWS / "weekly-ingest.yml").read_text()
        cog = (WORKFLOWS / "cogwatch.yml").read_text()
        self.assertIn("timeout-minutes: 360", weekly)
        self.assertIn("timeout-minutes: 360", cog)
        self.assertIn('BATCH_MAX_WAIT_HOURS: "5"', weekly)
        self.assertIn("if: failure()", weekly)
        self.assertIn("if: failure()", cog)
        self.assertIn("if: failure()", (WORKFLOWS / "stuck-sermons.yml").read_text())

    def test_requirements_include_the_missing_imports(self):
        text = (ROOT / "requirements.txt").read_text()
        for package in ("assemblyai", "json-repair", "feedparser", "jinja2", "playwright", "pdfplumber"):
            self.assertIn(package, text)

    def test_mac_paths_read_the_env_override(self):
        steward = [
            "scripts/deploy_sermon_pages.py",
            "scripts/build_church_indexes.py",
            "scripts/build_podcast_feeds.py",
            "scripts/build_famous_preacher_pages.py",
            "scripts/build_ricky_sample_pages.py",
        ]
        for rel in steward:
            text = (ROOT / rel).read_text()
            self.assertIn("SERMON_STEWARD_REPO", text, rel)
            self.assertIn("/Users/dad/shepherds-guild/sermon-steward", text, rel)
        for rel in ("scripts/watch_cog_and_process.py", "scripts/selfserve_poller.py"):
            text = (ROOT / rel).read_text()
            self.assertIn("PIPELINE_REPO", text, rel)
            self.assertNotIn('REPO = "/Users/dad', text, rel)


class PlanTests(unittest.TestCase):
    def test_dispatch_defaults_are_dry(self):
        result = plan.decide("workflow_dispatch", "discover-dry-run", "true", "")
        self.assertEqual(result["mode"], "discover-dry-run")
        self.assertEqual(result["dry_run"], "true")
        self.assertEqual(result["needs_publish"], "false")

    def test_discover_mode_stays_dry_even_if_the_box_is_cleared(self):
        result = plan.decide("workflow_dispatch", "discover-dry-run", "false", "")
        self.assertEqual(result["dry_run"], "true")

    def test_weekly_submit_does_not_need_the_site_checkout(self):
        result = plan.decide("workflow_dispatch", "weekly", "false", "")
        self.assertEqual(result["needs_publish"], "false")
        self.assertEqual(result["dry_run"], "false")

    def test_catchup_for_real_publishes(self):
        result = plan.decide("workflow_dispatch", "catchup", "false", "")
        self.assertEqual(result, {"mode": "catchup", "dry_run": "false", "needs_publish": "true"})

    def test_catchup_dry_run_does_not_publish(self):
        result = plan.decide("workflow_dispatch", "catchup", "true", "")
        self.assertEqual(result["needs_publish"], "false")

    def test_sunday_and_monday_crons(self):
        sunday = plan.decide("schedule", "", "", "0 0 * * 1")
        self.assertEqual(sunday["mode"], "weekly")
        self.assertEqual(sunday["dry_run"], "false")
        self.assertEqual(sunday["needs_publish"], "false")
        winter_submit = plan.decide("schedule", "", "", "0 1 * * 1")
        self.assertEqual(winter_submit["mode"], "weekly")
        monday_9_cst = plan.decide("schedule", "", "", "0 15 * * 1")
        self.assertEqual(monday_9_cst["mode"], "catchup")
        self.assertEqual(monday_9_cst["needs_publish"], "true")

    def test_unknown_schedule_is_rejected(self):
        with self.assertRaises(SystemExit):
            plan.decide("schedule", "", "", "0 4 * * *")

    def test_cogwatch_hand_run_defaults_to_dry(self):
        result = plan.decide_cogwatch("workflow_dispatch", "true")
        self.assertEqual(result["dry_run"], "true")
        self.assertEqual(result["needs_publish"], "false")

    def test_cogwatch_schedule_is_a_real_run(self):
        result = plan.decide_cogwatch("schedule", "true")
        self.assertEqual(result["dry_run"], "false")
        self.assertEqual(result["needs_publish"], "true")


class PendingBatchTests(unittest.TestCase):
    def setUp(self):
        try:
            import weekly_ingest
        except Exception as exc:  # missing local deps, not a logic failure
            self.skipTest(f"weekly_ingest import failed: {exc}")
        self.w = weekly_ingest

    def test_merge_keeps_the_file_preacher_and_sorts_waits_last(self):
        recovered = [
            self.w.WorkItem("msgbatch_sunday", None, "anthropic"),
            self.w.WorkItem("msgbatch_late", "Ricky Alcantar", "anthropic"),
            self.w.WorkItem("msgbatch_waiting", None, "anthropic"),
        ]
        work = self.w.merge_work({"Chris Oswald": "msgbatch_sunday"}, recovered)
        self.assertEqual(
            [item.batch_id for item in work],
            ["msgbatch_sunday", "msgbatch_late", "msgbatch_waiting"],
        )
        sunday = work[0]
        self.assertEqual(sunday.preacher_name, "Chris Oswald")
        self.assertEqual(sunday.source, "file")

    def test_recovered_name_does_not_replace_the_file(self):
        recovered = [self.w.WorkItem("msgbatch_sunday", "Someone Else", "anthropic")]
        merged = self.w.merge_work({"Chris Oswald": "msgbatch_sunday"}, recovered)
        self.assertEqual(merged[0].preacher_name, "Chris Oswald")

    def test_request_total_uses_anthropic_count_fields(self):
        class Counts:
            canceled = 0
            errored = 1
            expired = 0
            processing = 2
            succeeded = 3

        class Batch:
            request_counts = Counts()

        self.assertEqual(self.w._request_total(Batch()), 6)

    def test_new_submit_does_not_drop_an_older_preacher(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            queue = Path(tmp)
            original = self.w.QUEUE_DIR
            self.w.QUEUE_DIR = queue
            try:
                (queue / "pending_batches.json").write_text(
                    '{"batches": {"Chris Oswald": "msgbatch_sunday"}, "processed": []}'
                )
                self.w._write_pending_state({"Ricky Alcantar": "msgbatch_monday"})
                saved = json.loads((queue / "pending_batches.json").read_text())
            finally:
                self.w.QUEUE_DIR = original
        self.assertEqual(saved["batches"]["Chris Oswald"], "msgbatch_sunday")
        self.assertEqual(saved["batches"]["Ricky Alcantar"], "msgbatch_monday")


class StuckSermonTests(unittest.TestCase):
    def test_fresh_audio_is_not_stuck(self):
        row = _sermon(created_at=(NOW - timedelta(hours=2)).isoformat())
        self.assertEqual(stuck.classify_sermon(row, set(), NOW), [])

    def test_old_audio_without_decomposition_is_stuck(self):
        problems = stuck.classify_sermon(_sermon(), set(), NOW)
        self.assertEqual(len(problems), 1)
        self.assertIn("has audio", problems[0])
        self.assertIn("not been decomposed", problems[0])

    def test_old_row_without_audio_is_not_stuck(self):
        row = _sermon(audio_url=None, hosted_audio_url=None)
        self.assertEqual(stuck.classify_sermon(row, set(), NOW), [])

    def test_decomposed_yesterday_with_four_resources_is_stuck(self):
        row = _sermon(decomposed_at=(NOW - timedelta(days=2)).isoformat(), last_rendered_at=NOW.isoformat())
        kinds = {"small_group_questions", "daily_readings", "family_card", "couples_guide"}
        problems = stuck.classify_sermon(row, kinds, NOW)
        self.assertEqual(len(problems), 1)
        self.assertIn("only 4 of 5", problems[0])

    def test_decomposed_but_never_rendered_is_stuck(self):
        row = _sermon(decomposed_at=(NOW - timedelta(days=2)).isoformat())
        kinds = {
            "small_group_questions", "daily_readings", "family_card",
            "couples_guide", "memory_verse",
        }
        problems = stuck.classify_sermon(row, kinds, NOW)
        self.assertEqual(len(problems), 1)
        self.assertIn("never rendered", problems[0])

    def test_just_decomposed_is_left_alone(self):
        row = _sermon(decomposed_at=(NOW - timedelta(hours=1)).isoformat())
        self.assertEqual(stuck.classify_sermon(row, set(), NOW), [])

    def test_finished_sermon_is_quiet(self):
        row = _sermon(
            decomposed_at=(NOW - timedelta(days=2)).isoformat(),
            last_rendered_at=(NOW - timedelta(days=2)).isoformat(),
        )
        kinds = {
            "small_group_questions", "daily_readings", "family_card",
            "couples_guide", "memory_verse",
        }
        self.assertEqual(stuck.classify_sermon(row, kinds, NOW), [])

    def test_failure_email_includes_the_run_link(self):
        subject, body = stuck.failure_message(
            "Weekly ingest",
            "https://github.com/coswald75/shepherds-guild-pipeline/actions/runs/1",
        )
        self.assertIn("failed", subject.lower())
        self.assertIn("actions/runs/1", body)
        self.assertIn("Chris,", body)
        self.assertNotIn("re_", body)

    def test_dry_run_failure_email_does_not_call_resend(self):
        env = os.environ.copy()
        env.pop("RESEND_API_KEY", None)
        env.pop("RESEND_FROM", None)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "check_stuck_sermons.py"),
                "--workflow-failure",
                "--dry-run",
                "--run-url",
                "https://github.com/coswald75/shepherds-guild-pipeline/actions/runs/99",
                "--workflow-name",
                "Weekly ingest",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("actions/runs/99", result.stdout)
        self.assertIn("DRY RUN", result.stdout)


if __name__ == "__main__":
    unittest.main()
