"""Execute actual four-strategy hello encoding and RSU state-update branches.

NN uses versioned lossless VNH1/CBOR; baselines retain their legacy JSON bytes.
This standalone source-extraction probe is not a SUMO/NDN end-to-end test and
never builds a production library. Set HELLO_STRATEGY_EVIDENCE_DIR to preserve
probe, input, exact source snapshots, source identities and execution results.
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
    # Exercise binary preservation of extreme doubles, signed zero, integer
    # fields, and escaped/Unicode cache names through the actual source paths.
    states = [dict(STATE), dict(STATE), dict(STATE)]
    states[0].update(LocateX=2.2250738585072014e-308,
                     LocateY=-1.7976931348623157e308, Speed=5e-324,
                     Acceleration=-0.0, Angle=0.12345678901234568)
    states[1].update(LocateX=1.7976931348623157e308,
                     LocateY=1.2345678901234567, Speed=0.0,
                     Acceleration=-2.2250738585072014e-308,
                     Angle=-0.0, LaneIndex=-1, NextRsu=-1)
    for strategy in range(4):
        for index, state in enumerate(states):
            names = sorted(['/缓存/空 格/"escape\\', '/δ/车辆'])
            expected = dict(state)
            expected.update(CsList=names, CsUpdate=False)
            result.append({
                "case": "exact-double-unicode-" + str(index),
                "strategy": strategy, "participate": True,
                "initial_rsu_cs": ["/stale"], "state": state,
                "steps": [{"current_cs": names, "expected_payload": expected,
                           "expected_rsu_cs": names}],
            })
    return result


PROBE = r'''
#include "src/json/single_include/nlohmann/json.hpp"
#include "vndn-rsu-strategy.h"
#include "vndn-handover-strategy.h"
@@HELPER@@
#include <array>
#include <cmath>
#include <cstring>
#include <deque>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <vector>
#define NS_LOG_DEBUG(expression) do { std::ostringstream sink; sink << expression; } while(false)
using namespace vanet;
using Json = nlohmann::json;
using Names = std::set<std::string>;
namespace ns3 {
struct Time {
 enum Unit { MS };
 uint64_t ToInteger(Unit) const { return 1234; }
 uint64_t GetNanoSeconds() const { return 1234000000; }
};
struct Simulator { static Time Now() { return {}; } };
}
struct Node { uint32_t GetId() const { return 2; } };
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
 std::map<int64_t, uint64_t> m_vehicleLastReplyMs;
 std::map<int64_t, int64_t> m_vehicleNextRsu, m_resolvedVehicleRsu;
 std::map<int64_t, std::deque<std::array<double,6>>> m_vehicleObservationHistory;
 std::map<int64_t, std::deque<uint64_t>> m_vehicleObservationReceiveTimes;
 uint32_t m_neuralSequenceLength = 10;
 std::shared_ptr<Node> m_thisNode = std::make_shared<Node>();
 Json decoded;
 unsigned accepted = 0;
 void Receive(const std::string& jsonStr, int64_t obuNodeId) {
@@PARSE@@
@@STATE@@
@@CACHE@@
 decoded = j;
 ++accepted;
 }
};
void Seed(ActualRsu& rsu, int64_t vehicle, const Names& names) {
 rsu.m_vehicleToCs[vehicle] = names;
 for(const auto& n : names) rsu.m_csToVehicles[n].insert(vehicle);
}
Json Relations(const ActualRsu& rsu) {
 Json f = Json::object(), r = Json::object();
 for(const auto& p : rsu.m_vehicleToCs) if(!p.second.empty()) f[std::to_string(p.first)] = p.second;
 for(const auto& p : rsu.m_csToVehicles) if(!p.second.empty()) r[p.first] = p.second;
 return {{"f",f},{"r",r}};
}
Json State(const ActualRsu& rsu) {
 return {{"relations",Relations(rsu)}, {"accepted",rsu.accepted},
 {"reply",rsu.m_vehicleLastReplyMs},{"next",rsu.m_vehicleNextRsu},
 {"resolved",rsu.m_resolvedVehicleRsu},{"history",rsu.m_vehicleObservationHistory},
 {"times",rsu.m_vehicleObservationReceiveTimes},{"decoded",rsu.decoded}};
}
std::string Envelope(const Json& value, const std::string& magic="VNH1") {
 const auto bytes = Json::to_cbor(value);
 return magic + std::string(bytes.begin(),bytes.end());
}
bool SameBits(double a, double b) { return std::memcmp(&a,&b,sizeof(double)) == 0; }
int main(int argc, char** argv) {
 if(argc!=2) return 2;
 std::ifstream input(argv[1]); Json fixtures; input >> fixtures;
 Json rows=Json::array(), rejected=Json::array();
 unsigned failures=0, checks=0;
 auto check = [&](Json& row,const std::string& name,bool value){row[name]=value;++checks;if(!value)++failures;};
 for(const auto& fixture:fixtures) {
  ActualObu obu; ActualRsu rsu;
  int strategy=fixture.at("strategy"); bool participate=fixture.at("participate");
  obu.m_forwardStrategy=static_cast<RsuForwardStrategy>(strategy);
  obu.m_cacheStrategy=participate ? CacheStrategy_Participate : CacheStrategy_None;
  Seed(rsu,7,fixture.at("initial_rsu_cs").get<Names>()); Seed(rsu,8,{"/shared","/other"});
  unsigned step=0;
  for(const auto& item:fixture.at("steps")) {
   obu.currentCsFixture=item.at("current_cs").get<Names>();
   Json expected=item.at("expected_payload");
   std::string wire=obu.Serialize(fixture.at("state"));
   rsu.Receive(wire,7);
   Json row={{"case",fixture.at("case")},{"strategy",strategy},{"step",++step},
             {"wire_bytes",wire.size()},{"old_compact_bytes",expected.dump().size()}};
   check(row,"wire_contract",strategy==3 ? wire.compare(0,4,"VNH1")==0 : wire==expected.dump(4));
   check(row,"decoded_exact",rsu.decoded==expected);
   bool features=true; const char* keys[]={"LocateX","LocateY","Speed","Acceleration","Angle","LaneIndex"};
   if(rsu.m_vehicleObservationHistory[7].empty()) features=false;
   else for(size_t i=0;i<6;++i) features &= SameBits(rsu.m_vehicleObservationHistory[7].back()[i],expected.at(keys[i]).get<double>());
   check(row,"feature_bits_exact",features);
   check(row,"next_exact",rsu.m_vehicleNextRsu[7]==expected.at("NextRsu").get<int64_t>());
   ActualRsu expectedRsu;Seed(expectedRsu,7,item.at("expected_rsu_cs").get<Names>());Seed(expectedRsu,8,{"/shared","/other"});
   check(row,"cache_relations_exact",Relations(rsu)==Relations(expectedRsu));
   check(row,"registered_exact",obu.m_registered==participate);
   check(row,"last_cs_exact",Json(obu.m_lastCsNames)==(participate?item.at("current_cs"):Json::array()));
   rows.push_back(row);
  }
 }
 Json six=Json::array({1.25,-2.5,30.0,-0.25,359.75,2});
 Json valid=Json::array({1,six,6,Json::object()});
 std::vector<std::pair<std::string,std::string>> bad;
 auto add=[&](const std::string& name,const Json& p){bad.emplace_back(name,Envelope(p));};
 Json p=valid;p[0]=2;add("unknown-payload-version",p);
 p=valid;p[0]=0;add("zero-payload-version",p);
 p=valid;p[0]=-1;add("negative-payload-version",p);
 p=valid;p[0]=true;add("boolean-payload-version",p);
 bad.emplace_back("unknown-magic-version",Envelope(valid,"VNH2"));
 bad.emplace_back("truncated-magic","VNH");bad.emplace_back("empty-cbor","VNH1");
 auto truncated=Envelope(valid);truncated.pop_back();bad.emplace_back("truncated-cbor",truncated);
 bad.emplace_back("trailing-cbor",Envelope(valid)+"x");
 p=valid;p.push_back(0);add("wrong-envelope-size",p);
 p=valid;p[0]=1.0;add("floating-version",p);
 p=valid;p[1].erase(5);add("short-state",p);
 p=valid;p[1][0]="1";add("string-number",p);
 p=valid;p[1][1]=std::numeric_limits<double>::infinity();add("infinite-state",p);
 p=valid;p[1][2]=std::numeric_limits<double>::quiet_NaN();add("nan-state",p);
 p=valid;p[1][5]=2.5;add("fractional-lane",p);
 p=valid;p[1][5]=std::numeric_limits<uint64_t>::max();add("overflow-lane",p);
 p=valid;p[2]=2.5;add("fractional-next",p);
 p=valid;p[2]=std::numeric_limits<uint64_t>::max();add("overflow-next",p);
 p=valid;p[3]={{"CsUpdate",true},{"CsAdded",Json::array({42})}};add("invalid-cache-name",p);
 p=valid;p[3]={{"CsUpdate",1}};add("invalid-cache-mode",p);
 p=valid;p[3]={{"CsAdded",Json::array({"/a"})}};add("cache-missing-mode",p);
 p=valid;p[3]={{"CsUpdate",false},{"CsAdded",Json::array()}};add("mixed-cache-mode",p);
 p=valid;p[3]={{"Unexpected",false}};add("unknown-cache-key",p);
 for(const auto& item:bad) {
  ActualRsu rsu; Seed(rsu,7,{"/before"});rsu.Receive(R"({"LocateX":1,"LocateY":2,"Speed":3,"Acceleration":4,"Angle":5,"LaneIndex":1,"NextRsu":2})",7);
  Json before=State(rsu),row={{"case",item.first}};bool threw=false;
  try {rsu.Receive(item.second,7);} catch(...) {threw=true;}
  check(row,"does_not_throw",!threw);check(row,"state_unchanged",State(rsu)==before);rejected.push_back(row);
 }
 // Versioned input must be accepted, not merely rejected like all binary data.
 ActualRsu rsu;rsu.Receive(Envelope(valid),7);Json accept=Json::object();
 check(accept,"valid_binary_accepted",rsu.accepted==1);
 std::cout<<Json({{"checks",checks},{"failures",failures},{"states",rows},{"malformed",rejected},{"accept",accept}}).dump(2)<<'\n';
 return failures?1:0;
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
        # The old implementation deliberately compiles without the new header.
        # Its actual JSON encoder then fails the VNH1 behavior assertions.
        helper = APPS / "vndn-hello-wire.h"
        bodies = {
            "OBU": section(obu, "  if (m_cacheStrategy == CacheStrategy_Participate)",
                           "\n  data->setContent", obu_start),
            "PARSE": section(rsu, "  nlohmann::json j;", "\n  // 从 VndnTag", rsu_start),
            "STATE": section(rsu, "  // 更新车辆最后回复时间戳", "\n  // 补救 Data", rsu_start),
            "CACHE": section(rsu, '  if (j.contains ("CsUpdate"))',
                             "\n  // Passive table occupancy observation", rsu_start),
            "HELPER": '#include "vndn-hello-wire.h"' if helper.exists() else "",
        }
        cpp = PROBE
        for key, body in bodies.items():
            cpp = cpp.replace("@@" + key + "@@", body)
        source = cls.evidence / "probe.cc"
        source.write_text(cpp)
        fixture_path = cls.evidence / "fixtures.json"
        fixture_path.write_text(json.dumps(fixtures(), ensure_ascii=False, indent=2) + "\n")
        snapshots = cls.evidence / "source"
        snapshots.mkdir(exist_ok=True)
        identities = {}
        inputs = [APPS / "vndn-obu.cc", APPS / "vndn-rsu.cc",
                  APPS / "vndn-rsu-strategy.h", source, Path(__file__).resolve()]
        if helper.exists():
            inputs.append(helper)
        for path in inputs:
            identities[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            if path != source:
                shutil.copyfile(str(path), str(snapshots / path.name))
        (cls.evidence / "source-identities.json").write_text(json.dumps(identities, indent=2) + "\n")
        compiler = shutil.which("g++")
        if not compiler:
            raise RuntimeError("g++ is required for the actual-source hello behavior probe")
        executable = cls.evidence / "probe"
        command = [compiler, "-std=c++14", "-O0", "-I" + str(APPS),
                   "-I" + str(ROOT / "contrib/vndn-nn-rd/model"),
                   "-I" + str(ROOT), str(source), "-o", str(executable)]
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
        (cls.evidence / "run.json").write_text(json.dumps(
            {"command": [str(executable), str(fixture_path)],
             "exit_code": run.returncode}, indent=2) + "\n")
        if run.returncode not in (0, 1):
            raise RuntimeError("Probe execution failed: " + run.stderr)
        report = json.loads(run.stdout)
        if (len(report["states"]) != 56 or len(report["malformed"]) != 24 or
                report["checks"] != 441):
            raise RuntimeError("Expected 56 actual-source states and 24 malformed payloads / 441 checks")
        if run.returncode != int(report["failures"] != 0):
            raise RuntimeError("Probe exit status disagrees with its behavior-check results")
        cls.results = report["states"]
        cls.malformed = report["malformed"]
        cls.acceptance = report["accept"]

    def test_strategy_specific_wire_format(self):
        for row in self.results:
            with self.subTest(strategy=row["strategy"], case=row["case"], step=row["step"]):
                self.assertTrue(row["wire_contract"],
                                "Only strategy 3 uses VNH1; baseline JSON bytes stay unchanged")

    def test_full_and_delta_payloads_preserve_contract(self):
        for row in self.results:
            with self.subTest(strategy=row["strategy"], case=row["case"], step=row["step"]):
                self.assertTrue(row["decoded_exact"])

    def test_receiver_cache_relations_and_obu_state(self):
        for row in self.results:
            with self.subTest(strategy=row["strategy"], case=row["case"], step=row["step"]):
                self.assertTrue(row["cache_relations_exact"])
                self.assertTrue(row["registered_exact"])
                self.assertTrue(row["last_cs_exact"])

    def test_all_model_features_and_next_rsu_preserved(self):
        for row in self.results:
            with self.subTest(strategy=row["strategy"], case=row["case"], step=row["step"]):
                self.assertTrue(row["feature_bits_exact"], "Six double features must be bit-identical")
                self.assertTrue(row["next_exact"])

    def test_valid_binary_input_is_accepted(self):
        self.assertTrue(self.acceptance["valid_binary_accepted"])

    def test_malformed_binary_preserves_all_receiver_state(self):
        for row in self.malformed:
            with self.subTest(case=row["case"]):
                self.assertTrue(row["does_not_throw"])
                self.assertTrue(row["state_unchanged"],
                                "Rejected payload must not mutate registration, history or cache")


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
