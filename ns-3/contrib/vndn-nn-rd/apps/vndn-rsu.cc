/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-rsu.cc
 * \brief 路边单元（RSU）应用核心逻辑实现（重构版）。
 *
 * 本文件实现 VndnRsu 类的通信框架，仅保留 NDN 应用的基本收发骨架，
 * 原有业务逻辑暂不移植。
 */

#include "vndn-rsu.h"
#include "ns3/vndn-rsu-app.h"

#include "ns3/ndnSIM/helper/ndn-stack-helper.hpp"
#include "ns3/ndnSIM/model/ndn-l3-protocol.hpp"
#include "ns3/ndnSIM/NFD/daemon/fw/forwarder.hpp"
#include "ns3/ndnSIM/NFD/daemon/table/pit.hpp"
#include "ns3/assert.h"
#include "ns3/mobility-model.h"
// SUMO TraCI uses global TYPE_* macros that collide with protobuf enums pulled
// in by ns3-gym. VndnRsu does not use these TraCI type-code macros directly.
#undef TYPE_POLYGON
#undef TYPE_UBYTE
#undef TYPE_BYTE
#undef TYPE_INTEGER
#undef TYPE_DOUBLE
#undef TYPE_STRING
#undef TYPE_STRINGLIST
#undef TYPE_COMPOUND
#undef TYPE_COLOR
#include "ns3/opengym-module.h"
#include "ns3/simulator.h"
#include "ns3/vndn-rsu-forwarding-policy.h"
#include <ndn-cxx/lp/tags.hpp>
#include <ndn-cxx/encoding/block-helpers.hpp>
#include "../model/vndn-tag.hpp"

#include <iostream>
#include <algorithm>
#include <functional>
#include <limits>
#include <sstream>
#include <tuple>

NS_LOG_COMPONENT_DEFINE ("ndn.VndnRsu");

