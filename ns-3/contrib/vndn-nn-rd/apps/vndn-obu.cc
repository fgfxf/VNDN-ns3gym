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
#include "ns3/assert.h"
#include "ns3/random-variable-stream.h"
#include <ndn-cxx/lp/tags.hpp>

#include <iostream>
#include <cstdlib>

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

// 遍历节点上的 NetDevice，区分无线接口并注册前缀
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
          // 无线接口：注册根前缀，记录无线设备与 faceId
          std::shared_ptr<ndn::Name> name = std::make_shared<ndn::Name> ("/");
          ns3::ndn::FibHelper::AddRoute (m_thisNode, *name, face, 1);
          m_wirelessDevice = device;
          m_wirelessFaceId = face->getId ();
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
      // inFaceId == 0 表示来自本节点上层
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
  // TODO: 后续在此实现收到兴趣包后的具体响应逻辑
  NS_LOG_DEBUG ("OBU 收到兴趣包: " << interest.getName ());
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
  std::shared_ptr<ndn::Name> name = std::make_shared<ndn::Name> ("/com/baidu");
  name->appendSequenceNumber (m_seq);

  std::shared_ptr<ndn::Interest> interest = std::make_shared<ndn::Interest> ();
  interest->setName (*name);
  interest->setInterestLifetime (ndn::time::milliseconds (3000));
  interest->setCanBePrefix (false);
  interest->setMustBeFresh (false);

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

} // namespace vanet

namespace ns3 {
NS_OBJECT_ENSURE_REGISTERED (VndnObuApp);
} // namespace ns3
