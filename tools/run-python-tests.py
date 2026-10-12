"""Keep unittest progress on stdout so PowerShell logging preserves exit status."""
import argparse
import sys
import unittest

parser = argparse.ArgumentParser()
parser.add_argument('directory')
args = parser.parse_args()
suite = unittest.defaultTestLoader.discover(args.directory)
result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