namespace vanet {

ns3::Ptr<ns3::OpenGymInterface> VndnRsu::s_openGym = nullptr;
VndnRsu *VndnRsu::s_openGymOwner = nullptr;
std::queue<VndnRsu::NeuralRouteJob> VndnRsu::s_neuralRouteJobs;
uint32_t VndnRsu::s_openGymUserCount = 0;

VndnRsu::VndnRsu (ns3::Ptr<ns3::TraciClient> &traci)
    : m_scheduler (m_face.getIoService ())
    , m_traci (traci)
{
  m_syncSignalIntervalMs = 20;
  m_vehicleTimeoutMs = 2 * m_syncSignalIntervalMs;

  // 在 face 上注册根前缀，所有收到的兴趣包都交给 ProcessInterest 处理
  m_face.setInterestFilter ("/", std::bind (&VndnRsu::ProcessInterest, this, _2),
                            [this] (const ndn::Name &, const std::string &reason) {
                              throw std::runtime_error (
                                  "Failed to register sync interest prefix: " + reason);
                            });
  // 获取当前节点指针
  m_thisNode = ns3::NodeList::GetNode (ns3::Simulator::GetContext ());
  RegisterFacePrefixs ();
  m_face.setDataUnsolicitedProcess (
      std::bind (&VndnRsu::OnP2pHandshakeDataPush, this, _1, _2));
}

// 遍历节点上的 NetDevice，区分 p2p 与无线接口并注册前缀
void
VndnRsu::RegisterFacePrefixs ()
{
  ns3::Ptr<ns3::ndn::L3Protocol> ndnL3 = m_thisNode->GetObject<ns3::ndn::L3Protocol> ();
  NS_ASSERT_MSG (ndnL3 != nullptr, "Ndn stack should be installed on the node");

  for (uint32_t deviceId = 0; deviceId < m_thisNode->GetNDevices (); deviceId++)
    {
      ns3::Ptr<ns3::NetDevice> device = m_thisNode->GetDevice (deviceId);
      auto face = ndnL3->getFaceByNetDevice (device);
      NS_ASSERT_MSG (face != nullptr, "There is no face associated with the net-device");

      if (device->IsPointToPoint ())
        {
          // p2p 接口：注册控制前缀，用于后续基站间通信
          std::shared_ptr<ndn::Name> name = std::make_shared<ndn::Name> ("/vndn/control");
          ns3::ndn::FibHelper::AddRoute (m_thisNode, *name, face, 1);
          m_p2pFaceIds.push_back (face->getId ());
        }
      else
        {
          // 无线接口：注册同步信号前缀，记录无线设备与 faceId
          std::shared_ptr<ndn::Name> name = std::make_shared<ndn::Name> ("/vndn/control/hello");
          ns3::ndn::FibHelper::AddRoute (m_thisNode, *name, face, 1);
          m_wirelessDevice = device;
          m_wirelessFaceId = face->getId ();
          // 提取本节点无线 MAC 与广播 MAC（uint64 形式），供同步信号广播使用
          m_wirelessAddress = device->GetAddress ();
          m_wirelessAddress.CopyAllTo ((uint8_t *) &m_wirelessMac,
                                       sizeof (uint64_t) / sizeof (uint8_t));
          m_wirelessDevice->GetBroadcast ().CopyAllTo ((uint8_t *) &m_broadcastMac,
                                                       sizeof (uint64_t) / sizeof (uint8_t));
        }
    }
}

// 兴趣包分发入口
void
VndnRsu::ProcessInterest (const ndn::Interest &interest)
{
  if (!m_active)
    return;

  uint64_t inFaceId = ExtractIncomingFace (interest);
  if (!inFaceId)
    {
      // inFaceId == 0 表示来自本节点上层
      NS_LOG_DEBUG ("来自本节点上层的兴趣包");
      return;
    }

  // 统一交给 OnInterest 框架处理，后续按前缀细分
  OnInterest (interest);
}

// 提取兴趣包中的 IncomingFaceId 标签
uint64_t
VndnRsu::ExtractIncomingFace (const ndn::Interest &interest)
{
  std::shared_ptr<ndn::lp::IncomingFaceIdTag> inFaceIdTag =
      interest.getTag<ndn::lp::IncomingFaceIdTag> ();
  if (!inFaceIdTag)
    {
      return 0;
    }
  return *inFaceIdTag;
}

////////////////////////////////////////////////////////////////////////
// NDN 通信回调框架（仅保留骨架，业务逻辑待补充）
////////////////////////////////////////////////////////////////////////

void
VndnRsu::OnInterest (const ndn::Interest &interest)
{
  static const ndn::Name handshakePrefix ("/vndn/control/p2p-handshake");
  if (handshakePrefix.isPrefixOf (interest.getName ()))
    {
      OnP2pHandshakeInterest (interest);
      return;
    }

  // RSU app 代理发出的同名 Interest 可能再次匹配本应用的根前缀。
  // pending 表中已存在该名称时，说明它已经被代理，不得再次代理。
  if (m_pendingVehicleRequests.count (interest.getName ()) != 0)
    {
      NS_LOG_DEBUG ("RSU 忽略已代理的 Interest: " << interest.getName ());
      return;
    }

  // 默认策略不改变 NDN 原生的 Interest/Data 反向路径。
  if (m_forwardStrategy == RsuForwardStrategy_NoForward)
    {
      NS_LOG_DEBUG ("RSU 收到兴趣包: " << interest.getName ());
      return;
    }

  auto incomingFace = interest.getTag<ndn::lp::IncomingFaceIdTag> ();
  auto vndnTag = interest.getTag<vanet::lp::VndnTag> ();
  if (incomingFace == nullptr || *incomingFace != m_wirelessFaceId || vndnTag == nullptr)
    {
      NS_LOG_DEBUG ("RSU 忽略非车辆无线 Interest: " << interest.getName ());
      return;
    }

  if (m_forwardStrategy == RsuForwardStrategy_NeuralNetwork)
    RequestNeuralRoute (interest, vndnTag->getSenderNodeId (), vndnTag->getSenderMac ());
  else
    ForwardVehicleInterest (interest, vndnTag->getSenderNodeId (), vndnTag->getSenderMac ());
  NS_LOG_DEBUG ("RSU 收到兴趣包: " << interest.getName ());
}

void
VndnRsu::OnData (const ndn::Interest &interest, const ndn::Data &data)
{
  // 按前缀分发：同步信号响应走单独处理函数
  static const ndn::Name syncPrefix ("/vndn/control/hello");
  if (syncPrefix.isPrefixOf (data.getName ()))
    {
      OnSyncSignalData (interest, data);
      return;
    }

  NS_LOG_DEBUG ("RSU 收到数据包: " << data.getName ());
}

void
VndnRsu::OnSyncSignalData (const ndn::Interest &interest, const ndn::Data &data)
{
  // 解析 OBU 上报的车辆信息（JSON）
  const auto &content = data.getContent ();
  std::string jsonStr (reinterpret_cast<const char *> (content.value ()),
                       content.value_size ());
  nlohmann::json j;
  try
    {
      j = nlohmann::json::parse (jsonStr);
    }
  catch (const std::exception &e)
    {
      NS_LOG_DEBUG ("RSU 收到同步信号响应，但 JSON 解析失败: " << e.what ());
      return;
    }

  // 从 VndnTag 读取发送者节点 ID
  int64_t obuNodeId = -1;
  auto vndnTag = data.getTag<vanet::lp::VndnTag> ();
  if (vndnTag != nullptr)
    {
      obuNodeId = static_cast<int64_t> (vndnTag->getSenderNodeId ());
      m_vehicleMac[obuNodeId] = vndnTag->getSenderMac ();
    }

  if (obuNodeId < 0)
    return;

  // 更新车辆最后回复时间戳
  ns3::Time currentTime (ns3::Simulator::Now ());
  uint64_t currentTimeMs = currentTime.ToInteger (ns3::Time::MS);
  m_vehicleLastReplyMs[obuNodeId] = currentTimeMs;
  m_vehicleNextRsu[obuNodeId] =
      j.value ("NextRsu", static_cast<int64_t> (m_thisNode->GetId ()));
  m_resolvedVehicleRsu.erase (static_cast<uint32_t> (obuNodeId));

  // 保存与 training-tag CSV 六个输入列完全一致的 hello 时间序列。
  // Keep the exact six-feature order used during TKAN-LSTM training.
  std::array<double, 6> observation = {
      j.value ("LocateX", 0.0), j.value ("LocateY", 0.0),
      j.value ("Speed", 0.0), j.value ("Acceleration", 0.0),
      j.value ("Angle", 0.0), static_cast<double> (j.value ("LaneIndex", 0))};
  auto &history = m_vehicleObservationHistory[obuNodeId];
  history.push_back (observation);
  while (history.size () > m_neuralSequenceLength)
    history.pop_front ();

  // 补救 Data 可能比车辆在新 RSU 的首次 hello 注册更早到达。
  // 注册完成后立即刷新这些暂存 Data，避免交接竞态造成丢包。
  auto waitingRelay = m_relayDataWaitingForVehicle.find (
      static_cast<uint32_t> (obuNodeId));
  if (waitingRelay != m_relayDataWaitingForVehicle.end ())
    {
      for (const auto &packet : waitingRelay->second)
        SendDataToVehicle (*packet, static_cast<uint32_t> (obuNodeId), 0);
      m_relayDataWaitingForVehicle.erase (waitingRelay);
    }

  NS_LOG_DEBUG ("RSU 收到车辆信息: OBU=" << obuNodeId
                << " X=" << j.value ("LocateX", 0.0)
                << " Y=" << j.value ("LocateY", 0.0)
                << " Speed=" << j.value ("Speed", 0.0)
                << " Acc=" << j.value ("Acceleration", 0.0)
                << " Angle=" << j.value ("Angle", 0.0)
                << " Lane=" << j.value ("LaneIndex", 0)
                << " NextRsu=" << j.value ("NextRsu", -1));

  // 处理缓存映射
  if (j.contains ("CsUpdate"))
    {
      bool isUpdate = j["CsUpdate"].get<bool> ();
      if (!isUpdate)
        {
          // 首次注册：全量缓存列表
          std::set<std::string> csNames;
          if (j.contains ("CsList"))
            {
              for (const auto &name : j["CsList"])
                {
                  csNames.insert (name.get<std::string> ());
                }
            }
          // 先清除该车辆旧的映射（切换基站后重新注册）
          auto &oldCs = m_vehicleToCs[obuNodeId];
          for (const auto &name : oldCs)
            {
              m_csToVehicles[name].erase (obuNodeId);
              if (m_csToVehicles[name].empty ())
                m_csToVehicles.erase (name);
            }
          // 建立新映射
          m_vehicleToCs[obuNodeId] = csNames;
          for (const auto &name : csNames)
            {
              m_csToVehicles[name].insert (obuNodeId);
            }
          NS_LOG_DEBUG ("RSU 车辆注册: OBU=" << obuNodeId
                        << " 缓存数=" << csNames.size ());
        }
      else
        {
          // 非首次注册：增量更新
          if (j.contains ("CsAdded"))
            {
              for (const auto &name : j["CsAdded"])
                {
                  std::string s = name.get<std::string> ();
                  m_vehicleToCs[obuNodeId].insert (s);
                  m_csToVehicles[s].insert (obuNodeId);
                }
            }
          if (j.contains ("CsRemoved"))
            {
              for (const auto &name : j["CsRemoved"])
                {
                  std::string s = name.get<std::string> ();
                  m_vehicleToCs[obuNodeId].erase (s);
                  m_csToVehicles[s].erase (obuNodeId);
                  if (m_csToVehicles[s].empty ())
                    m_csToVehicles.erase (s);
                }
            }
          NS_LOG_DEBUG ("RSU 车辆缓存更新: OBU=" << obuNodeId
                        << " 当前缓存数=" << m_vehicleToCs[obuNodeId].size ());
        }
    }
}

void
VndnRsu::OnTimeout (const ndn::Interest &interest)
{
  m_pendingVehicleRequests.erase (interest.getName ());
  NS_LOG_DEBUG ("RSU 兴趣包超时: " << interest.getName ());
}

void
VndnRsu::OnNack (const ndn::Interest &interest, const ndn::lp::Nack &nack)
{
  m_pendingVehicleRequests.erase (interest.getName ());
  NS_LOG_DEBUG ("RSU 收到 NACK, reason: " << nack.getReason ());
}

////////////////////////////////////////////////////////////////////////
// 周期性同步信号广播（类似 5G Synchronization Signal）
////////////////////////////////////////////////////////////////////////

void
VndnRsu::SendSyncSignal ()
{
  m_sendSyncSignal.cancel ();

  // 清理超时未回复的车辆（已离开本基站覆盖范围）
  ns3::Time currentTime (ns3::Simulator::Now ());
  uint64_t currentTimeMs = currentTime.ToInteger (ns3::Time::MS);
  for (auto it = m_vehicleLastReplyMs.begin (); it != m_vehicleLastReplyMs.end (); )
    {
      if ((currentTimeMs - it->second) > m_vehicleTimeoutMs)
        {
          int64_t obuNodeId = it->first;
          // 从车辆->缓存映射中删除，并同步更新缓存->车辆映射
          auto csIt = m_vehicleToCs.find (obuNodeId);
          if (csIt != m_vehicleToCs.end ())
            {
              for (const auto &name : csIt->second)
                {
                  m_csToVehicles[name].erase (obuNodeId);
                  if (m_csToVehicles[name].empty ())
                    m_csToVehicles.erase (name);
                }
              m_vehicleToCs.erase (csIt);
            }
          NS_LOG_DEBUG ("RSU 车辆超时离开: OBU=" << obuNodeId);
          it = m_vehicleLastReplyMs.erase (it);
          if (m_forwardStrategy == RsuForwardStrategy_VTDF)
            QueryVehicleLocation (static_cast<uint32_t> (obuNodeId));
        }
      else
        {
          ++it;
        }
    }

  // 构造 /vndn/control/hello 兴趣包，作为基站同步信号广播给附近车辆
  std::shared_ptr<ndn::Name> name = std::make_shared<ndn::Name> ("/vndn/control/hello");
  std::shared_ptr<ndn::Interest> interest = std::make_shared<ndn::Interest> ();
  interest->setName (*name);
  interest->setCanBePrefix (false);
  // interest->setInterestLifetime (ndn::time::milliseconds (1));// 无需生存时间，因为我们让/vndn/contorl 长期存在
  // beacon 包不会超时、不删除 PIT、不缓存、不命中
  // （底层 forwarder.cpp / strategy.cpp 已对 /vndn/control 前缀实现此逻辑）
  interest->setMustBeFresh (false);
  // 指定从无线 face 发出
  interest->setTag (std::make_shared<ndn::lp::NextHopFaceIdTag> (m_wirelessFaceId));
  // 封装车联网元信息标签：发送者节点 ID、MAC、目标广播 MAC
  auto vndnTag = std::make_shared<vanet::lp::VndnTag> (m_thisNode->GetId (),
                                                       m_wirelessMac,
                                                       m_broadcastMac);
  interest->setTag (vndnTag);

  // NS_LOG_INFO ("RSU 发送同步信号: " << *name);
  m_face.expressInterest (*interest,
                          std::bind (&VndnRsu::OnData, this, _1, _2),
                          std::bind (&VndnRsu::OnNack, this, _1, _2),
                          std::bind (&VndnRsu::OnTimeout, this, _1));

  // 按设定间隔发送同步信号
  m_sendSyncSignal = m_scheduler.schedule (
      ndn::time::milliseconds (m_syncSignalIntervalMs), [this] { SendSyncSignal (); });
}

void
VndnRsu::SendP2pHandshake ()
{
  if (!m_active)
    return;

  const uint32_t nodeId = m_thisNode->GetId ();
  m_seenInfrastructureNodes.insert (nodeId);

  ndn::Name name ("/vndn/control/p2p-handshake/rsu");
  name.appendNumber (nodeId).appendNumber (m_p2pHandshakeRound);
  for (uint64_t faceId : m_p2pFaceIds)
    PushIdentityData (faceId, nodeId, "rsu", name);
  NS_LOG_INFO ("RSU " << nodeId << " 发送第 " << m_p2pHandshakeRound
                       << " 轮P2P身份握手");
  ++m_p2pHandshakeRound;
  if (m_p2pHandshakeRound < 3)
    m_p2pHandshakeEvent = ns3::Simulator::Schedule (
        ns3::MilliSeconds (200), &VndnRsu::SendP2pHandshake, this);
}

void
VndnRsu::PushIdentityData (uint64_t faceId, uint32_t nodeId,
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
VndnRsu::OnP2pHandshakeDataPush (const ndn::Interest &, const ndn::Data &data)
{
  // /vndn/control 是无 PIT 也会由 NFD 持久投递给本地应用的协议空间。
  // neural-pit 必须优先分发，避免落入普通握手或 RSU 中继处理分支。
  static const ndn::Name neuralPitPrefix ("/vndn/control/neural-pit");
  if (neuralPitPrefix.isPrefixOf (data.getName ()))
    {
      OnNeuralPitPrepareData (data);
      return;
    }

  static const ndn::Name servicePrefix ("/com/baidu");
  if (servicePrefix.isPrefixOf (data.getName ()))
    {
      OnNeuralReturnData (data);
      return;
    }

  static const ndn::Name relayPrefix ("/vndn/control/rsu-relay");
  if (relayPrefix.isPrefixOf (data.getName ()))
    {
      OnRsuRelayData (data);
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

  NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 发现 " << role << " " << nodeId
                       << "，出接口faceId=" << inFaceId);
  for (uint64_t faceId : m_p2pFaceIds)
    {
      if (faceId != inFaceId)
        PushIdentityData (faceId, nodeId, role, data.getName ());
    }
}

void
VndnRsu::OnNeuralPitPrepareData (const ndn::Data &data)
{
  const ndn::Name &controlName = data.getName ();
  // /vndn/control/neural-pit/<target-rsu>/<obu>/<obu-mac>/<sequence>
  if (controlName.size () < 7)
    return;

  const uint32_t targetRsuId =
      static_cast<uint32_t> (controlName.get (3).toNumber ());
  const uint32_t obuNodeId =
      static_cast<uint32_t> (controlName.get (4).toNumber ());
  // Router 通过指定 face 正常只会送到一个目标；仍校验 ID，使协议在拓扑
  // 或转发规则配置错误时不会在错误 RSU 上创建无效 PIT。
  if (targetRsuId != m_thisNode->GetId ())
    return;

  const ndn::Block &content = data.getContent ();
  auto parsed = ndn::Block::fromBuffer (content.value (), content.value_size ());
  if (!std::get<0> (parsed))
    {
      NS_LOG_WARN ("RSU " << m_thisNode->GetId ()
                            << " 无法解析神经网络 PIT 预备报文");
      return;
    }

  auto originalInterest =
      std::make_shared<ndn::Interest> (std::get<1> (parsed));
  // 只允许为业务前缀代建 PIT，控制报文不能借此任意修改其他命名空间。
  static const ndn::Name servicePrefix ("/com/baidu");
  if (!servicePrefix.isPrefixOf (originalInterest->getName ()))
    {
      NS_LOG_WARN ("RSU " << m_thisNode->GetId ()
                            << " 拒绝为非业务前缀创建神经网络 PIT: "
                            << originalInterest->getName ());
      return;
    }

  auto ndnL3 = m_thisNode->GetObject<ns3::ndn::L3Protocol> ();
  auto &forwarder = *ndnL3->getForwarder ();
  // PIT 的下游必须是无线 face，而不是收到控制报文的 P2P face。这样原始
  // Data 从 Router 到达后才会由 NFD 继续转给车辆。
  auto *wirelessFace = ndnL3->getFaceTable ().get (m_wirelessFaceId);
  if (wirelessFace == nullptr)
    {
      NS_LOG_WARN ("RSU " << m_thisNode->GetId ()
                            << " 找不到无线 face，无法创建神经网络回程 PIT");
      return;
    }

  auto inserted = forwarder.getPit ().insert (*originalInterest);
  auto pitEntry = inserted.first;
  if (pitEntry == nullptr)
    return;

  // 与旧版实现相同：恢复/补充无线 in-record。服务器 Data 从 Router 到达
  // 后，NFD 会沿 PIT 自动发到无线 face，VndnTag 中的目标 MAC 保证单播。
  pitEntry->insertOrUpdateInRecord (*wirelessFace, *originalInterest);
  // 复用原始 InterestLifetime。超时后 NFD 自动清理预备 PIT，防止神经
  // 网络误判或服务器无响应时遗留永久表项。
  forwarder.setProtocolPitExpiryTimer (
      pitEntry, ndn::time::duration_cast<ndn::time::milliseconds> (
                    originalInterest->getInterestLifetime ()));
  NS_LOG_INFO ("RSU " << m_thisNode->GetId ()
                       << (inserted.second ? " 创建" : " 补充")
                       << "神经网络回程 PIT: " << originalInterest->getName ()
                       << " wirelessFaceId=" << m_wirelessFaceId
                       << " OBU=" << obuNodeId);
}

void
VndnRsu::OnP2pHandshakeInterest (const ndn::Interest &interest)
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
            NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 发现 "
                                 << m_infrastructureRoles[requesterId] << " " << requesterId
                                 << "，出接口faceId=" << *incomingFace);
        }
    }

  std::ostringstream payload;
  payload << "rsu " << m_thisNode->GetId () << '\n';
  for (const auto &entry : m_infrastructureRoutes)
    payload << m_infrastructureRoles[entry.first] << ' ' << entry.first << '\n';

  auto data = std::make_shared<ndn::Data> (interest.getName ());
  const std::string content = payload.str ();
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
VndnRsu::OnP2pHandshakeData (uint64_t outFaceId, const ndn::Interest &, const ndn::Data &data)
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
        NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 发现 " << role << " " << nodeId
                             << "，出接口faceId=" << outFaceId);
    }
}

