/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include "ns3/test.h"
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/ndnSIM-module.h"
#include "ns3/vndn-rsu-app.h"
#include "ns3/ndnSIM/apps/ndn-app.hpp"
#include "ns3/ndnSIM/NFD/daemon/fw/forwarder.hpp"
#include "ns3/ndnSIM/NFD/daemon/table/fib.hpp"

#include <ndn-cxx/lp/vndn-tag.hpp>
#include <ndn-cxx/util/signal/scoped-connection.hpp>

#include <memory>
#include <set>
#include <string>
#include <vector>

namespace {

// All inputs travel through real SimpleNetDevice/P2P faces and production NFD,
// ndn::Face and VndnRsu callbacks. No direct private callback calls or fake
// Forwarder signals. SimpleNetDevice removes unrelated WiFi loss from this
// application-contract regression; it does not establish a performance gain.
enum class ReturnFormat { PREPARED_ROUTER, LEGACY_OBU, LEGACY_OBU_WITH_TARGET };

class NeuralReturnPeerSink : public ns3::ndn::App
{
public:
  static ns3::TypeId GetTypeId ()
  {
    static ns3::TypeId tid = ns3::TypeId ("VndnNeuralReturnPeerSink")
        .SetParent<ns3::ndn::App> ().AddConstructor<NeuralReturnPeerSink> ();
    return tid;
  }

private:
  void StartApplication () override
  {
    ns3::ndn::App::StartApplication ();
    // A real local sink prevents a NO_ROUTE Nack from closing the RSU proxy
    // before the controlled delayed return crosses the P2P face.
    ns3::ndn::FibHelper::AddRoute (GetNode (), "/com/baidu", m_face, 0);
  }
};

std::shared_ptr<ndn::Data>
MakeData (const ndn::Name &name, const std::string &content)
{
  auto data = std::make_shared<ndn::Data> (name);
  data->setContent (reinterpret_cast<const uint8_t *> (content.data ()), content.size ());
  ns3::ndn::StackHelper::getKeyChain ().sign (*data);
  return data;
}

class RsuNeuralReturnBufferTest : public ns3::TestCase
{
public:
  RsuNeuralReturnBufferTest (ReturnFormat format, const std::string &description)
    : TestCase (description), m_format (format)
  {
  }

private:
  void Configure ()
  {
    auto forwarder = m_nodes.Get (0)->GetObject<ns3::ndn::L3Protocol> ()->getForwarder ();
    auto &fib = forwarder->getFib ();
    const auto &root = fib.findLongestPrefixMatch (ndn::Name ("/"));
    for (const auto &hop : root.getNextHops ())
      if (hop.getFace ().getScope () == ndn::nfd::FACE_SCOPE_LOCAL)
        m_appFace = hop.getFace ().shared_from_this ();
    NS_TEST_ASSERT_MSG_EQ ((m_appFace != nullptr), true,
                           "The real RSU application must have registered its root prefix");
    auto entry = fib.insert (ndn::Name ("/com/baidu")).first;
    fib.addOrUpdateNextHop (*entry, *m_appFace, 0);
    m_connections.emplace_back (
        m_appFace->getLinkService ()->afterSendData.connect ([this] (const ndn::Data &data) {
          if (data.getName () == m_name)
            ++m_appData;
        }));
  }

  void Request ()
  {
    ndn::Interest interest (m_name);
    interest.setCanBePrefix (false);
    interest.setInterestLifetime (ndn::time::seconds (3));
    interest.setNonce (100);
    interest.setTag (std::make_shared<ndn::lp::VndnTag> (
        m_nodes.Get (1)->GetId (), m_vehicleMac, 0));
    m_vehicleFace->sendInterest (interest, 0);
  }

  void RouterInterest (const ndn::Interest &interest)
  {
    if (interest.getName () != m_name)
      return;
    ++m_routerInterests;
    if (m_replyScheduled)
      return;
    m_replyScheduled = true;
    auto saved = std::make_shared<ndn::Interest> (interest);
    if (m_format == ReturnFormat::PREPARED_ROUTER)
      ns3::Simulator::Schedule (ns3::MilliSeconds (2),
                               &RsuNeuralReturnBufferTest::Prepare, this, saved);
    ns3::Simulator::Schedule (ns3::MilliSeconds (4),
                             &RsuNeuralReturnBufferTest::ReturnData, this);
  }

  void Prepare (std::shared_ptr<ndn::Interest> interest)
  {
    ndn::Name name ("/vndn/control/neural-pit");
    name.appendNumber (m_nodes.Get (0)->GetId ())
        .appendNumber (m_nodes.Get (1)->GetId ())
        .appendNumber (m_vehicleMac).appendNumber (1);
    const auto &wire = interest->wireEncode ();
    const std::string content (reinterpret_cast<const char *> (wire.wire ()), wire.size ());
    m_routerFace->sendData (*MakeData (name, content), 0);
  }

