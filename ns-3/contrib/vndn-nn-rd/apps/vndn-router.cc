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
#include "../model/vndn-tag.hpp"

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
  std::set<uint64_t> requestedReturnFaces;
  std::vector<uint32_t> requestedReturnRsuIds;
  auto routeTag = interest.getTag<vanet::lp::VndnTag> ();
  NS_LOG_DEBUG ("Router 解析回程标签: present=" << (routeTag != nullptr)
                << " primary="
                << (routeTag != nullptr ? routeTag->getReturnRsuPrimary () : -1)
                << " secondary="
                << (routeTag != nullptr ? routeTag->getReturnRsuSecondary () : -1));
  if (routeTag != nullptr && routeTag->getReturnRsuPrimary () >= 0)
    {
      const int64_t requestedIds[] = {routeTag->getReturnRsuPrimary (),
                                      routeTag->getReturnRsuSecondary ()};
      for (int64_t requestedId : requestedIds)
        {
          if (requestedId < 0)
            continue;
          auto route = m_infrastructureRoutes.find (
              static_cast<uint32_t> (requestedId));
          auto role = m_infrastructureRoles.find (
              static_cast<uint32_t> (requestedId));
          if (route != m_infrastructureRoutes.end () &&
              role != m_infrastructureRoles.end () && role->second == "rsu")
            {
              requestedReturnFaces.insert (route->second);
              requestedReturnRsuIds.push_back (
                  static_cast<uint32_t> (requestedId));
            }
          else
            {
              NS_LOG_WARN ("Router 找不到神经网络选择的回程 RSU " << requestedId);
            }
        }
    }

  // 默认路由可能比应用代理的同名 Interest 更早到达。若配套控制指令已
  // 到达，则以神经网络结果覆盖普通反向接口。
  auto instruction = m_neuralRouteInstructions.find (interest.getName ());
  if (instruction != m_neuralRouteInstructions.end ())
    {
      PendingRequest instructedRequest;
      if (ApplyNeuralReturnRoute (instructedRequest, instruction->second))
        {
          requestedReturnFaces = instructedRequest.returnFaceIds;
          requestedReturnRsuIds = instructedRequest.requestedReturnRsuIds;
        }
      m_neuralRouteInstructions.erase (instruction);
    }
  if (requestedReturnFaces.empty ())
    requestedReturnFaces.insert (returnFaceId);

  auto pending = m_pendingRequests.find (interest.getName ());
  if (pending != m_pendingRequests.end ())
    {
      if (!requestedReturnRsuIds.empty ())
        {
          // 同名 Interest 可能先按默认反向路径到达、随后才收到神经网络
          // 指令。此处以最新决策覆盖旧接口，并立即为新目标预备 PIT。
          pending->second.returnFaceIds = requestedReturnFaces;
          pending->second.requestedReturnRsuIds = requestedReturnRsuIds;
          PrepareNeuralReturnPits (pending->second);
        }
      else
        pending->second.returnFaceIds.insert (requestedReturnFaces.begin (),
                                              requestedReturnFaces.end ());
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
  request.returnFaceIds = requestedReturnFaces;
  request.requestedReturnRsuIds = requestedReturnRsuIds;
  // 建 PIT 控制报文必须尽早发送，不能等服务器 Data 返回时才发送，否则
  // 控制报文投递到 RSU 应用的回调可能晚于业务 Data，形成微秒级竞态。
  PrepareNeuralReturnPits (request);
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
  // 回程选择只在 Router 本地生效，无需继续发送到内容服务器。
  // IncomingFaceId 也属于上一跳接收信息；保留它会让 Router app 把自己
  // 新发出的服务器 Interest 再次误判成来自 RSU 的请求。
  serverInterest.removeTag<ndn::lp::IncomingFaceIdTag> ();
  serverInterest.removeTag<vanet::lp::VndnTag> ();
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
  const std::vector<uint32_t> requestedReturnRsuIds =
      pending->second.requestedReturnRsuIds;
  const std::shared_ptr<const ndn::Interest> originalInterest =
      pending->second.originalInterest;
  auto routeTag =
      originalInterest->getTag<vanet::lp::VndnTag> ();
  const bool isNeuralReturn =
      !requestedReturnRsuIds.empty ();
  m_pendingRequests.erase (pending);

  if (isNeuralReturn && routeTag != nullptr)
    {
      // 每个目标 RSU 都已通过 /vndn/control/neural-pit 建好无线 PIT。
      // 双路径时这里发送两份同名 Data，它们分别进入两个 RSU 的 P2P face。
      for (uint32_t targetRsuId : requestedReturnRsuIds)
        {
          auto route = m_infrastructureRoutes.find (targetRsuId);
          if (route == m_infrastructureRoutes.end ())
            {
              NS_LOG_WARN ("Router 找不到神经网络回程 RSU " << targetRsuId);
              continue;
            }

          const uint64_t faceId = route->second;
          auto response = std::make_shared<ndn::Data> (data);
          // sender 字段表示本次发送该无线帧的 RSU；targetMac 始终是 OBU，
          // NetDeviceTransport 会据此执行无线单播，而不是广播给所有车辆。
          auto responseRouteTag = std::make_shared<vanet::lp::VndnTag> (
              targetRsuId, 0, routeTag->getSenderMac ());
          responseRouteTag->setReturnRsuPrimary (requestedReturnRsuIds.front ());
          if (requestedReturnRsuIds.size () > 1)
            responseRouteTag->setReturnRsuSecondary (requestedReturnRsuIds[1]);
          response->setTag (responseRouteTag);
          response->setTag (std::make_shared<ndn::lp::NextHopFaceIdTag> (faceId));
          response->wireEncode ();
          try
            {
              m_face.put (*response);
              NS_LOG_INFO ("Router 按神经网络 PIT 回传服务器数据: "
                           << data.getName () << " targetRsu=" << targetRsuId
                           << " returnFaceId=" << faceId);
            }
          catch (const ndn::Face::OversizedPacketError &e)
            {
              NS_LOG_ERROR ("Router 无法回传超大Data: " << e.what ());
            }
        }
      return;
    }

  for (uint64_t faceId : returnFaces)
    {
      auto response = std::make_shared<ndn::Data> (data);
      if (routeTag != nullptr && isNeuralReturn)
        {
          auto responseRouteTag = std::make_shared<vanet::lp::VndnTag> (
              routeTag->getSenderNodeId (), routeTag->getSenderMac (), 0);
          responseRouteTag->setReturnRsuPrimary (requestedReturnRsuIds.front ());
          if (requestedReturnRsuIds.size () > 1)
            responseRouteTag->setReturnRsuSecondary (requestedReturnRsuIds[1]);
          response->setTag (responseRouteTag);
        }
      response->setTag (std::make_shared<ndn::lp::NextHopFaceIdTag> (faceId));
      response->wireEncode ();
      try
        {
          m_face.put (*response);
          NS_LOG_INFO ("Router 回传服务器数据: " << data.getName ()
                       << " returnFaceId=" << faceId
                       << " 神经网络回程=" << isNeuralReturn);
        }
      catch (const ndn::Face::OversizedPacketError &e)
        {
          NS_LOG_ERROR ("Router 无法回传超大Data: " << e.what ());
        }
    }
}

