from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from hpc_tools.capabilities import (
    CAPABILITY_LEVELS,
    CAPABILITY_SCOPES,
    POLICY_VERSION,
    CapabilityLevel,
    CapabilityPolicyError,
    intersect_policies,
    narrow_policy,
    parse_capability_policy,
)


class CapabilityPolicyTests(unittest.TestCase):
    def test_parses_every_capability_level(self) -> None:
        for level in CAPABILITY_LEVELS:
            with self.subTest(level=level.value):
                policy = self._policy(max_level=level.value)
                self.assertIs(policy.max_level, level)

    def test_defaults_are_immutable_and_grant_no_scopes_or_roots(self) -> None:
        policy = self._policy()

        self.assertEqual(policy.scopes, ())
        self.assertEqual(policy.remote_roots.list, ())
        self.assertEqual(policy.remote_roots.read, ())
        self.assertEqual(policy.remote_roots.write, ())
        self.assertEqual(policy.remote_roots.delete, ())
        self.assertEqual(policy.remote_roots.install, ())
        with self.assertRaises(FrozenInstanceError):
            policy.max_level = CapabilityLevel.JOB_LIFECYCLE  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            policy.remote_roots.read = ("/project",)  # type: ignore[misc]

    def test_parses_and_canonicalizes_scopes_and_roots(self) -> None:
        policy = self._policy(
            scopes=["job.validate", "accounting.read"],
            remote_roots={
                "list": ["$VSC_DATA/Projects", "/project/group"],
                "read": ["~/source"],
                "write": ["${SCRATCH}/jobs"],
            },
        )

        self.assertEqual(policy.scopes, ("accounting.read", "job.validate"))
        self.assertEqual(
            policy.remote_roots.list,
            ("$VSC_DATA/Projects", "/project/group"),
        )
        self.assertEqual(policy.remote_roots.read, ("~/source",))
        self.assertEqual(policy.remote_roots.write, ("${SCRATCH}/jobs",))

    def test_rejects_missing_or_invalid_required_fields(self) -> None:
        cases = (
            ({"max_level": "profile-context"}, "must define version"),
            ({"version": POLICY_VERSION}, "must define max_level"),
            ({"version": True, "max_level": "profile-context"}, "version must"),
            ({"version": 2, "max_level": "profile-context"}, "version must"),
            ({"version": POLICY_VERSION, "max_level": "C0"}, "unknown capability"),
        )
        for raw, message in cases:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(CapabilityPolicyError, message):
                    parse_capability_policy(raw, profile="cluster")

    def test_rejects_unknown_policy_and_root_keys(self) -> None:
        with self.assertRaisesRegex(CapabilityPolicyError, "unknown key.*ceiling"):
            self._policy(ceiling="job-lifecycle")
        with self.assertRaisesRegex(CapabilityPolicyError, "unknown key.*execute"):
            self._policy(remote_roots={"execute": ["/project"]})

    def test_rejects_malformed_and_unknown_scopes(self) -> None:
        with self.assertRaisesRegex(CapabilityPolicyError, "list of strings"):
            self._policy(scopes="job.validate")
        with self.assertRaisesRegex(CapabilityPolicyError, "duplicates"):
            self._policy(scopes=["job.validate", "job.validate"])
        with self.assertRaisesRegex(CapabilityPolicyError, "unknown scope.*job.launch"):
            self._policy(scopes=["job.launch"])

    def test_recognizes_the_documented_scope_vocabulary(self) -> None:
        policy = self._policy(scopes=list(reversed(CAPABILITY_SCOPES)))
        self.assertEqual(policy.scopes, tuple(sorted(CAPABILITY_SCOPES)))

    def test_rejects_malformed_root_lists(self) -> None:
        with self.assertRaisesRegex(CapabilityPolicyError, "list of strings"):
            self._policy(remote_roots={"read": "/project"})
        with self.assertRaisesRegex(CapabilityPolicyError, "duplicates"):
            self._policy(remote_roots={"read": ["/project", "/project"]})

    def test_rejects_unsafe_or_ambiguous_root_forms(self) -> None:
        invalid_roots = (
            "relative/path",
            "/",
            "/project/../other",
            "/project//other",
            "/project/",
            "/project/*",
            "$(pwd)/project",
            "/project/$OTHER",
            "$9INVALID/project",
            " ~/project",
        )
        for root in invalid_roots:
            with self.subTest(root=root):
                with self.assertRaises(CapabilityPolicyError):
                    self._policy(remote_roots={"read": [root]})

    def test_narrowing_can_only_lower_the_level(self) -> None:
        policy = self._policy(
            max_level="job-inspection",
            scopes=["job.validate"],
            remote_roots={"read": ["/project"]},
        )

        lower = narrow_policy(policy, "cluster-discovery")
        higher_request = narrow_policy(policy, "job-lifecycle")

        self.assertIs(lower.max_level, CapabilityLevel.CLUSTER_DISCOVERY)
        self.assertEqual(lower.scopes, policy.scopes)
        self.assertEqual(lower.remote_roots, policy.remote_roots)
        self.assertIs(higher_request, policy)
        self.assertIs(narrow_policy(policy, None), policy)

    def test_intersection_never_unions_scopes_or_roots(self) -> None:
        profile = self._policy(
            max_level="job-lifecycle",
            scopes=["job.validate", "accounting.read"],
            remote_roots={"read": ["/project", "/shared"], "write": ["/project"]},
        )
        preset = self._policy(
            max_level="job-inspection",
            scopes=["job.validate", "remote-filesystem.read"],
            remote_roots={"read": ["/shared", "/preset"], "write": ["/preset"]},
        )

        effective = intersect_policies(profile, preset)

        self.assertIs(effective.max_level, CapabilityLevel.JOB_INSPECTION)
        self.assertEqual(effective.scopes, ("job.validate",))
        self.assertEqual(effective.remote_roots.read, ("/shared",))
        self.assertEqual(effective.remote_roots.write, ())

    def test_public_summary_uses_plain_sorted_data(self) -> None:
        policy = self._policy(
            scopes=["job.validate", "accounting.read"],
            remote_roots={"read": ["/project"]},
        )

        self.assertEqual(
            policy.public_summary(),
            {
                "version": 1,
                "max_level": "profile-context",
                "scopes": ["accounting.read", "job.validate"],
                "remote_roots": {
                    "list": [],
                    "read": ["/project"],
                    "write": [],
                    "delete": [],
                    "install": [],
                },
            },
        )

    def _policy(self, **updates: object):
        raw = {
            "version": POLICY_VERSION,
            "max_level": "profile-context",
        }
        raw.update(updates)
        return parse_capability_policy(raw, profile="cluster")


if __name__ == "__main__":
    unittest.main()