  void ReturnData ()
  {
    auto data = MakeData (m_name, "real peer-to-RSU business Data");
    const bool prepared = m_format == ReturnFormat::PREPARED_ROUTER;
    const uint64_t target = m_format == ReturnFormat::LEGACY_OBU ? 0 : m_vehicleMac;
    auto tag = std::make_shared<ndn::lp::VndnTag> (
        m_nodes.Get (prepared ? 0 : 1)->GetId (), prepared ? 0 : m_vehicleMac, target);
    tag->setReturnRsuPrimary (m_nodes.Get (0)->GetId ());
    data->setTag (tag);
    m_routerFace->sendData (*data, 0);
  }

  void Hello (bool identityProbe)
  {
    // The second packet intentionally claims the RSU ID. It is an identity
    // probe for stale, incorrectly keyed application state, not a legitimate
    // vehicle or a claim that normal traffic uses this identity. A previously
    // PIT-forwarded Data must not be retained/replayed for any later hello.
    auto data = MakeData (ndn::Name ("/vndn/control/hello"),
                         "{\"LocateX\":1,\"LocateY\":2,\"Speed\":0,"
                         "\"Acceleration\":0,\"Angle\":0,\"LaneIndex\":0,\"NextRsu\":0}");
    data->setTag (std::make_shared<ndn::lp::VndnTag> (
        m_nodes.Get (identityProbe ? 0 : 1)->GetId (), m_vehicleMac, 0));
    m_vehicleFace->sendData (*data, 0);
  }

  void BeforeHello ()
  {
    NS_TEST_EXPECT_MSG_EQ (m_appData, 1,
                           "Returned Data must really cross the RSU's local application face");
    NS_TEST_EXPECT_MSG_EQ (m_wirelessData,
                           (m_format == ReturnFormat::PREPARED_ROUTER ? 1 : 0),
                           "Prepared PIT forwards immediately; genuine fallback waits for hello");
  }

  void AfterVehicleHello ()
  {
    NS_TEST_EXPECT_MSG_EQ (m_wirelessData, 1,
                           "Real OBU hello releases a genuine fallback once, never a PIT copy");
  }

