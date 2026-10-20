/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include "ns3/test.h"
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/ndnSIM-module.h"
#include "ns3/vndn-router-app.h"
#include "ns3/ndnSIM/apps/ndn-app.hpp"
#include "ns3/ndnSIM/model/ndn-app-link-service.hpp"
#include "ns3/ndnSIM/NFD/daemon/fw/forwarder.hpp"
#include "ns3/ndnSIM/NFD/daemon/fw/best-route-strategy2.hpp"
#include "ns3/ndnSIM/NFD/daemon/table/pit.hpp"
#include "ns3/ndnSIM/NFD/daemon/table/fib.hpp"
#include "ns3/ndnSIM/NFD/daemon/table/strategy-choice.hpp"

#include <ndn-cxx/encoding/block-helpers.hpp>
#include <ndn-cxx/lp/vndn-tag.hpp>
#include <ndn-cxx/util/signal/scoped-connection.hpp>

#include <map>
#include <memory>
#include <sstream>
#include <vector>

namespace {

// No SUMO, Gym, mock Forwarder, private-member access, or manual signal emission.
// All test traffic crosses a real P2P NetDevice and the production NFD pipeline.
constexpr uint64_t OBU_MAC = 0x010203040506ULL;

std::shared_ptr<ndn::Data>
SignedData (const ndn::Name &name, const std::string &content)
{
  auto data = std::make_shared<ndn::Data> (name);
  data->setContent (reinterpret_cast<const uint8_t *> (content.data ()), content.size ());
  ns3::ndn::StackHelper::getKeyChain ().sign (*data);
  return data;
}

class PitTestServer : public ns3::ndn::App
{
public:
  enum Reply { DATA, NACK, SILENT };

  static ns3::TypeId GetTypeId ()
  {
    static ns3::TypeId tid = ns3::TypeId ("VndnRouterPitTestServer")
        .SetParent<ns3::ndn::App> ().AddConstructor<PitTestServer> ();
    return tid;
  }

  Reply reply = DATA;
  uint32_t received = 0;
  uint32_t nacksSent = 0;

  void OnInterest (std::shared_ptr<const ndn::Interest> interest) override
  {
    ns3::ndn::App::OnInterest (interest);
    ++received;
    if (reply != SILENT)
      ns3::Simulator::Schedule (ns3::MilliSeconds (30),
                               &PitTestServer::Respond, this, interest);
  }

private:
  void StartApplication () override
  {
    ns3::ndn::App::StartApplication ();
    ns3::ndn::FibHelper::AddRoute (GetNode (), "/com/baidu", m_face, 0);
    ns3::ndn::FibHelper::AddRoute (GetNode (), "/outside", m_face, 0);
  }

  void Respond (std::shared_ptr<const ndn::Interest> interest)
  {
    if (!m_active)
      return;
    if (reply == NACK)
      {
        ndn::lp::Nack nack (*interest);
        nack.setReason (ndn::lp::NackReason::NO_ROUTE);
        ++nacksSent;
        m_appLink->onReceiveNack (nack);
      }
    else
      {
        auto data = SignedData (interest->getName (), "real delayed server response");
        m_appLink->onReceiveData (*data);
      }
  }
};

enum class Case
{
  SINGLE, DUAL, LATE_ROUTE, NON_NEURAL, NO_PENDING, SELECTOR,
  OUTSIDE_PREFIX, STOP, NACK, TIMEOUT
};

class RouterNeuralPitTest : public ns3::TestCase
{
public:
  RouterNeuralPitTest (Case scenario, const std::string &description)
    : TestCase (description), m_case (scenario)
  {
  }

private:
  struct Snapshot
  {
    std::shared_ptr<nfd::pit::Entry> entry;
    size_t network = 0;
    size_t local = 0;
    bool serverOut = false;
    uint32_t nonce = 0;
    ndn::time::steady_clock::TimePoint renewed;
    ndn::time::steady_clock::TimePoint expiry;
    size_t appInterests = 0;
  };

