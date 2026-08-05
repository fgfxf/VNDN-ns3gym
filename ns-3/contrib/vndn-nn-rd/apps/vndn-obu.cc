/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-obu.cc
 * \brief 车载单元（OBU）应用核心逻辑实现（重构版）。
 *
 * 本文件实现 VndnObu 类的通信框架，仅保留 NDN 应用的基本收发骨架，
 * 原有业务逻辑暂不移植。
 */

#include "vndn-obu.h"
#include "ns3/vndn-obu-app.h"
#include "ns3/node-list.h"
#include "ns3/ndnSIM/helper/ndn-stack-helper.hpp"
#include "ns3/ndnSIM/model/ndn-l3-protocol.hpp"
#include "ns3/ndnSIM/NFD/daemon/fw/forwarder.hpp"
#include "ns3/ndnSIM/NFD/daemon/table/cs.hpp"
#include "ns3/assert.h"
#include "ns3/random-variable-stream.h"
#include <ndn-cxx/lp/tags.hpp>
#include "../model/vndn-tag.hpp"

#include <iostream>
#include <cstdlib>
#include <map>

NS_LOG_COMPONENT_DEFINE ("ndn.VndnObu");

namespace vanet {

VndnObu::VndnObu (ns3::Ptr<ns3::TraciClient> &traci)
    : m_scheduler (m_face.getIoService ())
    , m_traci (traci)
{
  // 在 face 上注册根前缀，所有收到的兴趣包都交给 ProcessInterest 处理
  m_face.setInterestFilter ("/", std::bind (&VndnObu::ProcessInterest, this, _2),
                            [this] (const ndn::Name &, const std::string &reason) {
                              throw std::runtime_error (
                                  "Failed to register sync interest prefix: " + reason);
                            });
  // 获取当前节点指针
  m_thisNode = ns3::NodeList::GetNode (ns3::Simulator::GetContext ());
  RegisterFacePrefixs ();
}

// 遍历节点上的 NetDevice，区分无线接口并记录 faceId
void
VndnObu::RegisterFacePrefixs ()
{
  ns3::Ptr<ns3::ndn::L3Protocol> ndnL3 = m_thisNode->GetObject<ns3::ndn::L3Protocol> ();
  NS_ASSERT_MSG (ndnL3 != nullptr, "Ndn stack should be installed on the node");

  for (uint32_t deviceId = 0; deviceId < m_thisNode->GetNDevices (); deviceId++)
    {
      ns3::Ptr<ns3::NetDevice> device = m_thisNode->GetDevice (deviceId);
      auto face = ndnL3->getFaceByNetDevice (device);
      NS_ASSERT_MSG (face != nullptr, "There is no face associated with the net-device");

      if (!device->IsPointToPoint ())
        {
          // 无线接口：仅记录无线设备与 faceId，不在无线 face 上注册任何前缀。
          // std::shared_ptr<ndn::Name> name = std::make_shared<ndn::Name> ("/");
          // ns3::ndn::FibHelper::AddRoute (m_thisNode, *name, face, 1);
          // 车辆收到兴趣包后若本地无法满足，则不对外转发（避免多跳洪泛）。
          // 应用层通过 setInterestFilter("/", ...) 已在 app face 上注册前缀，
          // 可正常接收并处理收到的兴趣包。
          // 接收信号强度由底层 wifi-phy 通过 RxPowerDbmTag 附加到包上，
          // 经 NetDeviceTransport 写入 VndnTag，OBU 直接从 VndnTag 读取。
          m_wirelessDevice = device;
          m_wirelessFaceId = face->getId ();
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
VndnObu::ProcessInterest (const ndn::Interest &interest)
{
  if (!m_active)
    return;

  uint64_t inFaceId = ExtractIncomingFace (interest);
  if (!inFaceId)
    {
      // inFaceId == 0 表示来自本节点上层 或提取失败
      NS_LOG_DEBUG ("来自本节点上层的兴趣包");
      return;
    }

  // 统一交给 OnInterest 框架处理，后续按前缀细分
  OnInterest (interest);
}

// 提取兴趣包中的 IncomingFaceId 标签
uint64_t
VndnObu::ExtractIncomingFace (const ndn::Interest &interest)
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
VndnObu::OnInterest (const ndn::Interest &interest)
{
  // 按前缀分发到具体处理函数
  static const ndn::Name syncSignalPrefix ("/vndn/control/hello");
  if (syncSignalPrefix.isPrefixOf (interest.getName ()))
    {
      OnSyncSignalInterest (interest);
      return;
    }

  NS_LOG_DEBUG ("OBU 收到兴趣包: " << interest.getName ());
}

void
VndnObu::OnSyncSignalInterest (const ndn::Interest &interest)
{
  if (!m_active)
    return;

  // 从兴趣包中提取 VndnTag，获取 RSU 传入的车联网元信息
  auto vndnTag = interest.getTag<vanet::lp::VndnTag> ();
  if (vndnTag == nullptr)
    {
      NS_LOG_DEBUG ("OBU 收到同步信号但无 VndnTag: " << interest.getName ());
      return;
    }

  // 从 VndnTag 读取发送者节点 ID 与接收信号功率
  int64_t senderNodeId = static_cast<int64_t> (vndnTag->getSenderNodeId ());
  double rxPowerDbm = vndnTag->getRxPowerDbm ();

  // 当前仿真时间（毫秒）
  ns3::Time currentTime (ns3::Simulator::Now ());
  uint64_t currentTimeMs = currentTime.ToInteger (ns3::Time::MS);

  /////////////////////////// 更新邻居基站列表
  auto it = m_neighborBs.find (senderNodeId);
  if (it == m_neighborBs.end ())
    {
      // 新发现的邻居基站
      auto info = std::make_shared<ObuNeighborBsInfo> ();
      info->rxPowerDbm = rxPowerDbm;
      info->lastUpdateMs = currentTimeMs;
      info->senderMac = vndnTag->getSenderMac ();
      m_neighborBs.emplace (senderNodeId, info);
    }
  else
    {
      // 更新已有邻居基站的信号强度与时间戳
      it->second->rxPowerDbm = rxPowerDbm;
      it->second->lastUpdateMs = currentTimeMs;
      it->second->senderMac = vndnTag->getSenderMac ();
    }

  /////////////////////////// 删除过期的邻居基站
  for (auto iter = m_neighborBs.begin (); iter != m_neighborBs.end (); )
    {
      if ((currentTimeMs - iter->second->lastUpdateMs) > m_bsTimeoutMs)
        {
          // 过期基站恰好是当前驻留基站，则清除驻留
          if (iter->first == m_currentBsNodeId)
            {
              m_currentBsNodeId = -1;
              m_currentBsRxPowerDbm = -999.0;
            }
          iter = m_neighborBs.erase (iter);
        }
      else
        {
          ++iter;
        }
    }

  NS_LOG_DEBUG ("OBU 收到同步信号: " << interest.getName ()
                << " 来自RSU节点ID=" << senderNodeId
                << " 信号强度=" << rxPowerDbm << "dBm"
                << " 当前驻留基站=" << m_currentBsNodeId
                << " 邻居数=" << m_neighborBs.size ());

  /////////////////////////// 基站驻留切换决策
  if (senderNodeId == m_currentBsNodeId)
    {
      // 驻留基站更新信号强度与时间戳
      m_currentBsRxPowerDbm = rxPowerDbm;
    }
  else
    {
      // 非驻留基站，判断是否需要切换
      bool shouldHandover = false;
      if (m_currentBsNodeId == -1)
        {
          // 尚未驻留任何基站，直接驻留
          shouldHandover = true;
        }
      else if (rxPowerDbm > m_currentBsRxPowerDbm)
        {
          // 新基站信号强于当前驻留基站
          if (m_handoverStrategy == HandoverStrategy_Immediate)
            {
              // 立即切换策略
              shouldHandover = true;
            }
          else
            {
              // 防止 ping-pong 切换策略：
              // 新基站信号强于当前驻留基站，且距离上次驻留切换时间大于阈值
              if ((currentTimeMs - m_lastHandoverMs) > m_handoverGuardMs)
                {
                  shouldHandover = true;
                }
            }
        }

      if (shouldHandover)
        {
          NS_LOG_DEBUG ("OBU 基站切换: " << m_currentBsNodeId << " -> " << senderNodeId
                        << " 信号 " << m_currentBsRxPowerDbm << " -> " << rxPowerDbm << "dBm");
          m_currentBsNodeId = senderNodeId;
          m_currentBsRxPowerDbm = rxPowerDbm;
          m_lastHandoverMs = currentTimeMs;
        }
      else
        {
          // 不切换，不响应非驻留基站的同步信号
          return;
        }
    }

  /////////////////////////// 驻留基站：响应 hello 兴趣包（回传车辆信息 Data）
  std::shared_ptr<ndn::Data> data = std::make_shared<ndn::Data> (interest.getName ());

  // 通过 TraCI 获取车辆交通信息，封装为 JSON
  nlohmann::json j = nlohmann::json::object ();
  std::string vehId = m_traci->GetVehicleId (m_thisNode);
  libsumo::TraCIPosition pos = m_traci->TraCIAPI::vehicle.getPosition3D (vehId);
  j["LocateX"] = pos.x;
  j["LocateY"] = pos.y;
  j["Speed"] = m_traci->TraCIAPI::vehicle.getSpeed (vehId);
  j["Acceleration"] = m_traci->TraCIAPI::vehicle.getAcceleration (vehId);
  j["Angle"] = m_traci->TraCIAPI::vehicle.getAngle (vehId);
  j["LaneIndex"] = m_traci->TraCIAPI::vehicle.getLaneIndex (vehId);

  // 除驻留基站外信号强度最大的基站（次优基站），没有则为当前基站
  double maxRxSignal = -999.0;
  int64_t nextRsu = m_currentBsNodeId;
  for (auto &nb : m_neighborBs)
    {
      if (nb.first == m_currentBsNodeId)
        continue;
      if (nb.second->rxPowerDbm > maxRxSignal)
        {
          maxRxSignal = nb.second->rxPowerDbm;
          nextRsu = nb.first;
        }
    }
  j["NextRsu"] = nextRsu;

  // 缓存响应策略：参与缓存响应时，上报 CS 缓存信息
  if (m_cacheStrategy == CacheStrategy_Participate)
    {
      std::set<std::string> currentCs = GetCsNames ();
      if (!m_registered)
        {
          // 首次注册：上报全量缓存列表
          j["CsList"] = std::vector<std::string> (currentCs.begin (), currentCs.end ());
          j["CsUpdate"] = false;
          m_registered = true;
        }
      else
        {
          // 非首次注册：仅上报缓存的增删信息
          std::vector<std::string> added, removed;
          for (const auto &n : currentCs)
            {
              if (m_lastCsNames.find (n) == m_lastCsNames.end ())
                added.push_back (n);
            }
          for (const auto &n : m_lastCsNames)
            {
              if (currentCs.find (n) == currentCs.end ())
                removed.push_back (n);
            }
          j["CsAdded"] = added;
          j["CsRemoved"] = removed;
          j["CsUpdate"] = true;
        }
      m_lastCsNames = currentCs;
    }

  std::string strContent = j.dump (4);
  data->setContent (reinterpret_cast<const uint8_t *> (strContent.c_str ()),
                    strContent.size ());
  // 封装车联网元信息标签：发送者节点 ID、MAC、目标 MAC（当前驻留基站 MAC）
  auto bsInfo = m_neighborBs.find (m_currentBsNodeId);
  uint64_t targetMac = 0;
  if (bsInfo != m_neighborBs.end ())
    {
      targetMac = bsInfo->second->senderMac;
    }
  auto dataVndnTag = std::make_shared<vanet::lp::VndnTag> (m_thisNode->GetId (),
                                                           m_wirelessMac,
                                                           targetMac);
  data->setTag (dataVndnTag);
  // 设置签名（使用占位签名，避免签名验证失败）
  ndn::Signature signature;
  ndn::SignatureInfo signatureInfo (static_cast<::ndn::tlv::SignatureTypeValue> (255));
  signature.setInfo (signatureInfo);
  signature.setValue (::ndn::makeNonNegativeIntegerBlock (::ndn::tlv::SignatureValue, 0));
  data->setSignature (signature);
  data->wireEncode ();
  m_face.put (*data);

  NS_LOG_DEBUG ("OBU 响应驻留基站同步信号: " << interest.getName ()
                << " 基站ID=" << m_currentBsNodeId);

  // // 打印本节点 ContentStore 中的条目
  // ns3::Ptr<ns3::ndn::L3Protocol> ndnL3 = m_thisNode->GetObject<ns3::ndn::L3Protocol> ();
  // if (ndnL3 != nullptr)
  //   {
  //     auto forwarder = ndnL3->getForwarder ();
  //     if (forwarder != nullptr)
  //       {
  //         nfd::cs::Cs &cs = forwarder->getCs ();
  //         NS_LOG_DEBUG ("OBU ContentStore 条目数=" << cs.size ());
  //         for (auto it = cs.begin (); it != cs.end (); ++it)
  //           {
  //             NS_LOG_DEBUG ("  CS entry: " << it->getName ());
  //           }
  //       }
  //   }
}

void
VndnObu::OnData (const ndn::Interest &interest, const ndn::Data &data)
{
  // 收到数据包后不做额外处理，仅记录日志
  NS_LOG_DEBUG ("OBU 收到数据包: " << data.getName ());
}

void
VndnObu::OnTimeout (const ndn::Interest &interest)
{
  // 兴趣包超时后不做额外处理，仅记录日志
  NS_LOG_DEBUG ("OBU 兴趣包超时: " << interest.getName ());
}

void
VndnObu::OnNack (const ndn::Interest &interest, const ndn::lp::Nack &nack)
{
  // 收到 NACK 后不做额外处理，仅记录日志
  NS_LOG_DEBUG ("OBU 收到 NACK, reason: " << nack.getReason ());
}

////////////////////////////////////////////////////////////////////////
// 周期性请求发送（模拟用户高频访问）
////////////////////////////////////////////////////////////////////////

void
VndnObu::ScheduleNextPacket ()
{
  if (!m_active)
    return;
  // 根据频率计算发送间隔（微秒），并加入少量随机抖动以避免同步风暴
  ns3::Time reqTime = ns3::MicroSeconds (1000000 / m_frequency + rand () % 20000);
  m_requestScheduler = ns3::Simulator::Schedule (reqTime, &VndnObu::SendPacket, this);
}

void
VndnObu::SendPacket ()
{
  m_requestScheduler.Cancel ();
  if (!m_active)
    return;

  // 构造兴趣包：前缀 /com/baidu + 递增序号，模拟用户请求不同内容
  m_seq++;
  std::string userWatch = "/com/baidu/www/userid/" + std::to_string (m_thisNode->GetId ());
  std::shared_ptr<ndn::Name> name = std::make_shared<ndn::Name> (userWatch);
  name->appendSequenceNumber (m_seq);

  std::shared_ptr<ndn::Interest> interest = std::make_shared<ndn::Interest> ();
  interest->setName (*name);
  interest->setInterestLifetime (ndn::time::milliseconds (3000));
  interest->setCanBePrefix (true);
  interest->setMustBeFresh (false);
  interest->setTag (std::make_shared<ndn::lp::NextHopFaceIdTag> (m_wirelessFaceId));
  // 封装车联网元信息标签：发送者节点 ID、MAC、目标广播 MAC
  auto vndnTag = std::make_shared<vanet::lp::VndnTag> (m_thisNode->GetId (),
                                                       m_wirelessMac,
                                                       m_broadcastMac);
  NS_LOG_INFO ("OBU 发送兴趣包: " << *name);
  m_face.expressInterest (*interest,
                          std::bind (&VndnObu::OnData, this, _1, _2),
                          std::bind (&VndnObu::OnNack, this, _1, _2),
                          std::bind (&VndnObu::OnTimeout, this, _1));

  // 调度下一次发送，形成持续的高频请求
  ScheduleNextPacket ();
}

void
VndnObu::Start ()
{
  m_face.processEvents ();
  m_active = true;
  NS_LOG_DEBUG ("OBU 启动...");
  // 启动周期性请求发送
  ScheduleNextPacket ();
}

void
VndnObu::Stop ()
{
  NS_LOG_DEBUG ("OBU 关闭...");
  m_requestScheduler.Cancel ();
  m_face.shutdown ();
  m_active = false;
}

void
VndnObu::setHandoverStrategy (HandoverStrategy strategy)
{
  m_handoverStrategy = strategy;
}

void
VndnObu::setCacheStrategy (CacheStrategy strategy)
{
  m_cacheStrategy = strategy;
}

std::set<std::string>
VndnObu::GetCsNames ()
{
  std::set<std::string> names;
  ns3::Ptr<ns3::ndn::L3Protocol> ndnL3 = m_thisNode->GetObject<ns3::ndn::L3Protocol> ();
  if (ndnL3 == nullptr)
    return names;
  auto forwarder = ndnL3->getForwarder ();
  if (forwarder == nullptr)
    return names;
  nfd::cs::Cs &cs = forwarder->getCs ();
  for (auto it = cs.begin (); it != cs.end (); ++it)
    {
      std::string name = it->getName ().toUri ();
      // 排除 /localhost 开头的缓存条目
      if (name.rfind ("/localhost", 0) == 0)
        continue;
      names.insert (name);
    }
  return names;
}

} // namespace vanet

namespace ns3 {
NS_OBJECT_ENSURE_REGISTERED (VndnObuApp);
} // namespace ns3
