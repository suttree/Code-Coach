import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from cc.core import validate


class ExampleTests(unittest.TestCase):
    def test_example_launches_outside_checkout_without_pythonpath(self):
        launcher = Path(__file__).resolve().parents[1] / "cc"
        with tempfile.TemporaryDirectory() as directory:
            env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            result = subprocess.run([str(launcher), "--example", "--json"], cwd=directory,
                                    env=env, capture_output=True, text=True, check=True)
        review = json.loads(result.stdout)
        self.assertTrue(review["example"])
        self.assertEqual(len(review["report"]["points"]), 2)
        self.assertEqual({p["kind"] for p in review["report"]["points"]}, {"discussion", "strength"})
        validate(review["report"], review["packet"])
