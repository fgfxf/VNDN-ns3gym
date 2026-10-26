#include "ns3/test.h"
#include "ns3/vndn-experiment-config.h"
#include "../src/json/single_include/nlohmann/json.hpp"

#include <cstdlib>
#include <fstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

namespace {

using Json = nlohmann::json;

class ExperimentConfigTestCase : public ns3::TestCase
{
public:
  ExperimentConfigTestCase ()
      : TestCase ("Experiment inputs preserve stable vehicle IDs, explicit sequences and boundaries")
  {
  }

private:
  std::string m_directory;

  void Write (const std::string &name, const std::string &body)
  {
    std::ofstream stream (m_directory + "/" + name);
    stream << body;
    if (!stream)
      throw std::runtime_error ("Cannot write test fixture");
  }

  bool Rejects (const Json &configuration, const Json &plan,
                const std::string &scenario = "circle")
  {
    Write ("experiment.json", configuration.dump ());
    Write ("requests.json", plan.dump ());
    try
      {
        vanet::LoadExperimentConfig (m_directory + "/experiment.json", scenario);
        return false;
      }
    catch (const std::exception &)
      {
        return true;
      }
  }

  void DoRun () override
  {
    char directory[] = "/tmp/vndn-experiment-config-XXXXXX";
    char *created = mkdtemp (directory);
    NS_TEST_ASSERT_MSG_EQ ((created != nullptr), true, "Temporary test directory must exist");
    m_directory = created;
    Write ("routes.rou.xml",
           "<routes><vehicle id=\"car-b\" depart=\"0\"><route edges=\"a\"/></vehicle>"
           "<vehicle id=\"car-a\" depart=\"0\"><route edges=\"a\"/></vehicle></routes>");
    Write ("network.net.xml", "<net/>");
    Write ("simulation.sumocfg",
           "<configuration><input><net-file value=\"network.net.xml\"/>"
           "<route-files value=\"routes.rou.xml\"/></input></configuration>");
    Json configuration = {
        {"schema_version", 1}, {"scenario", "circle"}, {"run_id", "fixture"},
        {"sumo_config", "simulation.sumocfg"}, {"route_file", "routes.rou.xml"},
        {"request_plan", "requests.json"}, {"output_dir", "results"},
        {"training_snapshots", true},
        {"measurement_start_s", 2.0}, {"measurement_end_s", 5.0},
        {"drain_end_s", 8.5},
        {"seeds", {{"rng_seed", 7}, {"rng_run", 3}, {"sumo_seed", 5}, {"srand_seed", 9}}}};
    Json plan = {{"schema_version", 1},
                 {"requests", Json::array ({
                    {{"vehicle_id", "car-b"}, {"sequence", 91}, {"send_time_ns", 2000000000ULL}},
                    {{"vehicle_id", "car-a"}, {"sequence", 7}, {"send_time_ns", 4999999999ULL}}
                 })}};
    Write ("experiment.json", configuration.dump ());
    Write ("requests.json", plan.dump ());
    const auto loaded =
        vanet::LoadExperimentConfig (m_directory + "/experiment.json", "circle");
    NS_TEST_EXPECT_MSG_EQ (loaded.vehicleIds.size (), 2, "Count the selected route's vehicles");
    NS_TEST_EXPECT_MSG_EQ (loaded.requestPlan.size (), 2, "Bind requests to SUMO IDs");
    if (loaded.requestPlan.count ("car-b"))
      {
        NS_TEST_EXPECT_MSG_EQ (loaded.requestPlan.at ("car-b").at (0).sequence, 91,
                               "Do not renumber explicit request sequences");
        NS_TEST_EXPECT_MSG_EQ (loaded.requestPlan.at ("car-b").at (0).sendTimeNs,
                               2000000000ULL, "The left boundary is included");
      }
    NS_TEST_EXPECT_MSG_EQ (loaded.measurementEndNs, 5000000000ULL, "Preserve time units");
    NS_TEST_EXPECT_MSG_EQ (loaded.rngRun, 3, "Read the independent repetition number");
    NS_TEST_EXPECT_MSG_EQ (loaded.routeFilePath, m_directory + "/routes.rou.xml",
                           "Resolve relative paths from the configuration directory");

    Json bad = plan;
    bad["requests"][0]["send_time_ns"] = 5000000000ULL;
    NS_TEST_EXPECT_MSG_EQ (Rejects (configuration, bad), true,
                           "Reject a request at the exclusive end boundary");
    bad = plan;
    bad["requests"][0]["send_time_ns"] = 1999999999ULL;
    NS_TEST_EXPECT_MSG_EQ (Rejects (configuration, bad), true,
                           "Reject a request before the measurement window");
    bad = plan;
    bad["requests"].push_back (bad["requests"][0]);
    NS_TEST_EXPECT_MSG_EQ (Rejects (configuration, bad), true, "Reject duplicate request keys");
    bad = plan;
    bad["requests"][0]["vehicle_id"] = "unknown";
    NS_TEST_EXPECT_MSG_EQ (Rejects (configuration, bad), true, "Reject missing vehicles");
    bad = plan;
    bad["requests"][0]["sequence"] = 0;
    NS_TEST_EXPECT_MSG_EQ (Rejects (configuration, bad), true, "Sequences must be positive");
    bad = plan;
    bad["requests"][0]["send_time_ns"] = 2000000000.5;
    NS_TEST_EXPECT_MSG_EQ (Rejects (configuration, bad), true, "Nanoseconds must be integers");
    bad = configuration;
    bad["drain_end_s"] = 7.9;
    NS_TEST_EXPECT_MSG_EQ (Rejects (bad, plan), true, "Preserve a full three-second drain");
    bad = configuration;
    bad["seeds"]["rng_seed"] = 0;
    NS_TEST_EXPECT_MSG_EQ (Rejects (bad, plan), true, "Reject invalid ns-3 seed");
    bad["seeds"]["rng_seed"] = 4294944443ULL;
    NS_TEST_EXPECT_MSG_EQ (Rejects (bad, plan), true,
                           "Reject the MRG32k3a modulus before ns-3 aborts");
    NS_TEST_EXPECT_MSG_EQ (Rejects (configuration, plan, "grid"), true,
                           "Reject a configuration from another scenario");
    for (const Json &invalid : {Json (1), Json ("true"), Json (nullptr),
                                Json::array (), Json::object ()})
      {
        bad = configuration;
        bad["training_snapshots"] = invalid;
        NS_TEST_EXPECT_MSG_EQ (Rejects (bad, plan), true,
                               "A passive training switch must be a JSON boolean");
      }
    for (const Json &invalid : {Json (0), Json (-1), Json (true), Json (20.5),
                                Json ("20"), Json (2147483648ULL), Json (nullptr)})
      {
        bad = configuration;
        bad["hello_interval_ms"] = invalid;
        NS_TEST_EXPECT_MSG_EQ (Rejects (bad, plan), true,
                               "Hello period must be an integer whose doubled timeout fits uint32");
      }
    for (const Json &invalid : {Json (1), Json ("true"), Json (nullptr)})
      {
        bad = configuration;
        bad["resource_observations"] = invalid;
        NS_TEST_EXPECT_MSG_EQ (Rejects (bad, plan), true,
                               "Passive resource recording must be an explicit JSON boolean");
      }
    for (const uint32_t interval : {20U, 40U, 80U, 160U, 2147483647U})
      {
        bad = configuration;
        bad["hello_interval_ms"] = interval;
        bad["resource_observations"] = true;
        NS_TEST_EXPECT_MSG_EQ (Rejects (bad, plan), false,
                               "All four approved periods accept identical valid experimental inputs");
      }
    Write ("other.rou.xml", "<routes><vehicle id=\"other\"/></routes>");
    bad = configuration;
    bad["route_file"] = "other.rou.xml";
    NS_TEST_EXPECT_MSG_EQ (Rejects (bad, plan), true,
                           "The counted route must be the route loaded by SUMO");
    Write ("routes.rou.xml", "<routes><flow id=\"cars\" number=\"2\"/></routes>");
    NS_TEST_EXPECT_MSG_EQ (Rejects (configuration, plan), true,
                           "Do not silently count flows as explicit vehicles");

    // A partial prior run may have logs but no effective-config marker. None of
    // these files may be overwritten by another attempt at the same directory.
    const std::string resultDirectory = m_directory + "/results";
    mkdir (resultDirectory.c_str (), 0755);
    Write ("results/request-events.csv", "preserve earlier partial run\n");
    bool refusedReuse = false;
    try
      {
        vanet::SaveEffectiveExperimentConfig (loaded, 0);
      }
    catch (const std::exception &)
      {
        refusedReuse = true;
      }
    NS_TEST_EXPECT_MSG_EQ (refusedReuse, true,
                           "Refuse a nonempty output directory even without a completion marker");
    unlink ((resultDirectory + "/request-events.csv").c_str ());
    unlink ((resultDirectory + "/effective-experiment-config.json").c_str ());
    rmdir ((resultDirectory + "/ai-training").c_str ());
    rmdir (resultDirectory.c_str ());

    Write ("routes.rou.xml",
           "<routes><vehicle id=\"car-b\" depart=\"0\"><route edges=\"a\"/></vehicle>"
           "<vehicle id=\"car-a\" depart=\"0\"><route edges=\"a\"/></vehicle></routes>");
    for (uint32_t interval : {20U, 40U, 80U, 160U})
      {
        Json configured = configuration;
        configured["hello_interval_ms"] = interval;
        configured["resource_observations"] = true;
        configured["output_dir"] = "period-" + std::to_string (interval);
        Write ("experiment.json", configured.dump ());
        Write ("requests.json", plan.dump ());
        const auto current = vanet::LoadExperimentConfig (m_directory + "/experiment.json", "circle");
        NS_TEST_EXPECT_MSG_EQ (current.helloIntervalMs, interval, "The selected period survives JSON parsing");
        NS_TEST_EXPECT_MSG_EQ (current.resourceObservations, true, "Resource observation is enabled explicitly");
        vanet::SaveEffectiveExperimentConfig (current, 3);
        std::ifstream input (current.outputDirectory + "/effective-experiment-config.json");
        Json evidence;
        input >> evidence;
        NS_TEST_EXPECT_MSG_EQ (evidence.at ("hello_interval_ms").get<uint32_t> (), interval,
                               "Effective metadata names the actual selected period");
        NS_TEST_EXPECT_MSG_EQ (evidence.at ("rsu_timeout_ms").get<uint32_t> (), interval * 2,
                               "Effective timeout remains exactly two selected periods");
        NS_TEST_EXPECT_MSG_EQ (evidence.at ("resource_observations").get<bool> (), true,
                               "Enabled passive evidence is independently identifiable");
        unlink ((current.outputDirectory + "/effective-experiment-config.json").c_str ());
        rmdir ((current.outputDirectory + "/ai-training").c_str ());
        rmdir (current.outputDirectory.c_str ());
      }

    vanet::SaveEffectiveExperimentConfig (loaded, 2);
    Json effective;
    std::ifstream effectiveInput (resultDirectory + "/effective-experiment-config.json");
    effectiveInput >> effective;
    NS_TEST_EXPECT_MSG_EQ (effective.at ("strategy").get<uint32_t> (), 2,
                           "The evidence records the actual algorithm");
    NS_TEST_EXPECT_MSG_EQ (effective.at ("expected_requests").get<uint64_t> (), 2,
                           "The evidence preserves the exact request budget");
    NS_TEST_EXPECT_MSG_EQ (effective.value ("training_snapshots", false), true,
                           "Effective evidence must preserve enabled passive training snapshots");
    NS_TEST_EXPECT_MSG_EQ (effective.value ("hello_interval_ms", 0U), 20U,
                           "Missing optional period preserves the actual 20ms default");
    NS_TEST_EXPECT_MSG_EQ (effective.value ("rsu_timeout_ms", 0U), 40U,
                           "Default RSU timeout is twice the hello period");
    NS_TEST_EXPECT_MSG_EQ (effective.value ("obu_neighbor_timeout_ms", 0U), 2000U,
                           "Vehicle neighbour expiry remains independently fixed at two seconds");
    NS_TEST_EXPECT_MSG_EQ (effective.value ("resource_observations", true), false,
                           "Default resource observation remains disabled");
    vanet::SaveExperimentCompletion (loaded, true, loaded.drainEndNs + 1);
    Json completion;
    std::ifstream completionInput (resultDirectory + "/simulation-result.json");
    completionInput >> completion;
    NS_TEST_EXPECT_MSG_EQ (completion.at ("complete").is_boolean (), true,
                           "Completion is a JSON boolean, not a string");
    NS_TEST_EXPECT_MSG_EQ (completion.at ("complete").get<bool> (), true,
                           "Exact drain followed by the scheduler stop completes the run");
    unlink ((resultDirectory + "/effective-experiment-config.json").c_str ());
    unlink ((resultDirectory + "/simulation-result.json").c_str ());
    rmdir ((resultDirectory + "/ai-training").c_str ());
    rmdir (resultDirectory.c_str ());

    for (const std::string name : {"experiment.json", "requests.json", "routes.rou.xml",
                                   "other.rou.xml", "network.net.xml", "simulation.sumocfg"})
      unlink ((m_directory + "/" + name).c_str ());
    rmdir (m_directory.c_str ());
  }
};

class ExperimentConfigTestSuite : public ns3::TestSuite
{
public:
  ExperimentConfigTestSuite () : TestSuite ("vndn-experiment-config", UNIT)
  {
    AddTestCase (new ExperimentConfigTestCase, TestCase::QUICK);
  }
} g_experimentConfigTestSuite;

} // namespace
