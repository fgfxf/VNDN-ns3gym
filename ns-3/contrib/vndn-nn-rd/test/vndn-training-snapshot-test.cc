#include "ns3/test.h"
#include "ns3/vndn-experiment-recorder.h"
#include "ns3/vndn-rsu-app.h"
#include "ns3/vndn-l3-experiment-tracer.h"
#include "ns3/vndn-rsu-forwarding-policy.h"
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/ndnSIM-module.h"
#include <ndn-cxx/lp/vndn-tag.hpp>
#include <ndn-cxx/util/signal/scoped-connection.hpp>
#include "../src/json/single_include/nlohmann/json.hpp"

#include <array>
#include <fstream>
#include <limits>
#include <vector>
#include <sstream>
#include <sys/stat.h>

namespace {
using Json = nlohmann::json;
using Recorder = vanet::VndnExperimentRecorder;

class TrainingSnapshotLedgerTest : public ns3::TestCase
{
public:
  TrainingSnapshotLedgerTest ()
    : TestCase ("Passive snapshots retain multi-source observations and diagnose duplicate or invalid inputs") {}

  void DoRun () override
  {
    Recorder::Config config;
    config.outputDirectory = CreateTempDirFilename ("");
    config.scenario = "circle";
    config.runId = "snapshot-fixture";
    config.trainingSnapshots = true;
    config.startNs = 100;
    config.endNs = 1000;
    config.drainEndNs = 3000001000ULL;
    config.requestPlan["car"] = {{1, 100}, {2, 200}};
    Recorder recorder (config);
    recorder.RecordGenerated (100, "/com/baidu/car/1", "car", 2, 1, 0);
    recorder.RecordGenerated (200, "/com/baidu/car/2", "car", 2, 2, 1);
    const std::array<double, 6> state = {{1.25, -2.5, 3.0, -4.0, 180.0, 0.0}};
    std::vector<std::array<double, 6>> values (10, state);
    const std::vector<uint32_t> candidates = {0, 1};
    recorder.RecordTrainingSnapshot (300, "/com/baidu/car/1", 2, 0, 257,
                                     candidates, values, {250});
    recorder.RecordTrainingSnapshot (310, "/com/baidu/car/1", 2, 0, 257,
                                     candidates, values, {250});
    recorder.RecordTrainingSnapshot (320, "/com/baidu/car/1", 2, 1, 257,
                                     candidates, values, {260});
    recorder.RecordTrainingSnapshot (330, "/com/baidu/missing", 2, 0, 257,
                                     candidates, values, {250});
    recorder.RecordTrainingSnapshot (340, "/com/baidu/car/2", 999, 0, 257,
                                     candidates, values, {250});
    values[9][0] = std::numeric_limits<double>::infinity ();
    recorder.RecordTrainingSnapshot (350, "/com/baidu/car/2", 2, 0, 257,
                                     candidates, values, {250});
    std::vector<std::array<double, 6>> emptyHistory (10, {{0, 0, 0, 0, 0, 0}});
    recorder.RecordTrainingSnapshot (360, "/com/baidu/car/2", 2, 1, 257,
                                     candidates, emptyHistory, {});
    recorder.RecordTerminal (400, "/com/baidu/car/1", "DATA", 1);
    recorder.RecordTerminal (3000000200ULL, "/com/baidu/car/2", "TIMEOUT", 1);
    NS_TEST_EXPECT_MSG_EQ (recorder.Finalize (config.drainEndNs), true,
                           "Snapshot exclusions do not alter protocol terminal outcomes");
    std::ifstream input (config.outputDirectory + "/training-observations.jsonl");
    std::vector<Json> rows;
    for (std::string line; std::getline (input, line);)
      rows.push_back (Json::parse (line));
    NS_TEST_ASSERT_MSG_EQ (rows.size (), 7, "Retain every candidate observation, including exclusions");
    NS_TEST_EXPECT_MSG_EQ (rows[0]["first_for_source_request"].get<bool> (), true,
                           "First source observation is eligible");
    NS_TEST_EXPECT_MSG_EQ (rows[0]["features"][9][0].get<double> (), state[0],
                           "Preserve raw six-feature values");
    NS_TEST_EXPECT_MSG_EQ (rows[0]["actual_history_length"].get<size_t> (), 1,
                           "Report true history separately from left padding");
    NS_TEST_EXPECT_MSG_EQ (rows[0]["padding_count"].get<size_t> (), 9,
                           "Do not invent ten received hellos");
    NS_TEST_EXPECT_MSG_EQ (rows[0]["history_age_ns"].get<uint64_t> (), 50,
                           "History age is causal simulated time");
    NS_TEST_EXPECT_MSG_EQ (rows[1]["sample_exclusion_reason"].get<std::string> (),
                           "DUPLICATE_SOURCE_REQUEST", "Duplicates remain raw diagnostics");
    NS_TEST_EXPECT_MSG_EQ (rows[1]["first_decision_event_id"], rows[0]["decision_event_id"],
                           "Duplicate identifies its first source-specific observation");
    NS_TEST_EXPECT_MSG_EQ (rows[2]["first_for_source_request"].get<bool> (), true,
                           "A second source has an independent first observation");
    NS_TEST_EXPECT_MSG_EQ (rows[3]["sample_exclusion_reason"].get<std::string> (),
                           "UNKNOWN_REQUEST", "Do not infer an unknown request identity");
    NS_TEST_EXPECT_MSG_EQ (rows[4]["sample_exclusion_reason"].get<std::string> (),
                           "OBU_ID_MISMATCH", "A valid name cannot authorize another OBU");
    NS_TEST_EXPECT_MSG_EQ (rows[5]["sample_exclusion_reason"].get<std::string> (),
                           "NONFINITE_FEATURE", "Invalid original data is not normalized into training");
    NS_TEST_EXPECT_MSG_EQ (rows[5]["features"][9][0].is_null (), true,
                           "Non-finite diagnostics use JSON null, never nonstandard Infinity");
    NS_TEST_EXPECT_MSG_EQ (rows[6]["actual_history_length"].get<size_t> (), 0,
                           "No-history input remains distinguishable");
    NS_TEST_EXPECT_MSG_EQ (rows[6]["history_age_ns"].is_null (), true,
                           "No history has no invented receive time");
    NS_TEST_EXPECT_MSG_EQ (rows[6]["sample_exclusion_reason"].get<std::string> (), "",
                           "Online all-zero no-history input remains a valid stratified sample");
    Json marker;
    std::ifstream complete (config.outputDirectory + "/recorder-complete.json");
    complete >> marker;
    NS_TEST_EXPECT_MSG_EQ (marker["training_snapshot_rows"].get<uint64_t> (), 7,
                           "Manifest can close the raw observation ledger");
    NS_TEST_EXPECT_MSG_EQ (marker["training_snapshot_eligible"].get<uint64_t> (), 3,
                           "Eligible counts exclude duplicate, unknown, wrong OBU and nonfinite");
    NS_TEST_EXPECT_MSG_EQ (marker["training_snapshot_excluded"].get<uint64_t> (), 4,
                           "Exclusions remain accountable");
  }
};

class TrainingSnapshotDisabledTest : public ns3::TestCase
{
public:
  TrainingSnapshotDisabledTest ()
    : TestCase ("Disabled passive sampling produces no observations and never changes the request ledger") {}
  void DoRun () override
  {
    Recorder::Config config;
    config.outputDirectory = CreateTempDirFilename ("");
    config.startNs = 100;
    config.endNs = 1000;
    config.drainEndNs = 3000001000ULL;
    config.requestPlan["car"] = {{1, 100}};
    Recorder recorder (config);
    recorder.RecordGenerated (100, "/com/baidu/car/1", "car", 2, 1, 0);
    recorder.RecordTrainingSnapshot (200, "/com/baidu/car/1", 2, 0, 257,
                                     {0, 1}, {}, {});
    recorder.RecordTerminal (3000000100ULL, "/com/baidu/car/1", "TIMEOUT", 0);
    NS_TEST_EXPECT_MSG_EQ (recorder.Finalize (config.drainEndNs), true, "Protocol ledger remains complete");
    NS_TEST_EXPECT_MSG_EQ (std::ifstream (config.outputDirectory + "/training-observations.jsonl").good (),
                           false, "Default-disabled mode cannot emit training samples");
  }
};

class TrainingSnapshotNetworkTest : public ns3::TestCase
{
public:
  TrainingSnapshotNetworkTest ()
    : TestCase ("Real RSU hello reception supplies causal empty short and full windows without changing traffic") {}

private:
  std::shared_ptr<nfd::Face> m_vehicleFace;
  std::shared_ptr<nfd::Face> m_routerFace;
  std::unique_ptr<Recorder> m_recorder;
  uint32_t m_helloCount = 0;
  uint64_t m_vehicleMac = 0;
  std::vector<ndn::util::signal::ScopedConnection> m_connections;

