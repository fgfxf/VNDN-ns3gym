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
#include "ns3/assert.h"
#include <ndn-cxx/lp/tags.hpp>
#include "../model/vndn-tag.hpp"

#include <iostream>

NS_LOG_COMPONENT_DEFINE ("ndn.VndnRsu");

namespace vanet {

VndnRsu::VndnRsu (ns3::Ptr<ns3::TraciClient> &traci)
    : m_scheduler (m_face.getIoService ())
    , m_traci (traci)
{
  // 在 face 上注册根前缀，所有收到的兴趣包都交给 ProcessInterest 处理
  m_face.setInterestFilter ("/", std::bind (&VndnRsu::ProcessInterest, this, _2),
                            [this] (const ndn::Name &, const std::string &reason) {
                              throw std::runtime_error (
                                  "Failed to register sync interest prefix: " + reason);
                            });
  // 获取当前节点指针
  m_thisNode = ns3::NodeList::GetNode (ns3::Simulator::GetContext ());
  RegisterFacePrefixs ();
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
  // TODO: 后续在此实现收到兴趣包后的具体响应逻辑
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
    }

  // 更新车辆最后回复时间戳
  ns3::Time currentTime (ns3::Simulator::Now ());
  uint64_t currentTimeMs = currentTime.ToInteger (ns3::Time::MS);
  m_vehicleLastReplyMs[obuNodeId] = currentTimeMs;

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
  // TODO: 后续在此实现兴趣包超时后的处理逻辑
  NS_LOG_DEBUG ("RSU 兴趣包超时: " << interest.getName ());
}

void
VndnRsu::OnNack (const ndn::Interest &interest, const ndn::lp::Nack &nack)
{
  // TODO: 后续在此实现收到 NACK 后的处理逻辑
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

  NS_LOG_INFO ("RSU 发送同步信号: " << *name);
  m_face.expressInterest (*interest,
                          std::bind (&VndnRsu::OnData, this, _1, _2),
                          std::bind (&VndnRsu::OnNack, this, _1, _2),
                          std::bind (&VndnRsu::OnTimeout, this, _1));

  // 每 20ms 发送一次同步信号
  m_sendSyncSignal = m_scheduler.schedule (ndn::time::milliseconds (20), [this] { SendSyncSignal (); });
}

void
VndnRsu::Start ()
{
  m_face.processEvents ();
  m_active = true;
  NS_LOG_DEBUG ("RSU 启动...");
  // 启动周期性同步信号广播
  m_sendSyncSignal =
      m_scheduler.schedule (ndn::time::milliseconds (20), [this] { SendSyncSignal (); });
}

void
VndnRsu::Stop ()
{
  NS_LOG_DEBUG ("RSU 关闭...");
  m_sendSyncSignal.cancel ();
  m_face.shutdown ();
  m_active = false;
}

} // namespace vanet

namespace ns3 {
NS_OBJECT_ENSURE_REGISTERED (VndnRsuApp);
} // namespace ns3
