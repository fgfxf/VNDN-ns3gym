/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include "ns3/test.h"
#include "ns3/boolean.h"
#include "ns3/error-model.h"
#include "ns3/mac48-address.h"
#include "ns3/node.h"
#include "ns3/queue.h"
#include "ns3/simple-channel.h"
#include "ns3/simple-net-device.h"
#include "ns3/simulator.h"
#include "ns3/ndnSIM/apps/ndn-app.hpp"
#include "ns3/ndnSIM/model/ndn-app-link-service.hpp"
#include "ns3/ndnSIM/model/ndn-block-header.hpp"
#include "ns3/ndnSIM/model/ndn-net-device-transport.hpp"
#include "ns3/ndnSIM/NFD/daemon/face/face.hpp"
#include "ns3/ndnSIM/NFD/daemon/face/generic-link-service.hpp"
#include "ns3/ndnSIM/NFD/daemon/face/internal-transport.hpp"
#include <ndn-cxx/encoding/block-helpers.hpp>
#include <ndn-cxx/lp/fields.hpp>
#include <ndn-cxx/lp/packet.hpp>
#include <ndn-cxx/lp/vndn-tag.hpp>
#include <algorithm>
#include <memory>
#include <string>
#include <vector>

namespace {

namespace lp = ndn::lp;
using nfd::EndpointId;

uint64_t
EncodeMac (const char *text)
{
  const ns3::Address address = ns3::Mac48Address (text);
  uint64_t result = 0;
  // Use the existing VndnTag Address representation, including type and length.
  address.CopyAllTo (reinterpret_cast<uint8_t *> (&result), sizeof (result));
  return result;
}

bool
SameWire (const ndn::Block &left, const ndn::Block &right)
{
  return left.size () == right.size () &&
         std::equal (left.begin (), left.end (), right.begin ());
}

std::shared_ptr<ndn::Data>
MakeData (size_t size, bool tagged, uint64_t target)
{
  auto data = std::make_shared<ndn::Data> (ndn::Name ("/com/baidu/fragment-test"));
  auto content = std::make_shared<ndn::Buffer> (size);
  for (size_t i = 0; i < size; ++i)
    (*content)[i] = static_cast<uint8_t> ((i * 31 + 7) % 251);
  data->setContent (content);
  ndn::Signature signature;
  signature.setInfo (ndn::SignatureInfo (static_cast<ndn::tlv::SignatureTypeValue> (255)));
  signature.setValue (ndn::makeNonNegativeIntegerBlock (ndn::tlv::SignatureValue, 0));
  data->setSignature (signature);
  if (tagged)
    data->setTag (std::make_shared<lp::VndnTag> (1, 0, target));
  data->wireEncode ();
  return data;
}

nfd::face::GenericLinkService::Options
LinkOptions ()
{
  nfd::face::GenericLinkService::Options options;
  options.allowFragmentation = true;
  options.allowReassembly = true;
  // Match the project's disabled LP reliability setting. MAC retry behavior is
  // covered by scenario validation, not simulated by this lossless fixture.
  return options;
}

struct SentPacket
{
  ndn::Block wire;
  EndpointId endpoint;
};

class RecordingTransport : public nfd::face::Transport
{
public:
  explicit RecordingTransport (
      ndn::nfd::LinkType type,
      ndn::nfd::FaceScope scope = ndn::nfd::FACE_SCOPE_NON_LOCAL)
  {
    setLocalUri (nfd::FaceUri ("dummy://"));
    setRemoteUri (nfd::FaceUri ("dummy://"));
    setScope (scope);
    setPersistency (ndn::nfd::FACE_PERSISTENCY_PERSISTENT);
    setLinkType (type);
    setMtu (1500);
  }

