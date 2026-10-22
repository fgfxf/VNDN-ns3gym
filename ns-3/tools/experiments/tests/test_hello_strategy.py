"""Execute actual hello/cache C++ branches for all four strategy settings.

This is a source-extraction unit probe plus static configuration guards, not a
SUMO/NDN end-to-end test. No production library or simulation is built. Set
HELLO_STRATEGY_EVIDENCE_DIR to preserve the probe, source identities and results.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
APPS = ROOT / "contrib/vndn-nn-rd/apps"
STATE = {"LocateX": 123.125, "LocateY": -4.5, "Speed": 8.25,
         "Acceleration": -0.5, "Angle": 359.75, "LaneIndex": 3, "NextRsu": 6}


def section(text, start, end, offset=0):
    begin = text.index(start, offset)
    finish = text.index(end, begin)
    return text[begin:finish]


def fixtures():
    # Payload expectations are explicit protocol examples, not an alternate
    # implementation of the production cache-delta algorithm.
    groups = [
        ("first-empty", True, ["/stale"], [
            ([], {"CsList": [], "CsUpdate": False}, False),
            ([], {"CsAdded": [], "CsRemoved": [], "CsUpdate": True}, True),
        ]),
        ("cache-changes", True, ["/stale", "/shared"], [
            (["/a", "/shared"], {"CsList": ["/a", "/shared"], "CsUpdate": False}, False),
            (["/a", "/shared"], {"CsAdded": [], "CsRemoved": [], "CsUpdate": True}, True),
            (["/a", "/b", "/shared"], {"CsAdded": ["/b"], "CsRemoved": [], "CsUpdate": True}, False),
            (["/b", "/shared"], {"CsAdded": [], "CsRemoved": ["/a"], "CsUpdate": True}, False),
            (["/c", "/shared"], {"CsAdded": ["/c"], "CsRemoved": ["/b"], "CsUpdate": True}, False),
            ([], {"CsAdded": [], "CsRemoved": ["/c", "/shared"], "CsUpdate": True}, False),
            ([], {"CsAdded": [], "CsRemoved": [], "CsUpdate": True}, True),
        ]),
        ("cache-disabled", False, ["/untouched"], [
            (["/ignored"], {}, False),
            (["/ignored2"], {}, False),
        ]),
    ]
    result = []
    for strategy in range(4):
        for name, participate, initial, steps in groups:
            rows = []
            for names, cache_fields, empty_delta in steps:
                expected = dict(STATE)
                if not (strategy == 3 and empty_delta):
                    expected.update(cache_fields)
                rows.append({"current_cs": names, "expected_payload": expected,
                             "expected_rsu_cs": names if participate else initial})
            result.append({"case": name, "strategy": strategy,
                           "participate": participate, "initial_rsu_cs": initial,
                           "state": STATE, "steps": rows})
    return result


PROBE = r'''
#include <nlohmann/json.hpp>
#include "vndn-rsu-strategy.h"
#include "vndn-handover-strategy.h"
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>
#define NS_LOG_DEBUG(expression) do { std::ostringstream sink; sink << expression; } while (false)
using namespace vanet;
using Json = nlohmann::json;
using Names = std::set<std::string>;
struct ActualObu {
  RsuForwardStrategy m_forwardStrategy = RsuForwardStrategy_NoForward;
  CacheStrategy m_cacheStrategy = CacheStrategy_Participate;
  bool m_registered = false;
  Names m_lastCsNames, currentCsFixture;
  Names GetCsNames() const { return currentCsFixture; }
  std::string Serialize(Json j) {
@@OBU@@
    return strContent;
  }
};
struct ActualRsu {
  std::map<int64_t, Names> m_vehicleToCs;
  std::map<std::string, std::set<int64_t>> m_csToVehicles;
  std::array<double, 6> receivedFeatures;
  void Receive(const std::string& jsonStr, int64_t obuNodeId) {
@@PARSE@@
@@FEATURES@@
    receivedFeatures = observation;
@@RSU@@
  }
};
void Seed(ActualRsu& rsu, int64_t vehicle, const Names& names) {
  rsu.m_vehicleToCs[vehicle] = names;
  for (const auto& name : names) rsu.m_csToVehicles[name].insert(vehicle);
}
Json Relations(const ActualRsu& rsu) {
  Json forward = Json::object(), reverse = Json::object();
  for (const auto& item : rsu.m_vehicleToCs)
    if (!item.second.empty()) forward[std::to_string(item.first)] = item.second;
  for (const auto& item : rsu.m_csToVehicles)
    if (!item.second.empty()) reverse[item.first] = item.second;
  return {{"vehicle_to_cs", forward}, {"cs_to_vehicles", reverse}};
}
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  std::ifstream input(argv[1]);
  if (!input) return 2;
  Json fixtures; input >> fixtures;
  Json results = Json::array();
  for (const auto& fixture : fixtures) {
    ActualObu obu;
    const int strategy = fixture.at("strategy");
    const bool participate = fixture.at("participate");
    obu.m_forwardStrategy = static_cast<RsuForwardStrategy>(strategy);
    obu.m_cacheStrategy = participate ? CacheStrategy_Participate : CacheStrategy_None;
    ActualRsu rsu;
    Seed(rsu, 7, fixture.at("initial_rsu_cs").get<Names>());
    Seed(rsu, 8, {"/shared", "/other"});
    unsigned stepNumber = 0;
    for (const auto& step : fixture.at("steps")) {
      ++stepNumber;
      obu.currentCsFixture = step.at("current_cs").get<Names>();
      const std::string wire = obu.Serialize(fixture.at("state"));
      const Json decoded = Json::parse(wire);
      const Json expected = step.at("expected_payload");
      rsu.Receive(wire, 7);
      ActualRsu expectedRsu;
      Seed(expectedRsu, 7, step.at("expected_rsu_cs").get<Names>());
      Seed(expectedRsu, 8, {"/shared", "/other"});
      results.push_back({
        {"case", fixture.at("case")}, {"strategy", strategy}, {"step", stepNumber},
        {"wire", wire}, {"decoded", decoded}, {"expected", expected},
        {"wire_matches_contract", wire == expected.dump(strategy == 3 ? -1 : 4)},
        {"rsu_relations", Relations(rsu)}, {"expected_rsu_relations", Relations(expectedRsu)},
        {"received_features", rsu.receivedFeatures},
        {"registered", obu.m_registered}, {"expected_registered", participate},
        {"last_cs", obu.m_lastCsNames},
        {"expected_last_cs", participate ? step.at("current_cs") : Json::array()}
      });
    }
  }
  std::cout << Json({{"steps", results.size()}, {"results", results}}).dump(2) << '\n';
  return 0;
}
'''


class HelloStrategyBehaviorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = os.environ.get("HELLO_STRATEGY_EVIDENCE_DIR")
        if directory:
            cls.evidence = Path(directory).resolve()
            cls.evidence.mkdir(parents=True, exist_ok=True)
        else:
            cls.temporary = tempfile.TemporaryDirectory(prefix="vndn-hello-strategy-")
            cls.addClassCleanup(cls.temporary.cleanup)
            cls.evidence = Path(cls.temporary.name)
        obu = (APPS / "vndn-obu.cc").read_text()
        rsu = (APPS / "vndn-rsu.cc").read_text()
        obu_start = obu.index("VndnObu::OnSyncSignalInterest (")
        rsu_start = rsu.index("VndnRsu::OnSyncSignalData (")
        bodies = {
            "OBU": section(obu, "  if (m_cacheStrategy == CacheStrategy_Participate)",
                           "\n  data->setContent", obu_start),
            "PARSE": section(rsu, "  nlohmann::json j;", "\n  // 从 VndnTag", rsu_start),
            "FEATURES": section(rsu, "  std::array<double, 6> observation =", "  auto &history", rsu_start),
            "RSU": section(rsu, '  if (j.contains ("CsUpdate"))',
                           "\n}\n\nvoid\nVndnRsu::OnTimeout", rsu_start),
        }
        cpp = PROBE
        for key, body in bodies.items():
            cpp = cpp.replace("@@" + key + "@@", body)
        source = cls.evidence / "probe.cc"
        source.write_text(cpp)
        fixture_path = cls.evidence / "fixtures.json"
        fixture_path.write_text(json.dumps(fixtures(), indent=2) + "\n")
        identities = {}
        for path in (APPS / "vndn-obu.cc", APPS / "vndn-rsu.cc",
                     APPS / "vndn-rsu-strategy.h", source, Path(__file__).resolve()):
            identities[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        (cls.evidence / "source-identities.json").write_text(json.dumps(identities, indent=2) + "\n")
        compiler = shutil.which("g++")
        if not compiler:
            raise RuntimeError("g++ is required for the actual-source hello behavior probe")
        executable = cls.evidence / "probe"
        command = [compiler, "-std=c++14", "-O0", "-I" + str(APPS),
                   "-I" + str(ROOT / "contrib/vndn-nn-rd/model"),
                   "-I" + str(ROOT / "src/json/single_include"),
                   str(source), "-o", str(executable)]
        build = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True, timeout=120)
        (cls.evidence / "compile.log").write_text(build.stdout)
        (cls.evidence / "compile.json").write_text(json.dumps(
            {"command": command, "exit_code": build.returncode}, indent=2) + "\n")
        if build.returncode:
            raise RuntimeError("Probe did not compile; this is not a valid behavior RED:\n" + build.stdout)
        run = subprocess.run([str(executable), str(fixture_path)], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True, timeout=30)
        (cls.evidence / "probe.stderr").write_text(run.stderr)
        (cls.evidence / "probe-results.json").write_text(run.stdout)
        if run.returncode:
            raise RuntimeError("Probe execution failed: " + run.stderr)
        cls.results = json.loads(run.stdout)["results"]
        if len(cls.results) != 44:
            raise RuntimeError("Expected 44 actual-source strategy/cache states")

    def test_strategy_specific_wire_format(self):
        for row in self.results:
            with self.subTest(strategy=row["strategy"], case=row["case"], step=row["step"]):
                self.assertTrue(row["wire_matches_contract"],
                                "Only strategy 3 uses compact JSON and omits empty deltas")

    def test_full_and_delta_payloads_preserve_contract(self):
        for row in self.results:
            with self.subTest(strategy=row["strategy"], case=row["case"], step=row["step"]):
                self.assertEqual(row["decoded"], row["expected"])

    def test_receiver_cache_relations_and_obu_state(self):
        for row in self.results:
            with self.subTest(strategy=row["strategy"], case=row["case"], step=row["step"]):
                self.assertEqual(row["rsu_relations"], row["expected_rsu_relations"])
                self.assertEqual(row["registered"], row["expected_registered"])
                self.assertEqual(row["last_cs"], row["expected_last_cs"])

    def test_all_model_features_and_next_rsu_preserved(self):
        expected_features = [STATE[key] for key in (
            "LocateX", "LocateY", "Speed", "Acceleration", "Angle", "LaneIndex")]
        for row in self.results:
            with self.subTest(strategy=row["strategy"], case=row["case"], step=row["step"]):
                self.assertEqual(row["received_features"], expected_features)
                self.assertEqual({key: row["decoded"][key] for key in STATE}, STATE)


class HelloStrategyWiringTest(unittest.TestCase):
    """Static guards: these do not substitute for three-scene runtime checks."""

    def test_app_attribute_propagates_to_obu_with_legacy_default(self):
        app = (APPS / "vndn-obu-app.h").read_text()
        self.assertIn('.AddAttribute ("RsuForwardStrategy"', app)
        begin = app.index('.AddAttribute ("RsuForwardStrategy"')
        attribute = app[begin:app.index('.AddAttribute (', begin + 1)]
        self.assertIn("EnumValue (vanet::RsuForwardStrategy_NoForward)", attribute)
        member = re.search(r"MakeEnumAccessor\s*\(\s*&VndnObuApp::(m_\w+)\s*\)", attribute)
        self.assertIsNotNone(member, "Strategy attribute must control an actual app member")
        self.assertRegex(app, r"setRsuForwardStrategy\s*\(\s*" + member.group(1) + r"\s*\)")
        for name in ("NoForward", "VTDF", "RealTimeVtdf", "NeuralNetwork"):
            self.assertIn("vanet::RsuForwardStrategy_" + name, attribute)
        obu_header = (APPS / "vndn-obu.h").read_text()
        self.assertRegex(obu_header, r"RsuForwardStrategy\s+m_forwardStrategy\s*=\s*RsuForwardStrategy_NoForward")
        obu_source = (APPS / "vndn-obu.cc").read_text()
        self.assertRegex(obu_source, r"VndnObu::setRsuForwardStrategy\s*\(\s*RsuForwardStrategy\s+strategy\s*\)\s*\{\s*m_forwardStrategy\s*=\s*strategy\s*;")

    def test_circle_and_shared_map_connect_actual_selected_strategy(self):
        for relative in ("scratch/vndn-circle-simulator/vndn-circle-main.cc",
                         "scratch/vndn-map-simulator-common.h"):
            with self.subTest(source=relative):
                source = (ROOT / relative).read_text()
                start = source.index("setupNewNode =")
                end = source.index("node->AddApplication", start) if "node->AddApplication" in source[start:] else source.index("newNode->AddApplication", start)
                creation = source[start:end]
                self.assertRegex(creation, r'SetAttribute\s*\(\s*"RsuForwardStrategy"\s*,\s*(?:ns3::)?EnumValue\s*\(\s*rsuForwardStrategy\s*\)\s*\)')


if __name__ == "__main__":
    unittest.main()