  Snapshot Read (const ndn::Interest &interest)
  {
    Snapshot result;
    result.entry = m_forwarder->getPit ().find (interest);
    result.appInterests = m_appInterests;
    if (result.entry == nullptr)
      return result;
    for (const auto &record : result.entry->getInRecords ())
      {
        if (record.getFace ().getScope () == ndn::nfd::FACE_SCOPE_LOCAL)
          ++result.local;
        else
          ++result.network;
      }
    auto out = result.entry->getOutRecord (*m_routerFaces[2]);
    if (out != result.entry->out_end ())
      {
        result.serverOut = true;
        result.nonce = out->getLastNonce ();
        result.renewed = out->getLastRenewed ();
        result.expiry = out->getExpiry ();
      }
    return result;
  }

  bool ExpectCleanup () const
  {
    return m_case != Case::NON_NEURAL && m_case != Case::NO_PENDING &&
           m_case != Case::OUTSIDE_PREFIX && m_case != Case::LATE_ROUTE;
  }

  void ObserveBefore (const ndn::Interest &interest)
  {
    if (interest.getName () == m_name &&
        (interest.getNonce () == 201 || interest.getNonce () == 202))
      m_before[interest.getNonce ()] = Read (interest);
  }

  void ObserveAfter (const ndn::Interest &interest)
  {
    if (interest.getName () != m_name ||
        (interest.getNonce () != 201 && interest.getNonce () != 202))
      return;
    const auto before = m_before.at (interest.getNonce ());
    const auto after = Read (interest);
    ++m_duplicateObservations;
    NS_TEST_EXPECT_MSG_EQ ((before.entry != nullptr), true,
                           "Duplicate must reach the real PIT before the Router observer");
    NS_TEST_EXPECT_MSG_EQ ((before.network > 0), true,
                           "Forwarder must really recreate the remote in-record");
    NS_TEST_EXPECT_MSG_EQ (after.entry.get (), before.entry.get (),
                           "Cleanup must preserve the existing PIT entry");
    NS_TEST_EXPECT_MSG_EQ (after.network, (ExpectCleanup () ? 0 : before.network),
                           "Only a pending neural business Interest owns remote cleanup");
    NS_TEST_EXPECT_MSG_EQ (after.local, before.local,
                           "The Router application's downstream in-record must survive");
    NS_TEST_EXPECT_MSG_EQ (after.serverOut, before.serverOut,
                           "The outstanding server transmission must survive");
    NS_TEST_EXPECT_MSG_EQ (after.nonce, before.nonce, "Do not change server out-record nonce");
    NS_TEST_EXPECT_MSG_EQ ((after.renewed == before.renewed), true,
                           "Do not renew server out-record while deleting downstreams");
    NS_TEST_EXPECT_MSG_EQ ((after.expiry == before.expiry), true,
                           "Do not shorten or renew server out-record expiry");
    NS_TEST_EXPECT_MSG_EQ (after.appInterests, before.appInterests,
                           "The observer itself must not deliver another app Interest");
    NS_TEST_EXPECT_MSG_EQ (m_appInterests, (m_case == Case::NO_PENDING ? 0 : 1),
                           "Within 10ms BestRoute suppresses the repeated app delivery");
    if (m_case != Case::NO_PENDING)
      {
        NS_TEST_EXPECT_MSG_EQ (after.local, 1, "Keep the live local application downstream");
        NS_TEST_EXPECT_MSG_EQ (after.serverOut, true, "Keep the live server upstream");
        NS_TEST_EXPECT_MSG_EQ ((after.expiry > ndn::time::steady_clock::now ()), true,
                               "The server request must still be outstanding");
      }
  }