  void Inject (const ndn::Block &wire, EndpointId source) { receive (wire, source); }
  std::vector<SentPacket> sent;

private:
  void doSend (const ndn::Block &wire, const EndpointId &endpoint) override
  {
    sent.push_back ({wire, endpoint});
  }
  void doClose () override { setState (nfd::face::TransportState::CLOSED); }
};

struct LinkFixture
{
  explicit LinkFixture (ndn::nfd::LinkType type)
  {
    auto transport = std::make_unique<RecordingTransport> (type);
    recorder = transport.get ();
    face = std::make_unique<nfd::Face> (
        std::make_unique<nfd::face::GenericLinkService> (LinkOptions ()), std::move (transport));
    face->afterReceiveData.connect ([this] (const ndn::Data &data, const EndpointId &source) {
      received.push_back (std::make_shared<ndn::Data> (data));
      sources.push_back (source);
    });
  }
  std::unique_ptr<nfd::Face> face;
  RecordingTransport *recorder;
  std::vector<std::shared_ptr<ndn::Data>> received;
  std::vector<EndpointId> sources;
};

class FragmentDestinationCase : public ns3::TestCase
{
public:
  FragmentDestinationCase (const std::string &name, ndn::nfd::LinkType type, bool tagged,
                           bool nonzeroTag, bool nonzeroEndpoint, size_t payload)
      : TestCase (name), m_type (type), m_tagged (tagged), m_nonzeroTag (nonzeroTag),
        m_nonzeroEndpoint (nonzeroEndpoint), m_payload (payload)
  {
  }

private:
  void DoRun () override
  {
    const uint64_t target = m_nonzeroTag ? EncodeMac ("00:00:00:00:00:03") : 0;
    const EndpointId original = m_nonzeroEndpoint ? EncodeMac ("00:00:00:00:00:04") : 0;
    const EndpointId expected = m_tagged && target != 0 ? target : original;
    LinkFixture sender (m_type);
    LinkFixture receiver (m_type);
    auto data = MakeData (m_payload, m_tagged, target);
    sender.face->sendData (*data, original);
    const auto &sent = sender.recorder->sent;
    NS_TEST_ASSERT_MSG_EQ (sent.empty (), false, "Real GLS must produce transport packets");
    NS_TEST_EXPECT_MSG_EQ ((sent.size () > 1), (m_payload > 1500),
                           "A 10KB Data fragments; a small Data remains one packet");
    size_t tagCount = 0;
    for (const auto &packet : sent)
      {
        NS_TEST_EXPECT_MSG_EQ (packet.endpoint, expected,
                               "Every fragment must retain the complete packet destination");
        NS_TEST_EXPECT_MSG_EQ ((packet.wire.size () <= 1500), true, "Encoded LP respects MTU");
        lp::Packet decoded (packet.wire);
        tagCount += decoded.has<lp::VndnTagField> ();
      }
    NS_TEST_EXPECT_MSG_EQ (tagCount, (m_tagged ? 1u : 0u),
                           "Packet-level tag stays on the first fragment only");

    const EndpointId source = EncodeMac ("00:00:00:00:00:09");
    for (auto it = sent.rbegin (); it != sent.rend (); ++it)
      receiver.recorder->Inject (it->wire, source);
    NS_TEST_ASSERT_MSG_EQ (receiver.received.size (), 1, "Reverse-order fragments reassemble once");
    NS_TEST_EXPECT_MSG_EQ (SameWire (receiver.received.front ()->wireEncode (), data->wireEncode ()),
                           true, "Reassembled complete Data must exactly equal the original bytes");
    NS_TEST_EXPECT_MSG_EQ (receiver.sources.front (), source,
                           "The received source endpoint is distinct from outgoing destination");
    if (m_tagged)
      {
        auto tag = receiver.received.front ()->getTag<lp::VndnTag> ();
        NS_TEST_ASSERT_MSG_EQ ((tag != nullptr), true, "Reassembly preserves first-fragment metadata");
        NS_TEST_EXPECT_MSG_EQ (tag->getTargetMac (), target, "The original target survives reassembly");
      }
  }
  void DoTeardown () override { ns3::Simulator::Destroy (); }