  std::string Read (const std::string &path)
  {
    std::ifstream input (path);
    std::ostringstream result;
    result << input.rdbuf ();
    return result.str ();
  }

  void Hello (const ndn::Interest &interest)
  {
    if (!ndn::Name ("/vndn/control/hello").isPrefixOf (interest.getName ()))
      return;
    ++m_helloCount;
    Json value = {{"LocateX", 100.0 + m_helloCount}, {"LocateY", -2.5}, {"Speed", 3.0},
                  {"Acceleration", -4.0}, {"Angle", 180.0}, {"LaneIndex", 0},
                  {"NextRsu", 0}};
    const std::string content = value.dump ();
    auto data = std::make_shared<ndn::Data> (interest.getName ());
    data->setContent (reinterpret_cast<const uint8_t *> (content.data ()), content.size ());
    data->setTag (std::make_shared<ndn::lp::VndnTag> (1, m_vehicleMac, 0));
    ns3::ndn::StackHelper::getKeyChain ().sign (*data);
    m_vehicleFace->sendData (*data, 0);
  }

  void Request (uint32_t sequence, bool repeat = false, bool fromRouter = false)
  {
    const std::string name = "/com/baidu/car/" + std::to_string (sequence);
    const uint64_t now = ns3::Simulator::Now ().GetNanoSeconds ();
    if (!repeat && !fromRouter)
      NS_TEST_EXPECT_MSG_EQ (m_recorder->RecordGenerated (now, name, "car", 1, sequence, 0),
                             true, "A real send must precede its passive snapshot");
    ndn::Interest interest (name);
    interest.setNonce (sequence * 100 + (repeat ? 1 : 0));
    interest.setCanBePrefix (false);
    interest.setInterestLifetime (ndn::time::seconds (3));
    interest.setTag (std::make_shared<ndn::lp::VndnTag> (1, m_vehicleMac, 0));
    (fromRouter ? m_routerFace : m_vehicleFace)->sendInterest (interest, 0);
  }