  void Configure ()
  {
    auto &fib = m_forwarder->getFib ();
    const auto &root = fib.findLongestPrefixMatch (ndn::Name ("/"));
    for (const auto &hop : root.getNextHops ())
      if (hop.getFace ().getScope () == ndn::nfd::FACE_SCOPE_LOCAL)
        m_appFace = hop.getFace ().shared_from_this ();
    NS_TEST_EXPECT_MSG_EQ ((m_appFace != nullptr), true, "Router's real ndn::Face registered /");
    if (m_appFace == nullptr)
      return;

    // ResolveServerFace uses /com/baidu. A more specific business route delivers
    // the first RSU request to the real app; its server proxy still uses NextHop.
    // This controls only FIB input, never changes Router's default BestRoute2.
    auto entry = fib.insert (m_name).first;
    fib.addOrUpdateNextHop (*entry,
                           m_case == Case::NO_PENDING ? *m_routerFaces[2] : *m_appFace, 0);
    NS_TEST_EXPECT_MSG_EQ (
        m_forwarder->getStrategyChoice ().findEffectiveStrategy (m_name).getInstanceName (),
        nfd::fw::BestRouteStrategy2::getStrategyName (),
        "Do not replace Router BestRoute2 with multicast to make the test pass");
    m_connections.emplace_back (
        m_appFace->getLinkService ()->afterSendInterest.connect (
            [this] (const ndn::Interest &interest) {
              if (interest.getName () == m_name)
                ++m_appInterests;
            }));
    for (size_t i = 0; i < 2; ++i)
      {
        m_connections.emplace_back (
            m_routerFaces[i]->afterReceiveInterest.connect (
                [this] (const ndn::Interest &interest, const nfd::EndpointId &) {
                  ObserveAfter (interest);
                }));
        m_connections.emplace_back (
            m_routerFaces[i]->getLinkService ()->afterSendData.connect (
                [this, i] (const ndn::Data &data) {
                  if (data.getName () != m_name)
                    return;
                  ++m_businessData[i];
                  auto tag = data.getTag<ndn::lp::VndnTag> ();
                  if (tag != nullptr && tag->getTargetMac () == OBU_MAC &&
                      tag->getSenderNodeId () == m_nodes.Get (i)->GetId ())
                    ++m_taggedData[i];
                }));
      }
  }

  void Handshake (size_t peer)
  {
    ndn::Name name ("/vndn/control/p2p-handshake/rsu");
    name.appendNumber (m_nodes.Get (peer)->GetId ()).appendNumber (0);
    std::ostringstream content;
    content << "rsu " << m_nodes.Get (peer)->GetId ();
    m_peerFaces[peer]->sendData (*SignedData (name, content.str ()), 0);
  }

  std::shared_ptr<ndn::Interest> Interest (uint32_t nonce, bool neural = true,
                                        bool differentSelector = false)
  {
    auto interest = std::make_shared<ndn::Interest> (m_name);
    interest->setCanBePrefix (differentSelector);
    interest->setMustBeFresh (false);
    interest->setNonce (nonce);
    interest->setInterestLifetime (ndn::time::milliseconds (50));
    auto tag = std::make_shared<ndn::lp::VndnTag> (999, OBU_MAC, 0);
    if (neural)
      {
        tag->setReturnRsuPrimary (m_nodes.Get (0)->GetId ());
        if (m_case == Case::DUAL)
          tag->setReturnRsuSecondary (m_nodes.Get (1)->GetId ());
      }
    interest->setTag (tag);
    return interest;
  }

  void SendInterest (size_t peer, uint32_t nonce)
  {
    bool neural = m_case != Case::NON_NEURAL && m_case != Case::LATE_ROUTE;
    m_peerFaces[peer]->sendInterest (*Interest (nonce, neural), 0);
  }

  void SendLateRoute ()
  {
    auto before = Read (*Interest (100, false));
    NS_TEST_EXPECT_MSG_EQ ((before.network > 0), true,
                           "Late-route fixture must first retain an ordinary remote downstream");
    ndn::Name name ("/vndn/control/neural-route");
    name.appendNumber (m_nodes.Get (0)->GetId ()).appendNumber (1);
    std::ostringstream content;
    content << m_name.toUri () << ' ' << m_nodes.Get (0)->GetId ();
    m_peerFaces[0]->sendData (*SignedData (name, content.str ()), 0);
  }