  ndn::nfd::LinkType m_type;
  bool m_tagged;
  bool m_nonzeroTag;
  bool m_nonzeroEndpoint;
  size_t m_payload;
};

// Capture the actual Send call made by production NetDeviceTransport. The
// device replaces only the lossless boundary beyond Send; destination selection
// and BlockHeader serialization are not copied or reimplemented in this test.
class RecordingNetDevice : public ns3::SimpleNetDevice
{
public:
  static ns3::TypeId GetTypeId ()
  {
    static ns3::TypeId tid = ns3::TypeId ("ns3::VndnFragmentRecordingNetDevice")
      .SetParent<ns3::SimpleNetDevice> ()
      .AddConstructor<RecordingNetDevice> ();
    return tid;
  }
  struct Transmission
  {
    ns3::Ptr<ns3::Packet> packet;
    ns3::Address destination;
    uint16_t protocol;
  };
  bool Send (ns3::Ptr<ns3::Packet> packet, const ns3::Address &destination,
             uint16_t protocol) override
  {
    sent.push_back ({packet->Copy (), destination, protocol});
    return true;
  }
  std::vector<Transmission> sent;
};

class NetDeviceDestinationCase : public ns3::TestCase
{
public:
  NetDeviceDestinationCase (const std::string &name, bool p2p, bool tagged,
                            bool nonzeroTag, bool nonzeroEndpoint,
                            bool directTransport = false, bool controlInterest = false)
      : TestCase (name), m_p2p (p2p), m_tagged (tagged), m_nonzeroTag (nonzeroTag),
        m_nonzeroEndpoint (nonzeroEndpoint), m_directTransport (directTransport),
        m_controlInterest (controlInterest)
  {
  }

private:
  void DoRun () override
  {
    auto node = ns3::CreateObject<ns3::Node> ();
    auto device = ns3::CreateObject<RecordingNetDevice> ();
    device->SetAddress (ns3::Mac48Address ("00:00:00:00:00:02"));
    device->SetAttribute ("PointToPointMode", ns3::BooleanValue (m_p2p));
    device->SetMtu (1500);
    node->AddDevice (device);
    const auto type = m_p2p ? ndn::nfd::LINK_TYPE_POINT_TO_POINT : ndn::nfd::LINK_TYPE_AD_HOC;
    auto transport = std::make_unique<ns3::ndn::NetDeviceTransport> (
        node, device, "netdev://[00:00:00:00:00:02]", "netdev://[ff:ff:ff:ff:ff:ff]",
        ndn::nfd::FACE_SCOPE_NON_LOCAL, ndn::nfd::FACE_PERSISTENCY_PERSISTENT, type);
    nfd::Face face (std::make_unique<nfd::face::GenericLinkService> (LinkOptions ()),
                    std::move (transport));
    const uint64_t target = m_nonzeroTag ? EncodeMac ("00:00:00:00:00:03") : 0;
    const EndpointId original = m_nonzeroEndpoint ? EncodeMac ("00:00:00:00:00:04") : 0;
    uint64_t expected = m_tagged && target != 0 ? target : original;
    if (m_directTransport && original != 0)
      expected = original; // A transport must honor the resolved whole-packet endpoint.
    ns3::Address destination = device->GetBroadcast ();
    if (!m_p2p && expected != 0)
      destination.CopyAllFrom (reinterpret_cast<const uint8_t *> (&expected), sizeof (expected));

    if (m_controlInterest)
      {
        auto interest = std::make_shared<ndn::Interest> (ndn::Name ("/vndn/control/hello"));
        interest->setNonce (1234);
        interest->setCanBePrefix (false);
        if (m_tagged)
          interest->setTag (std::make_shared<lp::VndnTag> (1, 0, target));
        face.sendInterest (*interest, original);
      }
    else
      {
        auto data = MakeData (m_directTransport ? 32 : 10240, m_tagged, target);
        if (m_directTransport)
          {
            lp::Packet packet (data->wireEncode ());
            if (m_tagged)
              packet.set<lp::VndnTagField> (lp::VndnTag (1, 0, target));
            face.getTransport ()->send (packet.wireEncode (), original);
          }
        else
          face.sendData (*data, original);
      }
    NS_TEST_ASSERT_MSG_EQ (device->sent.empty (), false, "Production transport must call device Send");
    NS_TEST_EXPECT_MSG_EQ ((device->sent.size () > 1), (!m_directTransport && !m_controlInterest),
                           "Fragmentation must occur before the real device boundary");
    for (const auto &tx : device->sent)
      {
        NS_TEST_EXPECT_MSG_EQ ((tx.destination == destination), true,
                               "Every actual device Send uses the intended unicast/broadcast address");
        NS_TEST_EXPECT_MSG_EQ (tx.protocol, 0x7777, "NDN device protocol remains unchanged");
        auto packet = tx.packet->Copy ();
        ns3::ndn::BlockHeader header;
        packet->RemoveHeader (header);
        NS_TEST_EXPECT_MSG_EQ (packet->GetSize (), 0, "Transport serializes exactly one LP block");
        NS_TEST_EXPECT_MSG_EQ ((header.getBlock ().size () <= device->GetMtu ()), true,
                               "Serialized block fits the configured device MTU");
      }
  }
  void DoTeardown () override { ns3::Simulator::Destroy (); }