  std::string Run (bool enabled)
  {
    const std::string directory = CreateTempDirFilename (enabled ? "enabled" : "disabled");
    mkdir (directory.c_str (), 0755);
    ns3::RngSeedManager::SetSeed (1);
    ns3::RngSeedManager::SetRun (1);
    ns3::NodeContainer nodes;
    nodes.Create (3);
    ns3::NodeContainer wireless;
    wireless.Add (nodes.Get (0));
    wireless.Add (nodes.Get (1));
    ns3::SimpleNetDeviceHelper simple;
    auto wirelessDevices = simple.Install (wireless);
    ns3::PointToPointHelper p2p;
    auto wiredDevices = p2p.Install (nodes.Get (0), nodes.Get (2));
    ns3::ndn::StackHelper stack;
    stack.Install (nodes);
    ns3::ndn::StrategyChoiceHelper::Install (wireless, "/",
                                             "/localhost/nfd/strategy/vndn-multicast");
    m_vehicleFace = nodes.Get (1)->GetObject<ns3::ndn::L3Protocol> ()->
        getFaceByNetDevice (wirelessDevices.Get (1));
    m_routerFace = nodes.Get (2)->GetObject<ns3::ndn::L3Protocol> ()->
        getFaceByNetDevice (wiredDevices.Get (1));
    m_vehicleMac = 0;
    wirelessDevices.Get (1)->GetAddress ().CopyAllTo (
        reinterpret_cast<uint8_t *> (&m_vehicleMac), sizeof (m_vehicleMac));
    m_helloCount = 0;
    m_connections.emplace_back (m_vehicleFace->afterReceiveInterest.connect (
        [this] (const ndn::Interest &interest, const nfd::EndpointId &) { Hello (interest); }));

    Recorder::Config config;
    config.outputDirectory = directory;
    config.scenario = "circle";
    config.runId = "network-fixture";
    config.trainingSnapshots = enabled;
    config.startNs = 1000000;
    config.endNs = 240000000;
    config.drainEndNs = 3240000000ULL;
    config.requestPlan["car"] = {{1, 1000000}, {2, 45000000}, {3, 225000000}};
    m_recorder.reset (new Recorder (config));
    Recorder::SetActive (m_recorder.get ());
    auto app = ns3::CreateObject<ns3::VndnRsuApp> ();
    nodes.Get (0)->AddApplication (app);
    app->SetStartTime (ns3::Seconds (0));
    app->SetStopTime (ns3::MilliSeconds (250));
    auto tracer = vanet::VndnL3ExperimentTracer::InstallAll (directory, 0, 260000000);
    if (enabled)
      vanet::VndnL3ExperimentTracer::SaveFaceRoles (
          directory, "circle", "network-fixture", {{0, "rsu"}, {1, "obu"}, {2, "router"}});
    ns3::Simulator::Schedule (ns3::MilliSeconds (1), &TrainingSnapshotNetworkTest::Request,
                              this, 1, false, false);
    ns3::Simulator::Schedule (ns3::MilliSeconds (15), &TrainingSnapshotNetworkTest::Request,
                              this, 1, true, false);
    ns3::Simulator::Schedule (ns3::MilliSeconds (45), &TrainingSnapshotNetworkTest::Request,
                              this, 2, false, false);
    ns3::Simulator::Schedule (ns3::MilliSeconds (100), &TrainingSnapshotNetworkTest::Request,
                              this, 99, false, true);
    ns3::Simulator::Schedule (ns3::MilliSeconds (225), &TrainingSnapshotNetworkTest::Request,
                              this, 3, false, false);
    ns3::Simulator::Stop (ns3::MilliSeconds (260));
    ns3::Simulator::Run ();
    tracer->Close ();
    for (uint32_t sequence = 1; sequence <= 3; ++sequence)
      {
        const auto *request = m_recorder->FindRequest ("/com/baidu/car/" + std::to_string (sequence));
        NS_TEST_EXPECT_MSG_EQ ((request != nullptr), true, "All scheduled requests ran");
        if (request != nullptr)
          m_recorder->RecordTerminal (request->deadlineNs, request->name, "TIMEOUT", 0);
      }
    NS_TEST_EXPECT_MSG_EQ (m_recorder->Finalize (config.drainEndNs), true,
                           "Fixture closes all three original request outcomes");
    m_connections.clear ();
    ns3::Simulator::Destroy ();
    m_vehicleFace.reset ();
    m_routerFace.reset ();
    m_recorder.reset ();
    return directory;
  }