void
VndnRsu::OnP2pHandshakeNack (const ndn::Interest &interest, const ndn::lp::Nack &nack)
{
  NS_LOG_DEBUG ("RSU 握手Nack: " << interest.getName () << " reason=" << nack.getReason ());
}

void
VndnRsu::OnP2pHandshakeTimeout (const ndn::Interest &interest)
{
  NS_LOG_DEBUG ("RSU 握手超时: " << interest.getName ());
}

void
VndnRsu::setRsuForwardStrategy (RsuForwardStrategy strategy)
{
  m_forwardStrategy = strategy;
}

void
VndnRsu::setOpenGymPort (uint16_t openGymPort)
{
  m_openGymPort = openGymPort;
}

uint64_t
VndnRsu::ResolveRouterFace () const
{
  for (const auto &entry : m_infrastructureRoles)
    {
      if (entry.second == "router")
        {
          auto route = m_infrastructureRoutes.find (entry.first);
          if (route != m_infrastructureRoutes.end ())
            return route->second;
        }
    }
  return m_p2pFaceIds.empty () ? 0 : m_p2pFaceIds.front ();
}

int64_t
VndnRsu::ResolveRealtimeTargetRsu (uint32_t obuNodeId) const
{
  if (m_traci != nullptr && obuNodeId < ns3::NodeList::GetNNodes ())
    {
      try
        {
          ns3::Ptr<ns3::Node> obuNode = ns3::NodeList::GetNode (obuNodeId);
          const std::string vehicleId = m_traci->GetVehicleId (obuNode);
          const libsumo::TraCIPosition position =
              m_traci->TraCIAPI::vehicle.getPosition3D (vehicleId);

          std::vector<std::pair<uint32_t, ns3::Vector>> rsuPositions;
          auto appendRsuPosition = [&rsuPositions] (uint32_t rsuNodeId) {
            if (rsuNodeId >= ns3::NodeList::GetNNodes ())
              return;
            auto mobility = ns3::NodeList::GetNode (rsuNodeId)
                                ->GetObject<ns3::MobilityModel> ();
            if (mobility != nullptr)
              rsuPositions.emplace_back (rsuNodeId, mobility->GetPosition ());
          };
          appendRsuPosition (m_thisNode->GetId ());
          for (const auto &entry : m_infrastructureRoles)
            {
              if (entry.second == "rsu" && entry.first != m_thisNode->GetId ())
                appendRsuPosition (entry.first);
            }

          const int64_t nearestRsu = VndnRsuForwardingPolicy::SelectNearestRsu (
              ns3::Vector (position.x, position.y, position.z), rsuPositions);
          if (nearestRsu >= 0)
            {
              NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " RealTimeVTDF 实时定位 OBU "
                                   << obuNodeId << " -> 最近 RSU " << nearestRsu);
              return nearestRsu;
            }
        }
      catch (const std::exception &e)
        {
          NS_LOG_WARN ("RSU " << m_thisNode->GetId () << " 无法获取 OBU " << obuNodeId
                               << " 的 TraCI 实时位置: " << e.what ());
        }
    }

  auto predicted = m_vehicleNextRsu.find (obuNodeId);
  return predicted == m_vehicleNextRsu.end () ? -1 : predicted->second;
}