  void DoRun () override
  {
    ns3::RngSeedManager::SetSeed (1);
    ns3::RngSeedManager::SetRun (1);
    m_nodes.Create (3); // RSU, real OBU, controlled Router peer
    ns3::NodeContainer wireless;
    wireless.Add (m_nodes.Get (0));
    wireless.Add (m_nodes.Get (1));
    ns3::SimpleNetDeviceHelper simple;
    auto wirelessDevices = simple.Install (wireless);
    ns3::PointToPointHelper p2p;
    p2p.SetDeviceAttribute ("DataRate", ns3::StringValue ("1Gbps"));
    p2p.SetChannelAttribute ("Delay", ns3::StringValue ("10us"));
    auto wiredDevices = p2p.Install (m_nodes.Get (0), m_nodes.Get (2));
    ns3::ndn::StackHelper stack;
    stack.setCsSize (0);
    stack.Install (m_nodes);
    ns3::ndn::StrategyChoiceHelper::Install (wireless, "/",
                                             "/localhost/nfd/strategy/vndn-multicast");
    auto rsuL3 = m_nodes.Get (0)->GetObject<ns3::ndn::L3Protocol> ();
    m_rsuWireless = rsuL3->getFaceByNetDevice (wirelessDevices.Get (0));
    m_vehicleFace = m_nodes.Get (1)->GetObject<ns3::ndn::L3Protocol> ()->
        getFaceByNetDevice (wirelessDevices.Get (1));
    m_routerFace = m_nodes.Get (2)->GetObject<ns3::ndn::L3Protocol> ()->
        getFaceByNetDevice (wiredDevices.Get (1));
    wirelessDevices.Get (1)->GetAddress ().CopyAllTo (
        reinterpret_cast<uint8_t *> (&m_vehicleMac), sizeof (m_vehicleMac));
    m_connections.emplace_back (m_routerFace->afterReceiveInterest.connect (
        [this] (const ndn::Interest &interest, const nfd::EndpointId &) { RouterInterest (interest); }));
    m_connections.emplace_back (m_rsuWireless->getLinkService ()->afterSendData.connect (
        [this] (const ndn::Data &data) {
          if (data.getName () != m_name)
            return;
          ++m_wirelessData;
          auto tag = data.getTag<ndn::lp::VndnTag> ();
          NS_TEST_EXPECT_MSG_EQ ((tag != nullptr), true, "Wireless Data retains a destination tag");
          if (tag != nullptr)
            NS_TEST_EXPECT_MSG_EQ (tag->getTargetMac (), m_vehicleMac,
                                   "Every actual wireless submission targets the real OBU MAC");
        }));
    m_connections.emplace_back (m_vehicleFace->afterReceiveData.connect (
        [this] (const ndn::Data &data, const nfd::EndpointId &) {
          if (data.getName () == m_name)
            ++m_receivedData;
        }));
    auto sink = ns3::CreateObject<NeuralReturnPeerSink> ();
    m_nodes.Get (2)->AddApplication (sink);
    sink->SetStartTime (ns3::Seconds (0));
    sink->SetStopTime (ns3::MilliSeconds (80));
    auto app = ns3::CreateObject<ns3::VndnRsuApp> ();
    app->SetAttribute ("RsuForwardStrategy", ns3::EnumValue (vanet::RsuForwardStrategy_NeuralNetwork));
    // Port zero deliberately uses the existing single-current-RSU decision;
    // no Gym, SUMO, trained model or new protocol behavior is needed here.
    m_nodes.Get (0)->AddApplication (app);
    app->SetStartTime (ns3::Seconds (0));
    app->SetStopTime (ns3::MilliSeconds (80));
    ns3::Simulator::ScheduleWithContext (m_nodes.Get (0)->GetId (), ns3::MilliSeconds (2),
                                        &RsuNeuralReturnBufferTest::Configure, this);
    ns3::Simulator::Schedule (ns3::MilliSeconds (5), &RsuNeuralReturnBufferTest::Request, this);
    ns3::Simulator::Schedule (ns3::MilliSeconds (25), &RsuNeuralReturnBufferTest::BeforeHello, this);
    ns3::Simulator::Schedule (ns3::MilliSeconds (30), &RsuNeuralReturnBufferTest::Hello, this, false);
    ns3::Simulator::Schedule (ns3::MilliSeconds (35), &RsuNeuralReturnBufferTest::AfterVehicleHello, this);
    ns3::Simulator::Schedule (ns3::MilliSeconds (40), &RsuNeuralReturnBufferTest::Hello, this, true);
    ns3::Simulator::Schedule (ns3::MilliSeconds (50), &RsuNeuralReturnBufferTest::Hello, this, true);
    ns3::Simulator::Stop (ns3::MilliSeconds (90));
    ns3::Simulator::Run ();
    NS_TEST_EXPECT_MSG_EQ ((m_routerInterests > 0), true,
                           "A real RSU proxy request must reach the Router peer");
    NS_TEST_EXPECT_MSG_EQ (m_wirelessData, 1,
                           "PIT-forwarded Data must not be cached under the sender RSU and replayed");
    NS_TEST_EXPECT_MSG_EQ (m_receivedData, 1, "The OBU must receive exactly one business Data");
    m_connections.clear ();
    ns3::Simulator::Destroy ();
  }

  ReturnFormat m_format;
  const ndn::Name m_name {"/com/baidu/neural-buffer-test/1"};
  ns3::NodeContainer m_nodes;
  std::shared_ptr<nfd::Face> m_rsuWireless;
  std::shared_ptr<nfd::Face> m_vehicleFace;
  std::shared_ptr<nfd::Face> m_routerFace;
  std::shared_ptr<nfd::Face> m_appFace;
  std::vector<ndn::util::signal::ScopedConnection> m_connections;
  uint64_t m_vehicleMac = 0;
  uint32_t m_routerInterests = 0;
  uint32_t m_appData = 0;
  uint32_t m_wirelessData = 0;
  uint32_t m_receivedData = 0;
  bool m_replyScheduled = false;
};

class RsuNeuralReturnBufferSuite : public ns3::TestSuite
{
public:
  RsuNeuralReturnBufferSuite () : TestSuite ("vndn-rsu-neural-return-buffer", UNIT)
  {
    AddTestCase (new RsuNeuralReturnBufferTest (
        ReturnFormat::PREPARED_ROUTER,
        "Prepared Router return is forwarded once and never replayed for a sender-RSU hello"),
        TestCase::QUICK);
    AddTestCase (new RsuNeuralReturnBufferTest (
        ReturnFormat::LEGACY_OBU,
        "Unprepared legacy OBU-tag return still waits for and uses the real OBU hello"),
        TestCase::QUICK);
    AddTestCase (new RsuNeuralReturnBufferTest (
        ReturnFormat::LEGACY_OBU_WITH_TARGET,
        "A nonzero target alone does not suppress a genuine legacy OBU fallback"),
        TestCase::QUICK);
  }
};

static RsuNeuralReturnBufferSuite g_rsuNeuralReturnBufferSuite;

} // namespace
