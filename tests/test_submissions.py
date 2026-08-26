from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest

from hpc_tools import submissions


class SubmissionDatabaseTests(unittest.TestCase):
    def test_parse_sbatch_submission_with_cluster(self) -> None:
        job_id, cluster = submissions.parse_sbatch_submission(
            "Submitted batch job 60351238 on cluster wice\n"
        )

        self.assertEqual(job_id, "60351238")
        self.assertEqual(cluster, "wice")

    def test_event_replay_distinguishes_active_from_closed(self) -> None:
        events = [
            {
                "event": "submitted",
                "run_id": "mindwell-run",
                "profile": "genius",
                "job_id": "1",
                "cluster": "mindwell",
                "jobscript": "job.slurm",
                "remote_directory": "$VSC_DATA/Projects/demo",
            },
            {
                "event": "observed",
                "run_id": "mindwell-run",
                "state": "PENDING",
            },
            {
                "event": "submitted",
                "run_id": "wice-run",
                "profile": "genius",
                "job_id": "2",
                "cluster": "wice",
                "jobscript": "job.slurm",
                "remote_directory": "$VSC_DATA/Projects/demo",
            },
            {
                "event": "observed",
                "run_id": "wice-run",
                "state": "COMPLETED",
            },
            {"event": "results_collected", "run_id": "wice-run"},
            {"event": "analysed", "run_id": "wice-run"},
            {"event": "closed", "run_id": "wice-run"},
        ]

        active = submissions.active_records(events)

        self.assertEqual([record.run_id for record in active], ["mindwell-run"])
        self.assertEqual(active[0].latest_state, "PENDING")
        self.assertEqual(active[0].action, "observe")

    def test_completed_record_requires_collection_then_analysis(self) -> None:
        events = [
            {
                "event": "submitted",
                "run_id": "run-1",
                "profile": "genius",
                "job_id": "1",
                "cluster": "wice",
                "jobscript": "job.slurm",
                "remote_directory": "$VSC_DATA/Projects/demo",
            },
            {"event": "observed", "run_id": "run-1", "state": "COMPLETED"},
        ]

        record = submissions.records_from_events(events)[0]
        self.assertEqual(record.action, "collect")

        events.append({"event": "results_collected", "run_id": "run-1"})
        record = submissions.records_from_events(events)[0]
        self.assertEqual(record.action, "analyse")

    def test_cancellation_request_is_audited_without_claiming_cancelled_state(self) -> None:
        events = [
            {
                "event": "submitted",
                "run_id": "run-1",
                "profile": "genius",
                "job_id": "123",
                "cluster": "wice",
                "jobscript": "job.slurm",
                "remote_directory": "$VSC_DATA/Projects/demo",
            },
            {"event": "observed", "run_id": "run-1", "state": "RUNNING"},
        ]
        record = submissions.records_from_events(events)[0]
        events.append(
            submissions.cancel_requested_event(
                record,
                requested_job_id="123",
                cancel_command="scancel -M wice 123",
                reason="superseded",
            )
        )

        refreshed = submissions.records_from_events(events)[0]

        self.assertEqual(refreshed.latest_event, "cancel_requested")
        self.assertEqual(refreshed.latest_state, "RUNNING")
        self.assertEqual(refreshed.action, "observe")
        self.assertEqual(events[-1]["reason"], "superseded")
        self.assertEqual(events[-1]["requested_job_id"], "123")

    def test_active_records_for_job_matches_profile_job_and_cluster(self) -> None:
        events = [
            {
                "event": "submitted",
                "run_id": cluster,
                "profile": "genius",
                "job_id": "123",
                "cluster": cluster,
                "jobscript": "job.slurm",
                "remote_directory": ".",
            }
            for cluster in ("wice", "mindwell")
        ]

        records = submissions.active_records_for_job(
            events,
            profile="genius",
            job_id="123_7",
            cluster="wice",
        )

        self.assertEqual([record.run_id for record in records], ["wice"])

    def test_closed_run_stays_hidden_even_if_later_metadata_events_exist(self) -> None:
        events = [
            {
                "event": "submitted",
                "run_id": "run-1",
                "profile": "genius",
                "job_id": "1",
                "cluster": "wice",
                "jobscript": "job.slurm",
                "remote_directory": "$VSC_DATA/Projects/demo",
            },
            {"event": "observed", "run_id": "run-1", "state": "COMPLETED"},
            {"event": "results_collected", "run_id": "run-1"},
            {"event": "analysed", "run_id": "run-1"},
            {"event": "closed", "run_id": "run-1", "reason": "done"},
            {"event": "analysed", "run_id": "run-1", "path": "job.out"},
        ]

        record = submissions.records_from_events(events)[0]
        self.assertEqual(record.action, "closed")
        self.assertEqual(submissions.active_records(events), [])

    def test_append_and_read_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "submissions.sqlite3"

            submissions.append_event(
                {"event": "closed", "run_id": "run-1", "reason": "done"},
                path=database_path,
            )

            events = submissions.read_events(database_path)
            self.assertEqual(events[0]["event"], "closed")
            self.assertEqual(events[0]["reason"], "done")
            self.assertIn("timestamp", events[0])

    def test_database_has_versioned_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "submissions.sqlite3"
            submissions.append_event(
                {"event": "submitted", "run_id": "run-1"},
                path=database_path,
            )

            with sqlite3.connect(database_path) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                count = connection.execute(
                    "SELECT COUNT(*) FROM submission_events"
                ).fetchone()[0]
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            mode = stat.S_IMODE(database_path.stat().st_mode)

        self.assertEqual(submissions.SCHEMA_VERSION, version)
        self.assertEqual(1, count)
        self.assertEqual("delete", journal_mode)
        self.assertEqual(0o600, mode)

    def test_append_events_is_atomic_when_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "submissions.sqlite3"

            with self.assertRaisesRegex(ValueError, "non-empty 'run_id'"):
                submissions.append_events(
                    [
                        {"event": "submitted", "run_id": "run-1"},
                        {"event": "observed"},
                    ],
                    path=database_path,
                )

            self.assertFalse(database_path.exists())

    def test_concurrent_event_appends_are_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "submissions.sqlite3"
            def append(index: int) -> None:
                submissions.append_event(
                    {"event": "submitted", "run_id": f"run-{index}"},
                    path=database_path,
                )

            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(append, range(20)))

            events = submissions.read_events(database_path)

        self.assertEqual(20, len(events))
        self.assertEqual(
            {f"run-{index}" for index in range(20)},
            {event["run_id"] for event in events},
        )

    def test_unknown_database_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "submissions.sqlite3"
            with sqlite3.connect(database_path) as connection:
                connection.execute("PRAGMA user_version = 99")

            with self.assertRaisesRegex(ValueError, "unsupported.*version 99"):
                submissions.read_events(database_path)

    def test_parse_sacct_observation_for_array_job(self) -> None:
        state, exit_code, elapsed = submissions.parse_sacct_observation(
            "60351238_4|COMPLETED|0:0|00:02:31\n"
            "60351238_4.batch|COMPLETED|0:0|00:02:31\n",
            "60351238",
        )

        self.assertEqual(state, "COMPLETED")
        self.assertEqual(exit_code, "0:0")
        self.assertEqual(elapsed, "00:02:31")


if __name__ == "__main__":
    unittest.main()