void
VndnRsu::ForwardVehicleInterest (const ndn::Interest &interest, uint32_t obuNodeId,
                                 uint64_t obuMac,
                                 const std::vector<uint32_t> &returnRsuIds)
{
  const uint64_t routerFace = ResolveRouterFace ();
  if (routerFace == 0)
    {
      NS_LOG_WARN ("RSU " << m_thisNode->GetId ()
                           << " 找不到 Router 接口，无法代理 "
                           << interest.getName ());
      return;
    }

  PendingVehicleRequest request;
  request.obuNodeId = obuNodeId;
  request.obuMac = obuMac;
  m_pendingVehicleRequests[interest.getName ()] = request;

  // 移除原无线 Interest 建立的 PIT，回程 Data 先交由 RSU app 决策。
  auto ndnL3 = m_thisNode->GetObject<ns3::ndn::L3Protocol> ();
  auto &pit = ndnL3->getForwarder ()->getPit ();
  auto pitEntry = pit.find (interest);
  if (pitEntry != nullptr)
    {
      pitEntry->expiryTimer.cancel ();
      pit.erase (pitEntry.get ());
    }

  ndn::Interest upstream (interest);
  upstream.refreshNonce ();
  // IncomingFaceId 是接收原无线 Interest 时的本地标签，不能带入新的
  // 代理 Interest，否则再次投递给本应用时会被误认为无线入包。
  upstream.removeTag<ndn::lp::IncomingFaceIdTag> ();
  upstream.removeTag<vanet::lp::VndnTag> ();
  if (!returnRsuIds.empty ())
    {
      // 该 LP 标签随 Interest 到达 Router；Router 据此替换 Data 回程接口。
      // OBU ID/MAC 同时随标签送达目标 RSU，供其完成最后一跳单播。
      auto routeTag = std::make_shared<vanet::lp::VndnTag> (obuNodeId, obuMac, 0);
      routeTag->setReturnRsuPrimary (returnRsuIds.front ());
      if (returnRsuIds.size () > 1)
        routeTag->setReturnRsuSecondary (returnRsuIds[1]);
      upstream.setTag (routeTag);
      NS_LOG_DEBUG ("RSU 写入神经网络回程标签: primary="
                    << routeTag->getReturnRsuPrimary () << " secondary="
                    << routeTag->getReturnRsuSecondary ());
      // 同名 Interest 可能已被 NFD 的默认路由先行转发并被 PIT 聚合，因此
      // 再发送一条控制 Data，确保 Router 能在服务器 Data 返回前覆盖回程接口。
      SendNeuralRouteInstruction (interest.getName (), returnRsuIds);
    }
  upstream.setTag (std::make_shared<ndn::lp::NextHopFaceIdTag> (routerFace));
  m_face.expressInterest (
      upstream, std::bind (&VndnRsu::OnVehicleData, this, _1, _2),
      std::bind (&VndnRsu::OnNack, this, _1, _2),
      std::bind (&VndnRsu::OnTimeout, this, _1));
  NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 代理 OBU " << obuNodeId
                       << " 的 Interest: " << interest.getName ()
                       << " 神经网络回程RSU数=" << returnRsuIds.size ());
}

