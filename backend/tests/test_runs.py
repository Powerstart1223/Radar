from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db.database import Database
from app.services.runs import RunService


class RunServicePromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.db = Database(self.base_dir / "project_radar.db")
        self.db.init()
        self.service = RunService(self.db, base_dir=self.base_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_review_command_uses_review_specific_prompt(self) -> None:
        command = self.service.display_command("codex", "review", str(self.base_dir))

        self.assertIn("review the current diff for bugs and regressions", command)

    def test_investigate_command_uses_root_cause_prompt(self) -> None:
        command = self.service.display_command("codex", "investigate", str(self.base_dir))

        self.assertIn("root-cause the highest-severity current problem", command)

    def test_ship_command_uses_ship_specific_prompt(self) -> None:
        command = self.service.display_command("codex", "ship", str(self.base_dir))

        self.assertIn("ship the current ready changes", command)


if __name__ == "__main__":
    unittest.main()
