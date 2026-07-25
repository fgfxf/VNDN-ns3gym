/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-rsu.cc
 * \brief 路边单元（RSU）应用核心逻辑实现（重构版）。
 *
 * 本文件实现 VndnRsu 类的通信框架，仅保留 NDN 应用的基本收发骨架，
 * 原有业务逻辑暂不移植。
 */

#include "vndn-rsu.h"

#include "ns3/ndnSIM/helper/ndn-stack-helper.hpp"
#include "ns3/ndnSIM/model/ndn-l3-protocol.hpp"
#include "ns3/assert.h"
#include <ndn-cxx/lp/tags.hpp>

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
          std::shared_ptr<ndn::Name> name = std::make_shared<ndn::Name> ("/control/p2pHandShark");
          ns3::ndn::FibHelper::AddRoute (m_thisNode, *name, face, 1);
        }
      else
        {
          // 无线接口：注册 hello 前缀，记录无线设备与 faceId
          std::shared_ptr<ndn::Name> name = std::make_shared<ndn::Name> ("/hello");
          ns3::ndn::FibHelper::AddRoute (m_thisNode, *name, face, 1);
          m_wirelessDevice = device;
          m_wirelessFaceId = face->getId ();
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

void
VndnRsu::Start ()
{
  m_face.processEvents ();
  m_active = true;
  NS_LOG_DEBUG ("RSU 启动...");
}

void
VndnRsu::Stop ()
{
  NS_LOG_DEBUG ("RSU 关闭...");
  m_face.shutdown ();
  m_active = false;
}

} // namespace vanet