void
VndnRsu::OnVehicleData (const ndn::Interest &interest, const ndn::Data &data)
{
  auto pending = m_pendingVehicleRequests.find (interest.getName ());
  if (pending == m_pendingVehicleRequests.end ())
    return;

  const PendingVehicleRequest request = pending->second;
  m_pendingVehicleRequests.erase (pending);
  if (m_forwardStrategy == RsuForwardStrategy_NeuralNetwork)
    {
      // Router 的 /vndn/control/neural-pit 预备报文已经在选中 RSU 的
      // 无线 face 上恢复了 PIT。NFD 会自动转发当前 Data；应用层不得再次
      // put，否则源 RSU 会绕过神经网络选择并产生重复无线 Data。
      NS_LOG_DEBUG ("RSU " << m_thisNode->GetId ()
                            << " 神经网络回程 Data 由 PIT 自动转发: "
                            << data.getName ());
      return;
    }
  if (m_vehicleLastReplyMs.count (request.obuNodeId) != 0)
    {
      SendDataToVehicle (data, request.obuNodeId, request.obuMac);
      return;
    }

  if (m_forwardStrategy == RsuForwardStrategy_VTDF)
    {
      auto resolved = m_resolvedVehicleRsu.find (request.obuNodeId);
      if (resolved != m_resolvedVehicleRsu.end ())
        {
          ForwardDataToRsu (resolved->second, request.obuNodeId, data);
        }
      else
        {
          m_waitingForwardData[request.obuNodeId].push_back (
              std::make_shared<ndn::Data> (data));
          QueryVehicleLocation (request.obuNodeId);
        }
      return;
    }

  if (m_forwardStrategy == RsuForwardStrategy_RealTimeVtdf)
    {
      const int64_t targetRsuId = ResolveRealtimeTargetRsu (request.obuNodeId);
      if (targetRsuId == static_cast<int64_t> (m_thisNode->GetId ()))
        {
          // hello 丢失导致误超时，但车辆实时位置仍最接近本 RSU。
          SendDataToVehicle (data, request.obuNodeId, request.obuMac);
        }
      else if (targetRsuId >= 0)
        {
          ForwardDataToRsu (static_cast<uint32_t> (targetRsuId),
                            request.obuNodeId, data);
        }
      else
        {
          NS_LOG_WARN ("RSU " << m_thisNode->GetId () << " 没有 OBU "
                               << request.obuNodeId << " 的有效 NextRsu，放弃补救 "
                               << data.getName ());
        }
    }
}