  void DoRun () override
  {
    const auto disabled = Run (false);
    const auto enabled = Run (true);
    NS_TEST_EXPECT_MSG_EQ (Read (disabled + "/packet-l3.csv"), Read (enabled + "/packet-l3.csv"),
                           "Passive collection must not change any logical network send");
    NS_TEST_EXPECT_MSG_EQ (Read (disabled + "/request-events.csv"), Read (enabled + "/request-events.csv"),
                           "Passive collection must not change request identity, time or outcome");
    std::ifstream input (enabled + "/training-observations.jsonl");
    std::vector<Json> rows;
    for (std::string line; std::getline (input, line);)
      rows.push_back (Json::parse (line));
    NS_TEST_ASSERT_MSG_EQ (rows.size (), 4,
                           "Only genuine wireless business callbacks, including one source duplicate");
    NS_TEST_EXPECT_MSG_EQ (rows[0]["actual_history_length"].get<size_t> (), 0,
                           "The first request predates every hello");
    NS_TEST_EXPECT_MSG_EQ (rows[0]["features"][9][0].get<double> (), 0,
                           "No-history online window is all zeros");
    NS_TEST_EXPECT_MSG_EQ (rows[1]["sample_exclusion_reason"].get<std::string> (),
                           "DUPLICATE_SOURCE_REQUEST", "Repeated wireless callbacks retain provenance");
    NS_TEST_EXPECT_MSG_EQ (rows[2]["actual_history_length"].get<size_t> (), 2,
                           "45ms request uses the 20ms and 40ms hello receptions");
    NS_TEST_EXPECT_MSG_EQ (rows[2]["features"][0][0].get<double> (), 101,
                           "Left padding repeats the earliest genuinely received state");
    NS_TEST_EXPECT_MSG_EQ (rows[2]["features"][9][0].get<double> (), 102,
                           "The most recent hello ends the short window");
    NS_TEST_EXPECT_MSG_EQ (rows[3]["actual_history_length"].get<size_t> (), 10,
                           "The eleventh hello evicts the oldest");
    NS_TEST_EXPECT_MSG_EQ (rows[3]["features"][0][0].get<double> (), 102,
                           "Full windows maintain hello chronological order");
    NS_TEST_EXPECT_MSG_EQ (rows[3]["features"][9][0].get<double> (), 111,
                           "A future 240ms hello never enters the 225ms snapshot");
    for (const auto &row : rows)
      for (const auto &time : row["hello_receive_times_ns"])
        NS_TEST_EXPECT_MSG_EQ ((time.get<uint64_t> () <= row["decision_time_ns"].get<uint64_t> ()),
                               true, "All observation information existed before the decision");
    Json roles = Json::parse (Read (enabled + "/face-roles.json"));
    size_t routerReturns = 0;
    for (const auto &face : roles["faces"])
      if (face["role"] == "router_return")
        {
          ++routerReturns;
          NS_TEST_EXPECT_MSG_EQ (face["node_id"].get<uint32_t> (), 0,
                                 "Return role belongs to the RSU, not the opposite router face");
          NS_TEST_EXPECT_MSG_EQ (face["peer_node_ids"], Json::array ({2}),
                                 "Return metadata identifies the physical upstream Router");
        }
    NS_TEST_EXPECT_MSG_EQ (routerReturns, 1, "Only the physical RSU-to-Router face is a return face");
  }
};

class NeuralDecisionLedgerTest : public ns3::TestCase
{
public:
  NeuralDecisionLedgerTest ()
    : TestCase ("Neural action evidence preserves actual float probabilities, selected IDs and fallback") {}
  void DoRun () override
  {
    Recorder::Config config;
    config.outputDirectory = CreateTempDirFilename ("");
    config.scenario = "grid";
    config.runId = "neural-decision-fixture";
    config.startNs = 100;
    config.endNs = 1000;
    config.drainEndNs = 3000001000ULL;
    config.requestPlan["car"] = {{1, 100}};
    Recorder recorder (config);
    recorder.RecordGenerated (100, "/com/baidu/car/1", "car", 7, 1, 0);
    const std::vector<uint32_t> candidates = {5, 0, 3};
    const std::vector<float> probabilities = {0.2f, 0.1f, 0.7f};
    const auto selected = vanet::VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
        candidates, probabilities, 0.1, 0.1);
    recorder.RecordNeuralDecision (200, "/com/baidu/car/1", 7, 0, candidates,
                                    probabilities, selected, 0.1, 0.1, "ACCEPTED");
    recorder.RecordNeuralDecision (210, "/com/baidu/car/1", 7, 0, candidates,
                                    {}, {0}, 0.1, 0.1, "FALLBACK_INVALID_ACTION");
    recorder.RecordTerminal (3000000100ULL, "/com/baidu/car/1", "TIMEOUT", 1);
    NS_TEST_EXPECT_MSG_EQ (recorder.Finalize (config.drainEndNs), true,
                           "Recording actions does not claim a successful data delivery");
    std::ifstream input (config.outputDirectory + "/neural-decisions.jsonl");
    std::vector<Json> rows;
    for (std::string line; std::getline (input, line);)
      rows.push_back (Json::parse (line));
    NS_TEST_ASSERT_MSG_EQ (rows.size (), 2, "Accepted and invalid-fallback actions both remain visible");
    NS_TEST_EXPECT_MSG_EQ (rows[0]["selected_rsu_ids"], Json::array ({3, 5}),
                           "Preserve actual C++ candidate order and dual-path decision");
    NS_TEST_EXPECT_MSG_EQ (rows[0]["probabilities"][0].get<double> (),
                           static_cast<double> (0.2f), "Record the actual received float, without rounding to 0.2");
    NS_TEST_EXPECT_MSG_EQ (rows[0]["request_id"].get<std::string> (), "car:1",
                           "The action is attributable to its first generated business request");
    NS_TEST_EXPECT_MSG_EQ (rows[1]["action_status"].get<std::string> (),
                           "FALLBACK_INVALID_ACTION", "A fallback must not masquerade as model inference");
    NS_TEST_EXPECT_MSG_EQ (rows[1]["selected_rsu_ids"], Json::array ({0}),
                           "Fallback records the actual source-station path");
    Json marker;
    std::ifstream complete (config.outputDirectory + "/recorder-complete.json");
    complete >> marker;
    NS_TEST_EXPECT_MSG_EQ (marker["neural_decision_rows"].get<uint64_t> (), 2,
                           "Completion counts accepted and fallback decision records");
  }
};

class TrainingSnapshotSuite : public ns3::TestSuite
{
public:
  TrainingSnapshotSuite () : TestSuite ("vndn-training-snapshot", UNIT)
  {
    AddTestCase (new TrainingSnapshotLedgerTest, TestCase::QUICK);
    AddTestCase (new TrainingSnapshotDisabledTest, TestCase::QUICK);
    AddTestCase (new TrainingSnapshotNetworkTest, TestCase::QUICK);
    AddTestCase (new NeuralDecisionLedgerTest, TestCase::QUICK);
  }
};
static TrainingSnapshotSuite g_suite;
} // namespace
