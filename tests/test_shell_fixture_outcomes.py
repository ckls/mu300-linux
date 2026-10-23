"""A shell fixture skip must not mask failures or add a GeneratorExit error."""
import gc
import unittest
from helpers import ShellTest


class FixtureOutcomes(unittest.TestCase):
    def test_skip_and_failure_keep_their_original_outcome(self):
        for skip in (True, False):
            class Fixture(ShellTest):
                def setUp(self):
                    self.shells = [['fixture-only']]

                def tearDown(self):
                    pass

                def runTest(self):
                    for shell in self.each_shell():
                        if skip:
                            self.skipTest('dependency unavailable')
                        self.fail('actual assertion failure')

            result = unittest.TestResult()
            Fixture().run(result)
            gc.collect()
            self.assertEqual(len(result.skipped), int(skip))
            self.assertEqual(len(result.failures), int(not skip))
            self.assertEqual(result.errors, [])
