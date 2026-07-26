/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Copyright (c) 2011-2018  Regents of the University of California.
 *
 * This file is part of ndnSIM. See AUTHORS for complete list of ndnSIM authors and
 * contributors.
 *
 * ndnSIM is free software: you can redistribute it and/or modify it under the terms
 * of the GNU General Public License as published by the Free Software Foundation,
 * either version 3 of the License, or (at your option) any later version.
 *
 * ndnSIM is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
 * without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
 * PURPOSE.  See the GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along with
 * ndnSIM, e.g., in COPYING.md file.  If not, see <http://www.gnu.org/licenses/>.
 **/

#include "ndn-net-device-transport.hpp"

#include "../helper/ndn-stack-helper.hpp"
#include "ndn-block-header.hpp"
#include "../utils/ndn-ns3-packet-tag.hpp"

#include <ndn-cxx/encoding/block.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/data.hpp>
#include <ndn-cxx/lp/packet.hpp>
#include <ndn-cxx/lp/fields.hpp>

#include "ns3/queue.h"
#include "ns3/node-list.h"

NS_LOG_COMPONENT_DEFINE("ndn.NetDeviceTransport");

namespace ns3 {
namespace ndn {

NetDeviceTransport::NetDeviceTransport(Ptr<Node> node,
                                       const Ptr<NetDevice>& netDevice,
                                       const std::string& localUri,
                                       const std::string& remoteUri,
                                       ::ndn::nfd::FaceScope scope,
                                       ::ndn::nfd::FacePersistency persistency,
                                       ::ndn::nfd::LinkType linkType)
  : m_netDevice(netDevice)
  , m_node(node)
{
  this->setLocalUri(FaceUri(localUri));
  this->setRemoteUri(FaceUri(remoteUri));
  this->setScope(scope);
  this->setPersistency(persistency);
  this->setLinkType(linkType);
  this->setMtu(m_netDevice->GetMtu()); // Use the MTU of the netDevice

  // Get send queue capacity for congestion marking
  PointerValue txQueueAttribute;
  if (m_netDevice->GetAttributeFailSafe("TxQueue", txQueueAttribute)) {
    Ptr<ns3::QueueBase> txQueue = txQueueAttribute.Get<ns3::QueueBase>();
    // must be put into bytes mode queue

    auto size = txQueue->GetMaxSize();
    if (size.GetUnit() == BYTES) {
      this->setSendQueueCapacity(size.GetValue());
    }
    else {
      // don't know the exact size in bytes, guessing based on "standard" packet size
      this->setSendQueueCapacity(size.GetValue() * 1500);
    }
  }

  NS_LOG_FUNCTION(this << "Creating an ndnSIM transport instance for netDevice with URI"
                  << this->getLocalUri());

  NS_ASSERT_MSG(m_netDevice != 0, "NetDeviceFace needs to be assigned a valid NetDevice");

  m_node->RegisterProtocolHandler(MakeCallback(&NetDeviceTransport::receiveFromNetDevice, this),
                                  L3Protocol::ETHERNET_FRAME_TYPE, m_netDevice,
                                  true /*promiscuous mode*/);
}

NetDeviceTransport::~NetDeviceTransport()
{
  NS_LOG_FUNCTION_NOARGS();
}

ssize_t
NetDeviceTransport::getSendQueueLength()
{
  PointerValue txQueueAttribute;
  if (m_netDevice->GetAttributeFailSafe("TxQueue", txQueueAttribute)) {
    Ptr<ns3::QueueBase> txQueue = txQueueAttribute.Get<ns3::QueueBase>();
    return txQueue->GetNBytes();
  }
  else {
    return nfd::face::QUEUE_UNSUPPORTED;
  }
}

void
NetDeviceTransport::doClose()
{
  NS_LOG_FUNCTION(this << "Closing transport for netDevice with URI"
                  << this->getLocalUri());

  // set the state of the transport to "CLOSED"
  this->setState(nfd::face::TransportState::CLOSED);
}

void
NetDeviceTransport::doSend(const Block& packet, const nfd::EndpointId& endpoint)
{
  NS_LOG_FUNCTION(this << "Sending packet from netDevice with URI"
                  << this->getLocalUri());

  // 将 NFD 数据包转换为 NS3 数据包 / Convert NFD packet to NS3 packet
  BlockHeader header(packet);
  Ptr<ns3::Packet> ns3Packet = Create<ns3::Packet>();
  ns3Packet->AddHeader(header);

  if (m_netDevice->IsPointToPoint()) {
    // 点对点链路：直接广播发送 / Point-to-point link: send via broadcast
    m_netDevice->Send(ns3Packet, m_netDevice->GetBroadcast(),
                      L3Protocol::ETHERNET_FRAME_TYPE);
  }
  else {
    // 无线链路：尝试从 LP 包中提取 VndnTag，判断是否需要单播
    // Wireless link: try to extract VndnTag from the LP packet to decide unicast
    bool isSingleCast = false;
    uint64_t targetMac = 0;

    try {
      // 将 Block 解析为 LP 包 / Parse the Block as an LP packet
      ndn::lp::Packet lpPacket(packet);
      if (lpPacket.has<ndn::lp::VndnTagField>()) {
        auto vndnTag = lpPacket.get<ndn::lp::VndnTagField>();
        targetMac = vndnTag.getTargetMac();
        // 目标 MAC 不为 0 且不等于广播地址时，进行单播发送
        // When target MAC is non-zero and not the broadcast address, send unicast
        if (targetMac != 0) {
          isSingleCast = true;
        }
      }
    }
    catch (const std::exception& e) {
      // 解析失败时按广播处理 / Fall back to broadcast on parse failure
      NS_LOG_WARN("doSend: failed to parse LP packet for VndnTag: " << e.what());
    }

    if (isSingleCast) {
      // --- 单播发送 / Unicast send ---

      // 直接发送法，用于调试程序，绕过 WiFi 层直接从一个 node 把数据凭空发送到另一个程序。
      // Direct injection method for debugging: bypass the WiFi layer and send
      // data directly from one node to another node's receive queue.
      //
      // ns3::Ptr<ns3::Node> dstNode = ns3::NodeList::GetNode(dstNodeId);
      // ns3::Simulator::ScheduleWithContext(dstNode->GetId(), ns3::MilliSeconds(10),
      //                                     &NetDeviceTransport::receiveFromNetDevice2,
      //                                     (NetDeviceTransport*)dstNode->GetDevice(0)->netDeviceTransport,
      //                                     ns3Packet->Copy());

      // 将 uint64_t 目标 MAC 转换为 ns3::Address / Convert uint64_t target MAC to ns3::Address
      ns3::Address macAddr;
      macAddr.CopyAllFrom(reinterpret_cast<uint8_t*>(&targetMac), 8);
      m_netDevice->Send(ns3Packet, macAddr,
                        L3Protocol::ETHERNET_FRAME_TYPE);
    }
    else {
      // --- 广播发送 / Broadcast send ---

      // 以下代码用于测试，直接把数据绕过一切仿真的物理层，直接丢到对方的设备接收队列里。
      // The following code is for testing: bypass all simulated physical layers
      // and drop data directly into the destination device's receive queue.
      //
      // uint32_t m_thisNode = (ns3::Simulator::GetContext());
      // for (uint32_t i = 0; i < ns3::NodeList::GetNNodes(); i++) {
      //   ns3::Ptr<ns3::Node> dstNode = ns3::NodeList::GetNode(i);
      //   if (dstNode->GetId() == 2) {
      //     ns3::Simulator::ScheduleWithContext(dstNode->GetId(),
      //         ns3::NanoSeconds(rand() % 1000000 + 1000),
      //         &NetDeviceTransport::receiveFromNetDevice2,
      //         (NetDeviceTransport*)dstNode->GetDevice(0)->netDeviceTransport,
      //         ns3Packet->Copy());
      //   }
      // }

      m_netDevice->Send(ns3Packet, m_netDevice->GetBroadcast(),
                        L3Protocol::ETHERNET_FRAME_TYPE);
    }
  }
}

// 调试用直接接收回调 / Debug direct-receive callback
void
NetDeviceTransport::receiveFromNetDevice2(Ptr<const ns3::Packet> p)
{
  // 将 NS3 数据包转换为 NFD 数据包 / Convert NS3 packet to NFD packet
  Ptr<ns3::Packet> packet = p->Copy();

  BlockHeader header;
  packet->RemoveHeader(header);

  this->receive(std::move(header.getBlock()));
}

// 正常接收回调 / Normal receive callback
void
NetDeviceTransport::receiveFromNetDevice(Ptr<NetDevice> device,
                                         Ptr<const ns3::Packet> p,
                                         uint16_t protocol,
                                         const Address& from, const Address& to,
                                         NetDevice::PacketType packetType)
{
  NS_LOG_FUNCTION(device << p << protocol << from << to << packetType);

  // Convert NS3 packet to NFD packet
  Ptr<ns3::Packet> packet = p->Copy();

  BlockHeader header;
  packet->RemoveHeader(header);

  this->receive(std::move(header.getBlock()));
}

Ptr<NetDevice>
NetDeviceTransport::GetNetDevice() const
{
  return m_netDevice;
}

} // namespace ndn
} // namespace ns3
