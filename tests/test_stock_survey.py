"""The source survey must not confuse commented rows or unresolved options with physics."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('stock_survey',
    Path(__file__).resolve().parents[1] / 'tools/survey-stock-vehicles.py')
survey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)


class StockSurveyTests(unittest.TestCase):
    def test_comments_defaults_inline_and_part_isolation(self):
        source = '''{
          // "chosen": {"nodes": [["id"], ["wrong"]]}
          "other": {"nodes": [["id"], ["other"]]},
          "chosen": {"nodes": [
            ["id", "posX"]
            {"nodeWeight": 5.5},
            // ["commented", 0],
            ["a", 0],
            ["b", 1, {"nodeWeight": 2}],
            /* braces } ] and commas are not data */
            ["c", 2],
          ]}
        }'''
        rows = survey.declarations(survey.table(source, 'chosen', 'nodes'))
        self.assertEqual([r['values']['id'] for r in rows], ['a', 'b', 'c'])
        self.assertEqual([r['values']['nodeWeight'] for r in rows], [5.5, 2, 5.5])
        self.assertEqual(rows[0]['line'], 8)

    def test_option_only_wheel_and_expressions_are_not_generated_nodes(self):
        source = '{"tire":{"pressureWheels":[["name"],{"nodeWeight":0.19,"pressurePSI":"$pressure","formula":"$=a[0]"}]}}'
        raw = survey.table(source, 'tire', 'pressureWheels')
        self.assertEqual(survey.declarations(raw), [])
        self.assertEqual(raw[-1][1]['pressurePSI'], '$pressure')

    def test_columns_and_missing_parts_fail_explicitly(self):
        with self.assertRaises(ValueError):
            survey.table('{}', 'missing', 'nodes')
        with self.assertRaises(ValueError):
            survey.declarations([(1, ['id']), (2, ['a', 42])])


if __name__ == '__main__':
    unittest.main()