  void CheckLateRoute ()
  {
    auto state = Read (*Interest (100, false));
    NS_TEST_EXPECT_MSG_EQ ((state.entry != nullptr), true, "Late route preserves the server PIT");
    NS_TEST_EXPECT_MSG_EQ (state.network, 0, "Activating neural route removes old remote in-record");
    NS_TEST_EXPECT_MSG_EQ (state.local, 1, "Late route preserves local app downstream");
    NS_TEST_EXPECT_MSG_EQ (state.serverOut, true, "Late route preserves outstanding server request");
    NS_TEST_EXPECT_MSG_EQ (m_appInterests, 1, "Late route works without a second app Interest");
  }

  void SendSelector ()
  {
    m_peerFaces[1]->sendInterest (*Interest (203, true, true), 0);
  }

  void CheckSelector ()
  {
    auto ordinary = Read (*Interest (100));
    auto other = Read (*Interest (203, true, true));
    NS_TEST_EXPECT_MSG_EQ ((ordinary.entry != nullptr), true, "Original pending PIT still exists");
    NS_TEST_EXPECT_MSG_EQ ((other.entry != nullptr), true, "Different selector has a distinct real PIT");
    NS_TEST_EXPECT_MSG_NE (ordinary.entry.get (), other.entry.get (), "Never conflate selectors");
    NS_TEST_EXPECT_MSG_EQ (ordinary.network, 0, "Original neural PIT remains protected");
    NS_TEST_EXPECT_MSG_EQ (ordinary.local, 1, "Original local downstream remains");
    NS_TEST_EXPECT_MSG_EQ (other.network, 1, "Do not delete a different selector's downstream");
  }

  void ProbeAfterStop ()
  {
    auto &fib = m_forwarder->getFib ();
    fib.erase (m_name);
    auto entry = fib.insert (m_name).first;
    fib.addOrUpdateNextHop (*entry, *m_routerFaces[2], 0);
    SendInterest (0, 300);
  }

  void CheckAfterStop ()
  {
    auto state = Read (*Interest (300));
    NS_TEST_EXPECT_MSG_EQ ((state.entry != nullptr), true, "P2P forwarding survives Router destruction");
    NS_TEST_EXPECT_MSG_EQ (state.network, 1, "Stopped Router must not remove new remote downstreams");
    NS_TEST_EXPECT_MSG_EQ (m_appInterests, 1, "Destroyed app receives no new callback");
  }

  void CheckExpiredAndRetry ()
  {
    auto state = Read (*Interest (100));
    NS_TEST_EXPECT_MSG_EQ ((state.entry == nullptr), true,
                           "Original request must complete Nack/expiry before reuse");
    SendInterest (0, 301);
  }

  void CheckRetry ()
  {
    auto state = Read (*Interest (301));
    NS_TEST_EXPECT_MSG_EQ (m_server->received, 2,
                           "Nack/timeout must release app pending so a fresh proxy reaches server");
    NS_TEST_EXPECT_MSG_EQ (state.local, 1, "Retry creates a new local app downstream");
    NS_TEST_EXPECT_MSG_EQ (state.serverOut, true, "Retry creates a fresh server out-record");
  }

