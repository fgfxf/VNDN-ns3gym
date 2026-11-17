import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('power_campaign',Path(__file__).resolve().parents[1]/'spider_power_campaign.py')
campaign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(campaign)


class PowerCampaignTests(unittest.TestCase):
    def test_complete_matrix_has_no_duplicates_or_missing_strategy(self):
        tasks = campaign.tasks('coarse',[13,17,18,19,20],[23017,23018])
        self.assertEqual(len(tasks),40)
        self.assertEqual(len({t['id'] for t in tasks}),40)
        for power in (13,17,18,19,20):
            for seed in (23017,23018):
                self.assertEqual({t['strategy'] for t in tasks if t['power_dbm']==power and t['seed']==seed},set(range(4)))

    def test_selection_prefers_declared_score_not_last_or_highest_power(self):
        values = [dict(power_dbm=18,selection_score=[1,1,6,.8,0,-500,-600,-18]),
                  dict(power_dbm=20,selection_score=[0,1,6,.9,0,-400,-500,-20])]
        self.assertEqual(campaign.choose(values)['power_dbm'],18)
        self.assertEqual(campaign.choose(values[::-1])['power_dbm'],18)

    def test_refinement_is_bounded_and_stops_when_goal_already_met(self):
        self.assertEqual(campaign.fine_powers(dict(power_dbm=19,meets_goal=False)),[18.5,19.5])
        self.assertEqual(campaign.fine_powers(dict(power_dbm=19,meets_goal=True)),[])
        self.assertEqual(len(campaign.tasks('confirmation',[19],[93001,93002,93003,93004,93005])),20)


if __name__=='__main__':
    unittest.main()