void
VndnRsu::SendDataToVehicle (const ndn::Data &data, uint32_t obuNodeId,
                            uint64_t fallbackMac)
{
  uint64_t targetMac = fallbackMac;
  auto mac = m_vehicleMac.find (obuNodeId);
  if (mac != m_vehicleMac.end ())
    targetMac = mac->second;
  if (targetMac == 0)
    {
      NS_LOG_WARN ("RSU " << m_thisNode->GetId () << " 缺少 OBU " << obuNodeId
                           << " 的 MAC，无法无线回传 " << data.getName ());
      return;
    }

  auto response = std::make_shared<ndn::Data> (data);
  response->setTag (std::make_shared<ndn::lp::NextHopFaceIdTag> (m_wirelessFaceId));
  response->setTag (std::make_shared<vanet::lp::VndnTag> (
      m_thisNode->GetId (), m_wirelessMac, targetMac));
  response->wireEncode ();
  m_face.put (*response);
  NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 向 OBU " << obuNodeId
                       << " 回传 Data: " << data.getName ());
}

void
VndnRsu::SendRelayData (const ndn::Name &name, const uint8_t *content,
                        size_t contentSize)
{
  const uint64_t routerFace = ResolveRouterFace ();
  if (routerFace == 0)
    return;
  auto relay = std::make_shared<ndn::Data> (name);
  relay->setContent (content, contentSize);
  relay->setTag (std::make_shared<ndn::lp::NextHopFaceIdTag> (routerFace));
  ndn::Signature signature;
  ndn::SignatureInfo signatureInfo (static_cast<ndn::tlv::SignatureTypeValue> (255));
  signature.setInfo (signatureInfo);
  signature.setValue (ndn::makeNonNegativeIntegerBlock (ndn::tlv::SignatureValue, 0));
  relay->setSignature (signature);
  relay->wireEncode ();
  m_face.put (*relay);
}

void
VndnRsu::SendNeuralRouteInstruction (
    const ndn::Name &interestName, const std::vector<uint32_t> &returnRsuIds)
{
  if (returnRsuIds.empty ())
    return;

  std::ostringstream payload;
  payload << interestName.toUri ();
  for (uint32_t rsuId : returnRsuIds)
    payload << ' ' << rsuId;
  const std::string content = payload.str ();

  ndn::Name name ("/vndn/control/neural-route");
  name.appendNumber (m_thisNode->GetId ())
      .appendNumber (++m_relaySequence);
  SendRelayData (name, reinterpret_cast<const uint8_t *> (content.data ()),
                 content.size ());
  NS_LOG_DEBUG ("RSU " << m_thisNode->GetId ()
                        << " 向 Router 发送神经网络回程指令: "
                        << interestName << " 目标数=" << returnRsuIds.size ());
}

void
VndnRsu::QueryVehicleLocation (uint32_t obuNodeId)
{
  m_resolvedVehicleRsu.erase (obuNodeId);
  for (const auto &entry : m_infrastructureRoles)
    {
      if (entry.second != "rsu" || entry.first == m_thisNode->GetId ())
        continue;
      ndn::Name name ("/vndn/control/rsu-relay/find");
      name.appendNumber (entry.first)
          .appendNumber (m_thisNode->GetId ())
          .appendNumber (obuNodeId)
          .appendNumber (++m_relaySequence);
      SendRelayData (name, nullptr, 0);
      NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 经 Router 询问 RSU "
                           << entry.first << ": OBU " << obuNodeId << " 是否驻留");
    }
}

void
VndnRsu::ForwardDataToRsu (uint32_t targetRsuId, uint32_t obuNodeId,
                           const ndn::Data &data)
{
  ndn::Name name ("/vndn/control/rsu-relay/forward");
  name.appendNumber (targetRsuId)
      .appendNumber (m_thisNode->GetId ())
      .appendNumber (obuNodeId)
      .appendNumber (++m_relaySequence);
  const ndn::Block &wire = data.wireEncode ();
  SendRelayData (name, wire.wire (), wire.size ());
  NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 经 Router 向 RSU " << targetRsuId
                       << " 补救 Data: " << data.getName () << " OBU=" << obuNodeId);
}

void
VndnRsu::OnRsuRelayData (const ndn::Data &data)
{
  const ndn::Name &name = data.getName ();
  if (name.size () < 8)
    return;
  const std::string action = name.get (3).toUri ();
  const uint32_t targetRsuId = static_cast<uint32_t> (name.get (4).toNumber ());
  const uint32_t sourceRsuId = static_cast<uint32_t> (name.get (5).toNumber ());
  const uint32_t obuNodeId = static_cast<uint32_t> (name.get (6).toNumber ());
  if (targetRsuId != m_thisNode->GetId ())
    return;

  if (action == "find")
    {
      if (m_vehicleLastReplyMs.count (obuNodeId) == 0)
        return;
      ndn::Name reply ("/vndn/control/rsu-relay/found");
      reply.appendNumber (sourceRsuId)
          .appendNumber (m_thisNode->GetId ())
          .appendNumber (obuNodeId)
          .appendNumber (++m_relaySequence);
      SendRelayData (reply, nullptr, 0);
      NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 回复：OBU " << obuNodeId
                           << " 当前在本基站");
      return;
    }

  if (action == "found")
    {
      m_resolvedVehicleRsu[obuNodeId] = sourceRsuId;
      auto waiting = m_waitingForwardData.find (obuNodeId);
      if (waiting != m_waitingForwardData.end ())
        {
          for (const auto &packet : waiting->second)
            ForwardDataToRsu (sourceRsuId, obuNodeId, *packet);
          m_waitingForwardData.erase (waiting);
        }
      return;
    }

  if (action == "forward")
    {
      const auto &content = data.getContent ();
      auto parsed = ndn::Block::fromBuffer (content.value (), content.value_size ());
      if (!std::get<0> (parsed))
        return;
      auto original = std::make_shared<ndn::Data> (std::get<1> (parsed));
      if (m_vehicleLastReplyMs.count (obuNodeId) == 0)
        {
          m_relayDataWaitingForVehicle[obuNodeId].push_back (original);
          NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 暂存 OBU " << obuNodeId
                               << " 尚未注册时到达的补救 Data: "
                               << original->getName ());
          return;
        }
      SendDataToVehicle (*original, obuNodeId, 0);
    }
}