  void DoRun () override
  {
    m_nodes.Create (4); // peer A, peer B, Router, Server
    m_name = ndn::Name (m_case == Case::OUTSIDE_PREFIX
                           ? "/outside/test/1" : "/com/baidu/www/userid/999/1");
    ns3::PointToPointHelper p2p;
    p2p.SetDeviceAttribute ("DataRate", ns3::StringValue ("1Gbps"));
    p2p.SetChannelAttribute ("Delay", ns3::StringValue ("10us"));
    std::vector<ns3::NetDeviceContainer> devices;
    for (uint32_t peer : {0u, 1u, 3u})
      devices.push_back (p2p.Install (m_nodes.Get (2), m_nodes.Get (peer)));
    ns3::ndn::StackHelper stack;
    stack.setCsSize (0); // Explicit CS-miss contract; CS-hit is a separate limitation.
    stack.Install (m_nodes);
    auto l3 = m_nodes.Get (2)->GetObject<ns3::ndn::L3Protocol> ();
    m_forwarder = l3->getForwarder ();
    for (size_t i = 0; i < devices.size (); ++i)
      {
        m_routerFaces.push_back (l3->getFaceByNetDevice (devices[i].Get (0)));
        if (i < 2)
          m_peerFaces.push_back (m_nodes.Get (i)->GetObject<ns3::ndn::L3Protocol> ()
                                    ->getFaceByNetDevice (devices[i].Get (1)));
      }
    // Before callbacks are attached after Forwarder, but before Router.Start.
    for (size_t i = 0; i < 2; ++i)
      m_connections.emplace_back (
          m_routerFaces[i]->afterReceiveInterest.connect (
              [this] (const ndn::Interest &interest, const nfd::EndpointId &) {
                ObserveBefore (interest);
              }));
    auto entry = m_forwarder->getFib ().insert (ndn::Name ("/com/baidu")).first;
    m_forwarder->getFib ().addOrUpdateNextHop (*entry, *m_routerFaces[2], 0);
    m_server = ns3::CreateObject<PitTestServer> ();
    if (m_case == Case::NACK)
      m_server->reply = PitTestServer::NACK;
    if (m_case == Case::TIMEOUT || m_case == Case::STOP)
      m_server->reply = PitTestServer::SILENT;
    m_nodes.Get (3)->AddApplication (m_server);
    m_server->SetStartTime (ns3::Seconds (0));
    auto router = ns3::CreateObject<ns3::VndnRouterApp> ();
    m_nodes.Get (2)->AddApplication (router);
    router->SetStartTime (ns3::Seconds (0));
    router->SetStopTime (ns3::MilliSeconds (m_case == Case::STOP ? 40 : 140));

    ns3::Simulator::ScheduleWithContext (m_nodes.Get (2)->GetId (), ns3::MilliSeconds (2),
                                        &RouterNeuralPitTest::Configure, this);
    ns3::Simulator::Schedule (ns3::MilliSeconds (10), &RouterNeuralPitTest::Handshake, this, 0);
    ns3::Simulator::Schedule (ns3::MilliSeconds (11), &RouterNeuralPitTest::Handshake, this, 1);
    ns3::Simulator::Schedule (ns3::MilliSeconds (30), &RouterNeuralPitTest::SendInterest, this, 0, 100);
    ns3::Simulator::Schedule (ns3::MilliSeconds (31), &RouterNeuralPitTest::SendInterest, this, 0, 201);
    if (m_case == Case::DUAL)
      ns3::Simulator::Schedule (ns3::MilliSeconds (32), &RouterNeuralPitTest::SendInterest, this, 1, 202);
    if (m_case == Case::LATE_ROUTE)
      {
        ns3::Simulator::Schedule (ns3::MilliSeconds (33), &RouterNeuralPitTest::SendLateRoute, this);
        ns3::Simulator::Schedule (ns3::MilliSeconds (34), &RouterNeuralPitTest::CheckLateRoute, this);
      }
    if (m_case == Case::SELECTOR)
      {
        ns3::Simulator::Schedule (ns3::MilliSeconds (33), &RouterNeuralPitTest::SendSelector, this);
        ns3::Simulator::Schedule (ns3::MilliSeconds (34), &RouterNeuralPitTest::CheckSelector, this);
      }
    if (m_case == Case::STOP)
      {
        ns3::Simulator::Schedule (ns3::MilliSeconds (45), &RouterNeuralPitTest::ProbeAfterStop, this);
        ns3::Simulator::Schedule (ns3::MilliSeconds (46), &RouterNeuralPitTest::CheckAfterStop, this);
      }
    if (m_case == Case::NACK || m_case == Case::TIMEOUT)
      {
        ns3::Simulator::Schedule (ns3::MilliSeconds (90), &RouterNeuralPitTest::CheckExpiredAndRetry, this);
        ns3::Simulator::Schedule (ns3::MilliSeconds (92), &RouterNeuralPitTest::CheckRetry, this);
      }
    ns3::Simulator::Stop (ns3::MilliSeconds (150));
    ns3::Simulator::Run ();

    NS_TEST_EXPECT_MSG_EQ (m_duplicateObservations, (m_case == Case::DUAL ? 2 : 1),
                           "The fixture must observe every scheduled duplicate");
    if (m_case == Case::SINGLE || m_case == Case::DUAL || m_case == Case::LATE_ROUTE)
      {
        NS_TEST_EXPECT_MSG_EQ (m_server->received, 1, "Do not resend suppressed business Interest");
        NS_TEST_EXPECT_MSG_EQ (m_businessData[0], 1, "Exactly one explicit neural return to RSU A");
        NS_TEST_EXPECT_MSG_EQ (m_taggedData[0], 1, "No bare automatic Data may consume the RSU PIT");
        NS_TEST_EXPECT_MSG_EQ (m_businessData[1], (m_case == Case::DUAL ? 1 : 0),
                               "Only the selected optional second return branch is emitted");
        NS_TEST_EXPECT_MSG_EQ (m_taggedData[1], (m_case == Case::DUAL ? 1 : 0),
                               "Both selected branches must carry the original OBU target MAC");
      }
    if (m_case == Case::NACK)
      NS_TEST_EXPECT_MSG_EQ (m_server->nacksSent, 2, "Both generations received real server Nacks");
    m_connections.clear ();
    ns3::Simulator::Destroy ();
  }

