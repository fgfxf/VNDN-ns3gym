/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include "vndn-router.h"
#include "ns3/vndn-router-app.h"

#include "ns3/log.h"
#include "ns3/node-list.h"
#include "ns3/simulator.h"
#include "ns3/ndnSIM/model/ndn-l3-protocol.hpp"
#include "ns3/ndnSIM/NFD/daemon/fw/forwarder.hpp"
#include "ns3/ndnSIM/NFD/daemon/table/fib.hpp"
#include "ns3/ndnSIM/NFD/daemon/table/pit.hpp"
#include "ns3/assert.h"

#include <ndn-cxx/encoding/block-helpers.hpp>
#include <ndn-cxx/lp/tags.hpp>

#include <algorithm>
#include <functional>
#include <stdexcept>
#include <sstream>

NS_LOG_COMPONENT_DEFINE ("ndn.VndnRouter");

namespace vanet {

VndnRouter::VndnRouter ()
{
  m_face.setInterestFilter (
      "/", std::bind (&VndnRouter::ProcessInterest, this, std::placeholders::_2),
      [] (const ndn::Name &, const std::string &reason) {
        throw std::runtime_error ("Failed to register router interest prefix: " + reason);
      });
  m_thisNode = ns3::NodeList::GetNode (ns3::Simulator::GetContext ());
  RegisterP2pFaces ();
  m_face.setDataUnsolicitedProcess (
      std::bind (&VndnRouter::OnP2pHandshakeDataPush, this,
                 std::placeholders::_1, std::placeholders::_2));
}

void
VndnRouter::RegisterP2pFaces ()
{
  auto ndnL3 = m_thisNode->GetObject<ns3::ndn::L3Protocol> ();
  NS_ASSERT_MSG (ndnL3 != nullptr, "Ndn stack should be installed on the router");
  for (uint32_t i = 0; i < m_thisNode->GetNDevices (); ++i)
    {
      auto device = m_thisNode->GetDevice (i);
      if (!device->IsPointToPoint ())
        continue;
      auto face = ndnL3->getFaceByNetDevice (device);
      NS_ASSERT_MSG (face != nullptr, "There is no face associated with the net-device");
      m_p2pFaceIds.push_back (face->getId ());
    }
}

void
VndnRouter::ResolveServerFace ()
{
  auto ndnL3 = m_thisNode->GetObject<ns3::ndn::L3Protocol> ();
  NS_ASSERT_MSG (ndnL3 != nullptr, "Ndn stack should be installed on the router");
  const auto &fibEntry = ndnL3->getForwarder ()->getFib ().findLongestPrefixMatch (
      ndn::Name ("/com/baidu"));
  for (const auto &nextHop : fibEntry.getNextHops ())
    {
      uint64_t faceId = nextHop.getFace ().getId ();
      if (std::find (m_p2pFaceIds.begin (), m_p2pFaceIds.end (), faceId) !=
          m_p2pFaceIds.end ())
        {
          m_serverFaceId = faceId;
          NS_LOG_INFO ("Router " << m_thisNode->GetId ()
                                  << " 服务器出接口faceId=" << m_serverFaceId);
          return;
        }
    }
  NS_LOG_WARN ("Router " << m_thisNode->GetId () << " 未在FIB中找到服务器P2P接口");
}

void
VndnRouter::ForwardInterestToServer (const ndn::Interest &interest, uint64_t returnFaceId)
{
  auto pending = m_pendingRequests.find (interest.getName ());
  if (pending != m_pendingRequests.end ())
    {
      pending->second.returnFaceIds.insert (returnFaceId);
      NS_LOG_DEBUG ("Router 合并同名请求: " << interest.getName ()
                    << " 回程接口数=" << pending->second.returnFaceIds.size ());
      return;
    }

  if (m_serverFaceId == 0)
    ResolveServerFace ();
  if (m_serverFaceId == 0)
    {
      NS_LOG_WARN ("Router 无服务器接口，丢弃请求: " << interest.getName ());
      return;
    }

  PendingRequest request;
  request.originalInterest = std::make_shared<ndn::Interest> (interest);
  request.returnFaceIds.insert (returnFaceId);
  m_pendingRequests.emplace (interest.getName (), std::move (request));

  // 删除基站请求创建的网络 PIT。服务器 Data 只交给 Router app，随后由
  // Router 根据保存的回程接口主动推送，避免 NFD 自动回传造成重复数据。
  auto ndnL3 = m_thisNode->GetObject<ns3::ndn::L3Protocol> ();
  auto &pit = ndnL3->getForwarder ()->getPit ();
  auto pitEntry = pit.find (interest);
  if (pitEntry != nullptr)
    {
      pitEntry->expiryTimer.cancel ();
      pit.erase (pitEntry.get ());
    }

  ndn::Interest serverInterest (interest);
  serverInterest.refreshNonce ();
  serverInterest.setTag (
      std::make_shared<ndn::lp::NextHopFaceIdTag> (m_serverFaceId));
  NS_LOG_INFO ("Router 向服务器请求: " << serverInterest.getName ()
               << " serverFaceId=" << m_serverFaceId);
  m_face.expressInterest (
      serverInterest,
      std::bind (&VndnRouter::OnServerData, this,
                 std::placeholders::_1, std::placeholders::_2),
      std::bind (&VndnRouter::OnServerNack, this,
                 std::placeholders::_1, std::placeholders::_2),
      std::bind (&VndnRouter::OnServerTimeout, this, std::placeholders::_1));
}

void
VndnRouter::OnServerData (const ndn::Interest &interest, const ndn::Data &data)
{
  auto pending = m_pendingRequests.find (interest.getName ());
  if (pending == m_pendingRequests.end ())
    return;

  const std::set<uint64_t> returnFaces = pending->second.returnFaceIds;
  m_pendingRequests.erase (pending);
  for (uint64_t faceId : returnFaces)
    {
      auto response = std::make_shared<ndn::Data> (data);
      response->setTag (std::make_shared<ndn::lp::NextHopFaceIdTag> (faceId));
      response->wireEncode ();
      try
        {
          m_face.put (*response);
          NS_LOG_INFO ("Router 回传服务器数据: " << data.getName ()
                       << " returnFaceId=" << faceId);
        }
      catch (const ndn::Face::OversizedPacketError &e)
        {
          NS_LOG_ERROR ("Router 无法回传超大Data: " << e.what ());
        }
    }
}

void
VndnRouter::OnServerNack (const ndn::Interest &interest, const ndn::lp::Nack &nack)
{
  NS_LOG_WARN ("Router 收到服务器Nack: " << interest.getName ()
               << " reason=" << nack.getReason ());
  m_pendingRequests.erase (interest.getName ());
}

void
VndnRouter::OnServerTimeout (const ndn::Interest &interest)
{
  NS_LOG_WARN ("Router 请求服务器超时: " << interest.getName ());
  m_pendingRequests.erase (interest.getName ());
}

void
VndnRouter::SendP2pHandshake ()
{
  if (!m_active)
    return;

  const uint32_t nodeId = m_thisNode->GetId ();
  m_seenInfrastructureNodes.insert (nodeId);
  ndn::Name name ("/vndn/control/p2p-handshake/router");
  name.appendNumber (nodeId).appendNumber (m_p2pHandshakeRound);
  for (uint64_t faceId : m_p2pFaceIds)
    PushIdentityData (faceId, nodeId, "router", name);
  NS_LOG_INFO ("Router " << nodeId << " 发送第 " << m_p2pHandshakeRound
                          << " 轮P2P身份握手");
  ++m_p2pHandshakeRound;
  if (m_p2pHandshakeRound < 3)
    m_p2pHandshakeEvent = ns3::Simulator::Schedule (
        ns3::MilliSeconds (200), &VndnRouter::SendP2pHandshake, this);
}

void
VndnRouter::PushIdentityData (uint64_t faceId, uint32_t nodeId,
                              const std::string &role, const ndn::Name &name)
{
  std::ostringstream payload;
  payload << role << ' ' << nodeId;
  const std::string content = payload.str ();
  auto data = std::make_shared<ndn::Data> (name);
  data->setContent (std::make_shared<ndn::Buffer> (content.begin (), content.end ()));
  data->setTag (std::make_shared<ndn::lp::NextHopFaceIdTag> (faceId));
  ndn::Signature signature;
  ndn::SignatureInfo signatureInfo (static_cast<ndn::tlv::SignatureTypeValue> (255));
  signature.setInfo (signatureInfo);
  signature.setValue (ndn::makeNonNegativeIntegerBlock (ndn::tlv::SignatureValue, 0));
  data->setSignature (signature);
  data->wireEncode ();
  m_face.put (*data);
}

void
VndnRouter::OnP2pHandshakeDataPush (const ndn::Interest &, const ndn::Data &data)
{
  static const ndn::Name handshakePrefix ("/vndn/control/p2p-handshake");
  if (!handshakePrefix.isPrefixOf (data.getName ()))
    return;
  auto incomingFace = data.getTag<ndn::lp::IncomingFaceIdTag> ();
  if (incomingFace == nullptr)
    return;

  const auto &content = data.getContent ();
  std::istringstream parser (std::string (reinterpret_cast<const char *> (content.value ()),
                                         content.value_size ()));
  std::string role;
  uint32_t nodeId = 0;
  if (!(parser >> role >> nodeId) || nodeId == m_thisNode->GetId ())
    return;

  uint64_t inFaceId = *incomingFace;
  bool isNew = m_seenInfrastructureNodes.insert (nodeId).second;
  m_infrastructureRoutes[nodeId] = inFaceId;
  m_infrastructureRoles[nodeId] = role;
  if (!isNew)
    return;

  NS_LOG_INFO ("Router " << m_thisNode->GetId () << " 发现 " << role << " " << nodeId
                          << "，出接口faceId=" << inFaceId);
  for (uint64_t faceId : m_p2pFaceIds)
    {
      if (faceId != inFaceId)
        PushIdentityData (faceId, nodeId, role, data.getName ());
    }
}

void
VndnRouter::OnP2pHandshakeInterest (const ndn::Interest &interest)
{
  auto incomingFace = interest.getTag<ndn::lp::IncomingFaceIdTag> ();
  const ndn::Name &name = interest.getName ();
  if (incomingFace != nullptr && name.size () >= 6)
    {
      uint32_t requesterId = static_cast<uint32_t> (name.get (4).toNumber ());
      if (requesterId != m_thisNode->GetId ())
        {
          bool isNew = m_seenInfrastructureNodes.insert (requesterId).second;
          m_infrastructureRoutes[requesterId] = *incomingFace;
          m_infrastructureRoles[requesterId] = name.get (3).toUri ();
          if (isNew)
            NS_LOG_INFO ("Router " << m_thisNode->GetId () << " 发现 "
                                    << m_infrastructureRoles[requesterId] << " " << requesterId
                                    << "，出接口faceId=" << *incomingFace);
        }
    }

  std::ostringstream payload;
  payload << "router " << m_thisNode->GetId () << '\n';
  for (const auto &entry : m_infrastructureRoutes)
    payload << m_infrastructureRoles[entry.first] << ' ' << entry.first << '\n';
  const std::string content = payload.str ();
  auto data = std::make_shared<ndn::Data> (interest.getName ());
  data->setContent (std::make_shared<ndn::Buffer> (content.begin (), content.end ()));
  ndn::Signature signature;
  ndn::SignatureInfo signatureInfo (static_cast<ndn::tlv::SignatureTypeValue> (255));
  signature.setInfo (signatureInfo);
  signature.setValue (ndn::makeNonNegativeIntegerBlock (ndn::tlv::SignatureValue, 0));
  data->setSignature (signature);
  data->wireEncode ();
  m_face.put (*data);
}

void
VndnRouter::OnP2pHandshakeData (uint64_t outFaceId, const ndn::Interest &,
                                const ndn::Data &data)
{
  const auto &content = data.getContent ();
  std::istringstream parser (std::string (reinterpret_cast<const char *> (content.value ()),
                                         content.value_size ()));
  std::string role;
  uint32_t nodeId;
  while (parser >> role >> nodeId)
    {
      if (nodeId == m_thisNode->GetId ())
        continue;
      bool isNew = m_seenInfrastructureNodes.insert (nodeId).second;
      m_infrastructureRoutes[nodeId] = outFaceId;
      m_infrastructureRoles[nodeId] = role;
      if (isNew)
        NS_LOG_INFO ("Router " << m_thisNode->GetId () << " 发现 " << role << " " << nodeId
                                << "，出接口faceId=" << outFaceId);
    }
}

void
VndnRouter::OnP2pHandshakeNack (const ndn::Interest &interest, const ndn::lp::Nack &nack)
{
  NS_LOG_DEBUG ("Router 握手Nack: " << interest.getName () << " reason=" << nack.getReason ());
}

void
VndnRouter::OnP2pHandshakeTimeout (const ndn::Interest &interest)
{
  NS_LOG_DEBUG ("Router 握手超时: " << interest.getName ());
}

void
VndnRouter::Start ()
{
  m_face.processEvents ();
  m_active = true;
  NS_LOG_INFO ("VNDN Router 启动");
  ResolveServerFace ();
  uint32_t delayMs = 500 + ((m_thisNode->GetId () * 17) % 50);
  m_p2pHandshakeEvent = ns3::Simulator::Schedule (
      ns3::MilliSeconds (delayMs), &VndnRouter::SendP2pHandshake, this);
}

void
VndnRouter::Stop ()
{
  NS_LOG_INFO ("VNDN Router 关闭");
  m_p2pHandshakeEvent.Cancel ();
  m_face.shutdown ();
  m_active = false;
}

void
VndnRouter::ProcessInterest (const ndn::Interest &interest)
{
  if (!m_active)
    {
      return;
    }

  static const ndn::Name handshakePrefix ("/vndn/control/p2p-handshake");
  if (handshakePrefix.isPrefixOf (interest.getName ()))
    {
      OnP2pHandshakeInterest (interest);
      return;
    }

  auto incomingFace = interest.getTag<ndn::lp::IncomingFaceIdTag> ();
  if (incomingFace == nullptr || *incomingFace == 0)
    {
      NS_LOG_DEBUG ("Router 忽略来自本节点上层的兴趣请求: " << interest.getName ());
      return;
    }

  NS_LOG_INFO ("Router 收到来自基站的兴趣请求: " << interest.getName ()
               << " incomingFaceId=" << *incomingFace);
  ForwardInterestToServer (interest, *incomingFace);
}

} // namespace vanet

namespace ns3 {
NS_OBJECT_ENSURE_REGISTERED (VndnRouterApp);
} // namespace ns3