void
VndnRsu::OnNeuralReturnData (const ndn::Data &data)
{
  auto routeTag = data.getTag<vanet::lp::VndnTag> ();
  if (routeTag == nullptr || routeTag->getReturnRsuPrimary () < 0)
    return;

  const uint32_t obuNodeId = routeTag->getSenderNodeId ();
  const uint64_t obuMac = routeTag->getSenderMac ();
  if (m_vehicleLastReplyMs.count (obuNodeId) == 0)
    {
      m_relayDataWaitingForVehicle[obuNodeId].push_back (
          std::make_shared<ndn::Data> (data));
      NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 暂存神经网络回程 Data: "
                           << data.getName () << " OBU=" << obuNodeId);
      return;
    }

  SendDataToVehicle (data, obuNodeId, obuMac);
  NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 执行神经网络回程: "
                       << data.getName () << " OBU=" << obuNodeId);
}

std::vector<uint32_t>
VndnRsu::GetNeuralCandidateRsuIds () const
{
  std::set<uint32_t> candidateSet;
  candidateSet.insert (m_thisNode->GetId ());
  for (const auto &entry : m_infrastructureRoles)
    {
      if (entry.second == "rsu")
        candidateSet.insert (entry.first);
    }
  return std::vector<uint32_t> (candidateSet.begin (), candidateSet.end ());
}

void
VndnRsu::InitializeOpenGym ()
{
  if (m_forwardStrategy != RsuForwardStrategy_NeuralNetwork ||
      m_openGymPort == 0 || m_openGymRegistered)
    return;

  m_openGymRegistered = true;
  ++s_openGymUserCount;
  if (s_openGym != nullptr)
    return;

  s_openGymOwner = this;
  s_openGym = ns3::CreateObject<ns3::OpenGymInterface> (m_openGymPort);
  s_openGym->SetGetObservationSpaceCb (
      ns3::MakeCallback (&VndnRsu::GetNeuralObservationSpace, this));
  s_openGym->SetGetActionSpaceCb (
      ns3::MakeCallback (&VndnRsu::GetNeuralActionSpace, this));
  s_openGym->SetGetGameOverCb (
      ns3::MakeCallback (&VndnRsu::GetNeuralGameOver, this));
  s_openGym->SetGetObservationCb (
      ns3::MakeCallback (&VndnRsu::GetNeuralObservation, this));
  s_openGym->SetGetRewardCb (
      ns3::MakeCallback (&VndnRsu::GetNeuralReward, this));
  s_openGym->SetGetExtraInfoCb (
      ns3::MakeCallback (&VndnRsu::GetNeuralExtraInfo, this));
  s_openGym->SetExecuteActionsCb (
      ns3::MakeCallback (&VndnRsu::ExecuteNeuralAction, this));
  NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 创建共享 ns3-gym 接口，端口="
                       << m_openGymPort);
}

void
VndnRsu::RequestNeuralRoute (const ndn::Interest &interest, uint32_t obuNodeId,
                             uint64_t obuMac)
{
  if (s_openGym == nullptr)
    {
      NS_LOG_WARN ("神经网络策略未配置有效 ns3-gym 端口，回程退化为当前 RSU "
                   << m_thisNode->GetId ());
      ForwardVehicleInterest (interest, obuNodeId, obuMac,
                              {m_thisNode->GetId ()});
      return;
    }

  NeuralRouteJob job;
  job.source = this;
  job.interest = std::make_shared<ndn::Interest> (interest);
  job.obuNodeId = obuNodeId;
  job.obuMac = obuMac;
  job.candidateRsuIds = GetNeuralCandidateRsuIds ();

  auto history = m_vehicleObservationHistory.find (obuNodeId);
  if (history != m_vehicleObservationHistory.end () && !history->second.empty ())
    {
      // 序列不足 10 步时用最早状态在左侧填充，最新状态始终位于末尾。
      // Left-pad a short history with its earliest state.
      while (job.observations.size () + history->second.size () <
             m_neuralSequenceLength)
        job.observations.push_back (history->second.front ());
      job.observations.insert (job.observations.end (), history->second.begin (),
                               history->second.end ());
    }
  else
    {
      job.observations.assign (m_neuralSequenceLength, std::array<double, 6> {});
    }

  if (job.candidateRsuIds.empty ())
    job.candidateRsuIds.push_back (m_thisNode->GetId ());
  s_neuralRouteJobs.push (std::move (job));
  s_openGym->NotifyCurrentState ();
}

ns3::Ptr<ns3::OpenGymSpace>
VndnRsu::GetNeuralObservationSpace ()
{
  NS_ASSERT_MSG (!s_neuralRouteJobs.empty (), "ns3-gym 初始化时应已有决策任务");
  const uint32_t candidateCount =
      static_cast<uint32_t> (s_neuralRouteJobs.front ().candidateRsuIds.size ());
  auto space = ns3::CreateObject<ns3::OpenGymDictSpace> ();
  space->Add ("features", ns3::CreateObject<ns3::OpenGymBoxSpace> (
                                -1000000.0f, 1000000.0f,
                                std::vector<uint32_t> {m_neuralSequenceLength, 6},
                                "double"));
  space->Add ("rsu_ids", ns3::CreateObject<ns3::OpenGymBoxSpace> (
                               0.0f, 1000000.0f,
                               std::vector<uint32_t> {candidateCount}, "uint32_t"));
  space->Add ("obu_id", ns3::CreateObject<ns3::OpenGymBoxSpace> (
                              0.0f, 1000000.0f,
                              std::vector<uint32_t> {1}, "uint32_t"));
  return space;
}