void
VndnRouter::PrepareNeuralReturnPits (PendingRequest &request)
{
  // 暂存指令早于 Interest 到达时，PendingRequest 可能还没有原始 Interest，
  // 因而先返回；待 Interest 到达并合并后会再次调用本函数。
  if (request.originalInterest == nullptr)
    return;
  auto routeTag =
      request.originalInterest->getTag<vanet::lp::VndnTag> ();
  if (routeTag == nullptr)
    return;

  for (uint32_t targetRsuId : request.requestedReturnRsuIds)
    {
      // 神经网络指令和带回程标签的代理 Interest 可能先后到达 Router。
      // 使用集合保证同一目标每个请求最多发送一次预备控制报文。
      if (request.preparedReturnRsuIds.count (targetRsuId) != 0)
        continue;
      auto route = m_infrastructureRoutes.find (targetRsuId);
      if (route == m_infrastructureRoutes.end ())
        continue;
      SendNeuralPitPrepare (targetRsuId, route->second,
                            routeTag->getSenderNodeId (),
                            routeTag->getSenderMac (),
                            *request.originalInterest);
      request.preparedReturnRsuIds.insert (targetRsuId);
    }
}

void
VndnRouter::SendNeuralPitPrepare (uint32_t targetRsuId, uint64_t targetFaceId,
                                  uint32_t obuNodeId, uint64_t obuMac,
                                  const ndn::Interest &originalInterest)
{
  // 名称字段依次为：目标 RSU、目标 OBU、OBU MAC、Router 本地流水号。
  // 目标 ID 便于 RSU 过滤误投控制报文，流水号避免控制 Data 重名。
  ndn::Name name ("/vndn/control/neural-pit");
  name.appendNumber (targetRsuId)
      .appendNumber (obuNodeId)
      .appendNumber (obuMac)
      .appendNumber (++m_neuralPitSequence);

  auto prepare = std::make_shared<ndn::Data> (name);
  // Content 保存原始 Interest 的完整 wire encoding。目标 RSU 解码后即可
  // 用相同 Name/Selectors 创建能匹配服务器 Data 的 PIT 条目。
  const ndn::Block &wire = originalInterest.wireEncode ();
  prepare->setContent (wire.wire (), wire.size ());
  prepare->setTag (
      std::make_shared<ndn::lp::NextHopFaceIdTag> (targetFaceId));
  ndn::Signature signature;
  ndn::SignatureInfo signatureInfo (
      static_cast<ndn::tlv::SignatureTypeValue> (255));
  signature.setInfo (signatureInfo);
  signature.setValue (
      ndn::makeNonNegativeIntegerBlock (ndn::tlv::SignatureValue, 0));
  prepare->setSignature (signature);
  prepare->wireEncode ();
  m_face.put (*prepare);
  NS_LOG_INFO ("Router 通知 RSU " << targetRsuId
                                   << " 创建神经网络回程 PIT: "
                                   << originalInterest.getName ()
                                   << " outFaceId=" << targetFaceId);
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
  static const ndn::Name neuralRoutePrefix ("/vndn/control/neural-route");
  if (neuralRoutePrefix.isPrefixOf (data.getName ()))
    {
      OnNeuralRouteInstruction (data);
      return;
    }

  static const ndn::Name relayPrefix ("/vndn/control/rsu-relay");
  if (relayPrefix.isPrefixOf (data.getName ()))
    {
      RelayRsuControlData (data);
      return;
    }

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

bool
VndnRouter::ApplyNeuralReturnRoute (
    PendingRequest &request, const std::vector<uint32_t> &returnRsuIds)
{
  std::set<uint64_t> returnFaces;
  std::vector<uint32_t> resolvedRsuIds;
  for (uint32_t rsuId : returnRsuIds)
    {
      auto route = m_infrastructureRoutes.find (rsuId);
      auto role = m_infrastructureRoles.find (rsuId);
      if (route == m_infrastructureRoutes.end () ||
          role == m_infrastructureRoles.end () || role->second != "rsu")
        {
          NS_LOG_WARN ("Router 找不到神经网络选择的回程 RSU " << rsuId);
          continue;
        }
      if (returnFaces.insert (route->second).second)
        resolvedRsuIds.push_back (rsuId);
    }
  if (returnFaces.empty ())
    return false;

  request.returnFaceIds = std::move (returnFaces);
  request.requestedReturnRsuIds = std::move (resolvedRsuIds);
  return true;
}

void
VndnRouter::OnNeuralRouteInstruction (const ndn::Data &data)
{
  const ndn::Block &content = data.getContent ();
  std::istringstream parser (
      std::string (reinterpret_cast<const char *> (content.value ()),
                   content.value_size ()));
  std::string interestUri;
  if (!(parser >> interestUri))
    return;

  std::vector<uint32_t> returnRsuIds;
  uint32_t rsuId = 0;
  while (parser >> rsuId)
    returnRsuIds.push_back (rsuId);
  if (returnRsuIds.empty ())
    return;

  ndn::Name interestName (interestUri);
  auto pending = m_pendingRequests.find (interestName);
  if (pending != m_pendingRequests.end ())
    {
      if (ApplyNeuralReturnRoute (pending->second, returnRsuIds))
        {
          PrepareNeuralReturnPits (pending->second);
          NS_LOG_INFO ("Router 覆盖请求回程路由: " << interestName
                       << " 目标RSU数="
                       << pending->second.requestedReturnRsuIds.size ());
        }
      return;
    }

  m_neuralRouteInstructions[interestName] = returnRsuIds;
  NS_LOG_DEBUG ("Router 暂存先到达的神经网络回程指令: " << interestName);
}

void
VndnRouter::RelayRsuControlData (const ndn::Data &data)
{
  const ndn::Name &name = data.getName ();
  if (name.size () < 8)
    return;

  const uint32_t targetRsuId = static_cast<uint32_t> (name.get (4).toNumber ());
  auto route = m_infrastructureRoutes.find (targetRsuId);
  if (route == m_infrastructureRoutes.end () ||
      m_infrastructureRoles[targetRsuId] != "rsu")
    {
      NS_LOG_WARN ("Router 找不到目标 RSU " << targetRsuId
                   << "，丢弃控制 Data " << name);
      return;
    }

  auto incomingFace = data.getTag<ndn::lp::IncomingFaceIdTag> ();
  if (incomingFace != nullptr && *incomingFace == route->second)
    {
      NS_LOG_WARN ("Router 拒绝将控制 Data 发回入接口: " << name);
      return;
    }

  auto forwarded = std::make_shared<ndn::Data> (data);
  forwarded->setTag (
      std::make_shared<ndn::lp::NextHopFaceIdTag> (route->second));
  forwarded->wireEncode ();
  m_face.put (*forwarded);
  NS_LOG_INFO ("Router 中继 RSU 控制 Data: " << name
               << " targetRsu=" << targetRsuId
               << " outFaceId=" << route->second);
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