  Case m_case;
  ndn::Name m_name;
  ns3::NodeContainer m_nodes;
  ns3::Ptr<PitTestServer> m_server;
  std::shared_ptr<nfd::Forwarder> m_forwarder;
  std::shared_ptr<nfd::Face> m_appFace;
  std::vector<std::shared_ptr<nfd::Face>> m_routerFaces;
  std::vector<std::shared_ptr<nfd::Face>> m_peerFaces;
  std::vector<ndn::util::signal::ScopedConnection> m_connections;
  std::map<uint32_t, Snapshot> m_before;
  size_t m_appInterests = 0;
  size_t m_duplicateObservations = 0;
  size_t m_businessData[2] = {0, 0};
  size_t m_taggedData[2] = {0, 0};
};

class RouterNeuralPitSuite : public ns3::TestSuite
{
public:
  RouterNeuralPitSuite () : TestSuite ("vndn-router-neural-pit", UNIT)
  {
    AddTestCase (new RouterNeuralPitTest (Case::SINGLE, "Suppressed late Interest keeps only app-owned neural PIT"), TestCase::QUICK);
    AddTestCase (new RouterNeuralPitTest (Case::DUAL, "Two late peers preserve two explicit tagged neural returns"), TestCase::QUICK);
    AddTestCase (new RouterNeuralPitTest (Case::LATE_ROUTE, "Late neural route cleans an already pending ordinary downstream"), TestCase::QUICK);
    AddTestCase (new RouterNeuralPitTest (Case::NON_NEURAL, "Ordinary pending traffic retains its network downstream"), TestCase::QUICK);
    AddTestCase (new RouterNeuralPitTest (Case::NO_PENDING, "No Router pending request means no remote PIT cleanup"), TestCase::QUICK);
    AddTestCase (new RouterNeuralPitTest (Case::SELECTOR, "Same name with different selectors retains its own downstream"), TestCase::QUICK);
    AddTestCase (new RouterNeuralPitTest (Case::OUTSIDE_PREFIX, "Neural-looking non-business traffic is outside cleanup scope"), TestCase::QUICK);
    AddTestCase (new RouterNeuralPitTest (Case::STOP, "Stop and destruction disconnect network observers"), TestCase::QUICK);
    AddTestCase (new RouterNeuralPitTest (Case::NACK, "Real server Nack releases pending state for a new request"), TestCase::QUICK);
    AddTestCase (new RouterNeuralPitTest (Case::TIMEOUT, "Server timeout releases pending state for a new request"), TestCase::QUICK);
  }
};

static RouterNeuralPitSuite g_routerNeuralPitSuite;
} // namespace