  bool m_p2p;
  bool m_tagged;
  bool m_nonzeroTag;
  bool m_nonzeroEndpoint;
  bool m_directTransport;
  bool m_controlInterest;
};

class RecordingLocalApp : public ns3::ndn::App
{
public:
  static ns3::TypeId GetTypeId ()
  {
    static ns3::TypeId tid = ns3::TypeId ("ns3::VndnFragmentRecordingLocalApp")
      .SetParent<ns3::ndn::App> ()
      .AddConstructor<RecordingLocalApp> ();
    return tid;
  }
  void OnData (std::shared_ptr<const ndn::Data> data) override { received.push_back (data); }
  std::vector<std::shared_ptr<const ndn::Data>> received;

private:
  void StartApplication () override {}
  void StopApplication () override {}
};

class LocalApplicationUnchangedCase : public ns3::TestCase
{
public:
  LocalApplicationUnchangedCase ()
      : TestCase ("Local AppLinkService delivers complete tagged Data without network fragments")
  {
  }

private:
  void DoRun () override
  {
    auto node = ns3::CreateObject<ns3::Node> ();
    auto app = ns3::CreateObject<RecordingLocalApp> ();
    node->AddApplication (app);
    auto transport = std::make_unique<RecordingTransport> (
        ndn::nfd::LINK_TYPE_POINT_TO_POINT, ndn::nfd::FACE_SCOPE_LOCAL);
    auto *recorder = transport.get ();
    nfd::Face face (std::make_unique<ns3::ndn::AppLinkService> (app), std::move (transport));
    auto data = MakeData (10240, true, EncodeMac ("00:00:00:00:00:03"));
    face.sendData (*data, EncodeMac ("00:00:00:00:00:04"));
    ns3::Simulator::Run ();
    NS_TEST_ASSERT_MSG_EQ (app->received.size (), 1, "Existing local application receives one Data");
    NS_TEST_EXPECT_MSG_EQ (SameWire (app->received.front ()->wireEncode (), data->wireEncode ()),
                           true, "Local delivery preserves the complete Data");
    NS_TEST_EXPECT_MSG_EQ (recorder->sent.size (), 0, "Local path must not send network fragments");
    auto tag = app->received.front ()->getTag<lp::VndnTag> ();
    NS_TEST_ASSERT_MSG_EQ ((tag != nullptr), true, "Local application keeps packet metadata");
    NS_TEST_EXPECT_MSG_EQ (tag->getTargetMac (), EncodeMac ("00:00:00:00:00:03"),
                           "Local metadata is not replaced by the unrelated endpoint");
  }
  void DoTeardown () override { ns3::Simulator::Destroy (); }
};

class RecordingInternalPeer : public nfd::face::InternalTransportBase
{
public:
  void receivePacket (const ndn::Block &packet) override { received.push_back (packet); }
  std::vector<ndn::Block> received;
};

class InternalTransportUnchangedCase : public ns3::TestCase
{
public:
  InternalTransportUnchangedCase ()
      : TestCase ("Local InternalForwarderTransport preserves complete tagged Data at unlimited MTU")
  {
  }

private:
  void DoRun () override
  {
    RecordingInternalPeer peer;
    auto transport = std::make_unique<nfd::face::InternalForwarderTransport> ();
    transport->setPeer (&peer);
    nfd::Face face (std::make_unique<nfd::face::GenericLinkService> (LinkOptions ()),
                    std::move (transport));
    const uint64_t target = EncodeMac ("00:00:00:00:00:03");
    auto data = MakeData (10240, true, target);
    face.sendData (*data, EncodeMac ("00:00:00:00:00:04"));
    NS_TEST_ASSERT_MSG_EQ (peer.received.size (), 1, "Real local transport hands one packet to peer");
    lp::Packet packet (peer.received.front ());
    NS_TEST_EXPECT_MSG_EQ (packet.has<lp::FragCountField> (), false,
                           "Unlimited local MTU does not introduce fragmentation");
    NS_TEST_ASSERT_MSG_EQ (packet.has<lp::FragmentField> (), true, "Local packet contains Data");
    const auto fragment = packet.get<lp::FragmentField> ();
    const ndn::Block wire (&*fragment.first, std::distance (fragment.first, fragment.second));
    NS_TEST_EXPECT_MSG_EQ (SameWire (wire, data->wireEncode ()), true,
                           "Internal local delivery preserves all Data bytes");
    NS_TEST_ASSERT_MSG_EQ (packet.has<lp::VndnTagField> (), true, "Local packet retains metadata");
    NS_TEST_EXPECT_MSG_EQ (packet.get<lp::VndnTagField> ().getTargetMac (), target,
                           "Changing outgoing endpoint does not rewrite the original local tag");
  }
  void DoTeardown () override { ns3::Simulator::Destroy (); }
};

class FragmentDestinationSuite : public ns3::TestSuite
{
public:
  FragmentDestinationSuite () : TestSuite ("vndn-fragment-destination", UNIT)
  {
    const auto adhoc = ndn::nfd::LINK_TYPE_AD_HOC;
    const auto p2p = ndn::nfd::LINK_TYPE_POINT_TO_POINT;
    AddTestCase (new FragmentDestinationCase ("GLS tagged 10KB default endpoint", adhoc, true, true, false, 10240), TestCase::QUICK);
    AddTestCase (new FragmentDestinationCase ("GLS tagged 10KB overrides endpoint", adhoc, true, true, true, 10240), TestCase::QUICK);
    AddTestCase (new FragmentDestinationCase ("GLS untagged keeps zero endpoint", adhoc, false, false, false, 10240), TestCase::QUICK);
    AddTestCase (new FragmentDestinationCase ("GLS untagged preserves nonzero endpoint", adhoc, false, false, true, 10240), TestCase::QUICK);
    AddTestCase (new FragmentDestinationCase ("GLS zero tag preserves nonzero endpoint", adhoc, true, false, true, 10240), TestCase::QUICK);
    AddTestCase (new FragmentDestinationCase ("GLS zero tag keeps zero endpoint", adhoc, true, false, false, 10240), TestCase::QUICK);
    AddTestCase (new FragmentDestinationCase ("GLS P2P untagged default endpoint", p2p, false, false, false, 10240), TestCase::QUICK);
    AddTestCase (new FragmentDestinationCase ("GLS P2P tagged endpoint contract", p2p, true, true, false, 10240), TestCase::QUICK);
    AddTestCase (new FragmentDestinationCase ("GLS tagged unfragmented Data", adhoc, true, true, false, 256), TestCase::QUICK);
    AddTestCase (new NetDeviceDestinationCase ("Device sends every tagged Data fragment to target", false, true, true, false), TestCase::QUICK);
    AddTestCase (new NetDeviceDestinationCase ("Device sends untagged Data to nonzero endpoint", false, false, false, true), TestCase::QUICK);
    AddTestCase (new NetDeviceDestinationCase ("Device endpoint wins over first-fragment tag", false, true, true, true, true), TestCase::QUICK);
    AddTestCase (new NetDeviceDestinationCase ("Device falls back to LP tag when endpoint is zero", false, true, true, false, true), TestCase::QUICK);
    AddTestCase (new NetDeviceDestinationCase ("Device untagged zero endpoint broadcasts", false, false, false, false), TestCase::QUICK);
    AddTestCase (new NetDeviceDestinationCase ("Device zero-tag zero-endpoint control broadcasts", false, true, false, false, false, true), TestCase::QUICK);
    AddTestCase (new NetDeviceDestinationCase ("Device untagged zero-endpoint control broadcasts", false, false, false, false, false, true), TestCase::QUICK);
    AddTestCase (new NetDeviceDestinationCase ("P2P device keeps broadcast despite target and endpoint", true, true, true, true), TestCase::QUICK);
    AddTestCase (new LocalApplicationUnchangedCase, TestCase::QUICK);
    AddTestCase (new InternalTransportUnchangedCase, TestCase::QUICK);
  }
};

static FragmentDestinationSuite g_fragmentDestinationSuite;

} // namespace