ns3::Ptr<ns3::OpenGymSpace>
VndnRsu::GetNeuralActionSpace ()
{
  NS_ASSERT_MSG (!s_neuralRouteJobs.empty (), "ns3-gym 初始化时应已有决策任务");
  const uint32_t candidateCount =
      static_cast<uint32_t> (s_neuralRouteJobs.front ().candidateRsuIds.size ());
  return ns3::CreateObject<ns3::OpenGymBoxSpace> (
      0.0f, 1.0f, std::vector<uint32_t> {candidateCount}, "float");
}

bool
VndnRsu::GetNeuralGameOver ()
{
  return false;
}

ns3::Ptr<ns3::OpenGymDataContainer>
VndnRsu::GetNeuralObservation ()
{
  // NotifySimulationEnd() 也会请求一次最终状态；此时可能没有待决策任务。
  if (s_neuralRouteJobs.empty ())
    return nullptr;
  const NeuralRouteJob &job = s_neuralRouteJobs.front ();
  auto observation = ns3::CreateObject<ns3::OpenGymDictContainer> ();

  auto features = ns3::CreateObject<ns3::OpenGymBoxContainer<double>> (
      std::vector<uint32_t> {m_neuralSequenceLength, 6});
  for (const auto &state : job.observations)
    for (double value : state)
      features->AddValue (value);
  observation->Add ("features", features);

  auto rsuIds = ns3::CreateObject<ns3::OpenGymBoxContainer<uint32_t>> (
      std::vector<uint32_t> {
          static_cast<uint32_t> (job.candidateRsuIds.size ())});
  for (uint32_t rsuId : job.candidateRsuIds)
    rsuIds->AddValue (rsuId);
  observation->Add ("rsu_ids", rsuIds);

  auto obuId = ns3::CreateObject<ns3::OpenGymBoxContainer<uint32_t>> (
      std::vector<uint32_t> {1});
  obuId->AddValue (job.obuNodeId);
  observation->Add ("obu_id", obuId);
  return observation;
}

float
VndnRsu::GetNeuralReward ()
{
  return 0.0f;
}

std::string
VndnRsu::GetNeuralExtraInfo ()
{
  if (s_neuralRouteJobs.empty ())
    return "no-pending-neural-job";
  std::ostringstream info;
  info << "sourceRsu=" << s_neuralRouteJobs.front ().source->m_thisNode->GetId ()
       << ",obu=" << s_neuralRouteJobs.front ().obuNodeId;
  return info.str ();
}

bool
VndnRsu::ExecuteNeuralAction (ns3::Ptr<ns3::OpenGymDataContainer> action)
{
  if (s_neuralRouteJobs.empty ())
    return false;

  NeuralRouteJob job = std::move (s_neuralRouteJobs.front ());
  s_neuralRouteJobs.pop ();
  auto probabilities =
      ns3::DynamicCast<ns3::OpenGymBoxContainer<float>> (action);
  if (probabilities == nullptr ||
      probabilities->GetData ().size () != job.candidateRsuIds.size ())
    {
      NS_LOG_WARN ("ns3-gym 返回的概率数量无效，退化为当前 RSU");
      job.source->ForwardVehicleInterest (*job.interest, job.obuNodeId, job.obuMac,
                                          {job.source->m_thisNode->GetId ()});
      return false;
    }

  const std::vector<float> values = probabilities->GetData ();
  // 双路径有两个触发条件：前两名十分接近，或第二名本身已有至少 0.10
  // 的可信度。后者让 0.78/0.22 这类切换期结果也能获得冗余回程。
  const std::vector<uint32_t> selectedRsuIds =
      VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
          job.candidateRsuIds, values,
          job.source->m_neuralDualPathProbabilityGap,
          job.source->m_neuralDualPathMinSecondProbability);

  std::vector<float> sortedValues = values;
  std::sort (sortedValues.begin (), sortedValues.end (), std::greater<float> ());

  std::ostringstream selected;
  for (uint32_t rsuId : selectedRsuIds)
    selected << rsuId << ' ';
  NS_LOG_INFO ("神经网络回程决策 OBU=" << job.obuNodeId
               << " top1=" << sortedValues.front ()
               << " top2=" << (sortedValues.size () > 1 ? sortedValues[1] : -1.0f)
               << " x=" << job.source->m_neuralDualPathProbabilityGap
               << " secondMin="
               << job.source->m_neuralDualPathMinSecondProbability
               << " 选择RSU=" << selected.str ());
  job.source->ForwardVehicleInterest (*job.interest, job.obuNodeId, job.obuMac,
                                      selectedRsuIds);
  return true;
}

void
VndnRsu::Start ()
{
  m_face.processEvents ();
  m_active = true;
  NS_LOG_DEBUG ("RSU 启动...");
  InitializeOpenGym ();
  // 启动周期性同步信号广播
  m_sendSyncSignal = m_scheduler.schedule (
      ndn::time::milliseconds (m_syncSignalIntervalMs), [this] { SendSyncSignal (); });
  // 将不同节点的公告分散在仿真启动后的 500~1000ms 内。
  uint32_t delayMs = 500 + ((m_thisNode->GetId () * 17) % 50);
  m_p2pHandshakeEvent = ns3::Simulator::Schedule (
      ns3::MilliSeconds (delayMs), &VndnRsu::SendP2pHandshake, this);
}

void
VndnRsu::Stop ()
{
  NS_LOG_INFO ("RSU " << m_thisNode->GetId () << " 关闭");
  m_sendSyncSignal.cancel ();
  m_p2pHandshakeEvent.Cancel ();
  if (m_openGymRegistered)
    {
      m_openGymRegistered = false;
      NS_ASSERT (s_openGymUserCount > 0);
      --s_openGymUserCount;
      // 第一个停止的 RSU 立即发送结束消息。若等待最后一个 RSU，最初注册
      // callbacks 的 owner 可能已经析构，Python 端也会一直阻塞在 step()。
      if (s_openGym != nullptr)
        {
          s_openGym->NotifySimulationEnd ();
          s_openGym = nullptr;
          s_openGymOwner = nullptr;
          while (!s_neuralRouteJobs.empty ())
            s_neuralRouteJobs.pop ();
        }
    }
  m_face.shutdown ();
  m_active = false;
}

} // namespace vanet

namespace ns3 {
NS_OBJECT_ENSURE_REGISTERED (VndnRsuApp);
} // namespace ns3
