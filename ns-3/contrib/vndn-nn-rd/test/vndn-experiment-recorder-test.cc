#include "ns3/test.h"
#include "ns3/vndn-experiment-recorder.h"
#include <fstream>
#include <sstream>

namespace {
using vanet::VndnExperimentRecorder;

VndnExperimentRecorder::Config
MakeConfig ()
{
  VndnExperimentRecorder::Config config;
  config.startNs = 1000000000;
  config.endNs = 2000000000;
  config.drainEndNs = 5500000000;
  config.requestPlan["car"] = {{17, 1000000000}, {23, 1500000000}};
  return config;
}

class RequestLedgerTest : public ns3::TestCase
{
public:
  RequestLedgerTest () : TestCase ("request cohort, deadline and terminal uniqueness") {}
  void DoRun () override
  {
    VndnExperimentRecorder recorder (MakeConfig ());
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordGenerated (999999999, "/early", "car", 2, 1, -1),
                           false, "Before measurement is not in the cohort");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordGenerated (1000000000, "/a", "car", 2, 17, -1),
                           true, "A generated request at t0 must enter the ledger, even disconnected");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordGenerated (1000000000, "/a", "car", 2, 17, -1),
                           false, "Duplicate generation cannot increase denominator");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordGenerated (1500000000, "/b", "car", 2, 23, 0),
                           true, "The supplied nonconsecutive sequence must be accepted");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordGenerated (2000000000, "/end", "car", 2, 24, 0),
                           false, "The measurement end is exclusive");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordTerminal (4000000000, "/a", "DATA", 1),
                           true, "Data exactly at the deadline is valid");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordTerminal (4000000000, "/a", "DATA", 1),
                           false, "Repeated data cannot replace a terminal state");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordTerminal (4500000000, "/b", "TIMEOUT", 1),
                           true, "Timeout closes the second request");
    NS_TEST_EXPECT_MSG_EQ (recorder.GetGeneratedCount (), 2, "Denominator must be two");
    NS_TEST_EXPECT_MSG_EQ (recorder.GetTerminalCount (), 2, "Every request terminates once");
    NS_TEST_EXPECT_MSG_EQ (recorder.Finalize (5500000000), true, "A complete ledger finalizes");
  }
};

class IncompleteLedgerTest : public ns3::TestCase
{
public:
  IncompleteLedgerTest () : TestCase ("late data is diagnostic and NACK STOPPED remain failures") {}
  void DoRun () override
  {
    auto config = MakeConfig ();
    config.requestPlan["car"].push_back ({27, 1700000000});
    config.requestPlan["car"].push_back ({31, 1900000000});
    VndnExperimentRecorder recorder (config);
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordGenerated (1000000000, "/a", "car", 2, 17, 0),
                           true, "Record first request");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordTerminal (4000000001, "/a", "DATA", 1),
                           false, "Late Data does not become a successful terminal");
    NS_TEST_EXPECT_MSG_EQ (recorder.GetTerminalCount (), 1,
                           "Late Data must close its expired request even without a later Face timeout");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordTerminal (4000000001, "/a", "TIMEOUT", 1),
                           false, "A later Face timeout cannot terminate the expired request twice");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordGenerated (1500000000, "/b", "car", 2, 23, 0),
                           true, "Record second request");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordTerminal (1600000000, "/b", "NACK", 0),
                           true, "NACK is a terminal failure");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordGenerated (1700000000, "/c", "car", 2, 27, 0),
                           true, "Record third request");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordTerminal (1800000000, "/c", "STOPPED", -1),
                           true, "Known application stop is a terminal failure");
    NS_TEST_EXPECT_MSG_EQ (recorder.GetTerminalCount (), 3, "All three failures are represented");
    NS_TEST_EXPECT_MSG_EQ (recorder.RecordGenerated (1900000000, "/pending", "car", 2, 31, 0),
                           true, "An unfinished request must remain visible");
    NS_TEST_EXPECT_MSG_EQ (recorder.Finalize (5500000000), false,
                           "Finalization must refuse to certify an unfinished ledger");
  }
};

