/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include "ns3/test.h"
#include "ns3/vndn-l3-experiment-tracer.h"
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/ndnSIM-module.h"
#include <ndn-cxx/encoding/block-helpers.hpp>
#include <fstream>
#include <sstream>

namespace {
ndn::Data
MakeData (const std::string &name, size_t payload = 32)
{
  ndn::Data data (name);
  std::vector<uint8_t> bytes (payload, 42);
  data.setContent (bytes.data (), bytes.size ());
  ns3::ndn::StackHelper::getKeyChain ().sign (data);
  return data;
}

class L3ClassificationTest : public ns3::TestCase
{
public:
  L3ClassificationTest () : TestCase ("L3 semantic bytes include all custom controls and separate relay payload") {}
  void DoRun () override
  {
    using vanet::VndnL3ExperimentTracer;
    const std::vector<std::pair<std::string, std::string>> classes = {
      {"/vndn/control/hello/1", "hello"},
      {"/vndn/control/p2p-handshake/rsu/1", "p2p_handshake"},
      {"/vndn/control/rsu-relay/find/1", "search"},
      {"/vndn/control/rsu-relay/found/1", "find"},
      {"/vndn/control/neural-route/1", "neural_route"},
      {"/vndn/control/neural-pit/1", "neural_pit"},
      {"/com/baidu/www/userid/2/1", "business"},
      {"/vndn/control/hello-extra/1", "unknown"}
    };
    for (const auto &item : classes)
      {
        ndn::Interest interest (item.first);
        interest.setCanBePrefix (false);
        auto i = VndnL3ExperimentTracer::Describe (interest);
        NS_TEST_EXPECT_MSG_EQ (i.semanticClass, item.second, "Match Name components, not string prefixes");
        NS_TEST_EXPECT_MSG_EQ (i.wireBytes, interest.wireEncode ().size (), "Use full logical Interest bytes");
        auto data = MakeData (item.first);
        auto d = VndnL3ExperimentTracer::Describe (data);
        NS_TEST_EXPECT_MSG_EQ (d.semanticClass, item.second, "Control Data responses must also be counted");
        NS_TEST_EXPECT_MSG_EQ (d.wireBytes, data.wireEncode ().size (), "Use full logical Data bytes");
      }
    auto business = MakeData ("/com/baidu/www/userid/2/1", 10240);
    auto relay = MakeData ("/vndn/control/rsu-relay/forward/1/0/2/1");
    const auto &inner = business.wireEncode ();
    relay.setContent (inner.wire (), inner.size ());
    ns3::ndn::StackHelper::getKeyChain ().sign (relay);
    auto description = VndnL3ExperimentTracer::Describe (relay);
    NS_TEST_EXPECT_MSG_EQ (description.semanticClass, "relay_data", "Business relay is not pure control");
    NS_TEST_EXPECT_MSG_EQ (description.wireBytes, relay.wireEncode ().size (), "Outer bytes counted once");
    NS_TEST_EXPECT_MSG_EQ (description.innerDataBytes, inner.size (), "Inner bytes are a decomposition, not an extra total");
    auto malformed = MakeData ("/vndn/control/rsu-relay/forward/1", 3);
    NS_TEST_EXPECT_MSG_EQ (VndnL3ExperimentTracer::Describe (malformed).semanticClass,
                           "unknown", "Malformed business encapsulation must not silently classify");
    ndn::lp::Nack nack (ndn::Interest ("/com/baidu/x"));
    nack.setReason (ndn::lp::NackReason::NO_ROUTE);
    auto n = VndnL3ExperimentTracer::Describe (nack);
    NS_TEST_EXPECT_MSG_EQ (n.semanticClass, "native_nack", "Nack is explicitly separate");
    NS_TEST_EXPECT_MSG_EQ (n.wireBytes, 0, "Never call inner Interest bytes complete Nack bytes");
  }
};

class L3TraceConnectionTest : public ns3::TestCase
{
public:
  L3TraceConnectionTest () : TestCase ("Existing trace captures logical messages once in a half-open window and flushes the tail") {}
  static void Send (std::shared_ptr<nfd::Face> face, std::shared_ptr<ndn::Data> data)
  {
    face->sendData (*data, 0);
  }
  void DoRun () override
  {
    ns3::NodeContainer nodes;
    nodes.Create (2);
    ns3::PointToPointHelper p2p;
    auto devices = p2p.Install (nodes);
    ns3::ndn::StackHelper stack;
    stack.Install (nodes);
    auto face = nodes.Get (0)->GetObject<ns3::ndn::L3Protocol> ()->getFaceByNetDevice (devices.Get (0));
    std::string directory = CreateTempDirFilename ("");
    auto tracer = vanet::VndnL3ExperimentTracer::InstallAll (directory, 1000000, 2000000);
    auto data = std::make_shared<ndn::Data> (MakeData ("/com/baidu/test", 10240));
    const auto originalWire = data->wireEncode ();
    for (int64_t time : {999999, 1000000, 1999999, 2000000})
      ns3::Simulator::Schedule (ns3::NanoSeconds (time),
                               &L3TraceConnectionTest::Send, face, data);
    ns3::Simulator::Stop (ns3::MilliSeconds (3));
    ns3::Simulator::Run ();
    tracer->Flush ();
    std::ifstream input (directory + "/packet-l3.csv");
    std::string line;
    std::getline (input, line);
    NS_TEST_EXPECT_MSG_EQ (line, "time_ns,node_id,face_id,direction,packet_type,name,semantic_class,wire_bytes,inner_data_bytes",
                           "Self-describing L3 output");
    size_t count = 0;
    while (std::getline (input, line))
      {
        ++count;
        NS_TEST_EXPECT_MSG_NE (line.find (",OUT,DATA,"), std::string::npos, "Only actual network face Out events");
        NS_TEST_EXPECT_MSG_NE (line.find (",business," + std::to_string (originalWire.size ()) + ",0"),
                               std::string::npos, "10KB Data is one logical event despite LP fragmentation");
      }
    NS_TEST_EXPECT_MSG_EQ (count, 2, "Boundary inclusive at start, exclusive at end; no period-tail loss");
    NS_TEST_EXPECT_MSG_EQ (data->wireEncode (), originalWire, "Observer must not mutate message encoding");
    tracer->Close ();
    ns3::Simulator::Destroy ();
  }
};

class L3ExperimentSuite : public ns3::TestSuite
{
public:
  L3ExperimentSuite () : TestSuite ("vndn-l3-experiment-tracer", UNIT)
  {
    AddTestCase (new L3ClassificationTest, TestCase::QUICK);
    AddTestCase (new L3TraceConnectionTest, TestCase::QUICK);
  }
};
static L3ExperimentSuite g_suite;
} // namespace
