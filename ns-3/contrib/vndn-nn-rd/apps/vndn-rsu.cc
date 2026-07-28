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
  // TODO: 后续在此实现收到数据包后的处理逻辑
  NS_LOG_DEBUG ("RSU 收到数据包: " << data.getName ());
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

  // 构造 /vndn/control/hello 兴趣包，作为基站同步信号广播给附近车辆
  std::shared_ptr<ndn::Name> name = std::make_shared<ndn::Name> ("/vndn/control/hello");
  std::shared_ptr<ndn::Interest> interest = std::make_shared<ndn::Interest> ();
  interest->setName (*name);
  interest->setCanBePrefix (false);
  interest->setInterestLifetime (ndn::time::milliseconds (300));
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
  m_sendSyncSignal =
      m_scheduler.schedule (ndn::time::seconds (1), [this] { SendSyncSignal (); });
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