class CsvLifecycleTest : public ns3::TestCase
{
public:
  CsvLifecycleTest () : TestCase ("closed CSV distinguishes late data, failed-terminal data and unknown ancestry") {}
  void DoRun () override
  {
    auto config = MakeConfig ();
    config.outputDirectory = CreateTempDirFilename ("");
    VndnExperimentRecorder recorder (config);
    recorder.RecordGenerated (1000000000, "/a", "car", 2, 17, 0);
    recorder.RecordGenerated (1500000000, "/b", "car", 2, 23, 0);
    recorder.RecordTerminal (1600000000, "/b", "NACK", 0);
    recorder.RecordTerminal (1700000000, "/b", "DATA", 0);
    recorder.RecordTerminal (4000000001, "/a", "DATA", 1);
    recorder.RecordDataAttempt (1800000000, "/a", 9, -1, "PREDICTIVE_EXTRA");
    NS_TEST_EXPECT_MSG_EQ (recorder.Finalize (5500000001), true,
                           "A late Data must not leave the cohort pending forever");
    const auto read = [&] (const std::string &filename) {
      std::ifstream input (config.outputDirectory + "/" + filename);
      std::ostringstream contents;
      contents << input.rdbuf ();
      return contents.str ();
    };
    const std::string requests = read ("request-events.csv");
    NS_TEST_EXPECT_MSG_NE (requests.find ("4000000000,TIMEOUT,car:17,/a,"),
                           std::string::npos, "Late Data synthesizes expiration at the fixed deadline");
    NS_TEST_EXPECT_MSG_NE (requests.find ("4000000001,LATE_DATA,car:17,/a,"),
                           std::string::npos, "Observation timestamp retains the later arrival");
    NS_TEST_EXPECT_MSG_NE (requests.find ("1700000000,POST_TERMINAL_DATA,car:23,/b,"),
                           std::string::npos, "NACK then Data is not duplicate successful Data");
    NS_TEST_EXPECT_MSG_EQ (requests.find (",DUPLICATE_DATA,"), std::string::npos,
                           "There was no previous successful Data in this run");
    const std::string attempts = read ("data-attempts.csv");
    NS_TEST_EXPECT_MSG_NE (attempts.find ("1800000000,a1,-,/a,9,-1,PREDICTIVE_EXTRA,APP_SUBMIT"),
                           std::string::npos, "A dash marks unavailable ancestry without inventing a parent");
    NS_TEST_EXPECT_MSG_NE (read ("recorder-complete.json").find ("\"complete\":true"),
                           std::string::npos, "Completion marker follows closed raw CSV files");
    NS_TEST_EXPECT_MSG_EQ (std::ifstream (config.outputDirectory + "/neural-decisions.jsonl").good (),
                           true, "Every experiment seals an explicit C++ neural decision log, even when empty");
    NS_TEST_EXPECT_MSG_NE (read ("recorder-complete.json").find ("\"neural_decision_rows\":0"),
                           std::string::npos, "The completion marker accounts for zero actual neural decisions");
  }
};

class DataAttemptTest : public ns3::TestCase
{
public:
  DataAttemptTest () : TestCase ("extra application attempts exclude first queue delivery and normal hops") {}
  void DoRun () override
  {
    VndnExperimentRecorder recorder (MakeConfig ());
    recorder.RecordDataAttempt (1100000000, "/a", 9, 1, "PREDICTIVE_EXTRA");
    recorder.RecordDataAttempt (1200000000, "/a", 1, 2, "REACTIVE_RELAY");
    recorder.RecordWirelessSubmission (1300000000, "/a", 2, 10);
    NS_TEST_EXPECT_MSG_EQ (recorder.GetExtraAttemptCount (), 2,
                           "First wireless delivery continues a copy; it does not create another");
    recorder.RecordWirelessSubmission (1400000000, "/a", 2, 10);
    NS_TEST_EXPECT_MSG_EQ (recorder.GetExtraAttemptCount (), 3,
                           "A repeated application submission on the same leg is extra");
  }
};

class ExperimentRecorderSuite : public ns3::TestSuite
{
public:
  ExperimentRecorderSuite () : TestSuite ("vndn-experiment-recorder", UNIT)
  {
    AddTestCase (new RequestLedgerTest, ns3::TestCase::QUICK);
    AddTestCase (new IncompleteLedgerTest, ns3::TestCase::QUICK);
    AddTestCase (new DataAttemptTest, ns3::TestCase::QUICK);
    AddTestCase (new CsvLifecycleTest, ns3::TestCase::QUICK);
  }
} g_experimentRecorderSuite;
} // namespace
