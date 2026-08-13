/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#ifndef VNDN_ROUTER_H
#define VNDN_ROUTER_H

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/data.hpp>

#include "ns3/event-id.h"
#include "ns3/ptr.h"

#include <map>
#include <set>
#include <string>
#include <vector>

namespace ns3 {
class Node;
}

namespace vanet {

/**
 * \brief 最基础的 VNDN 路由器应用。
 *
 * 收到基础设施侧 Interest 后代理向服务器请求，并把 Data 主动回传到请求接口。
 */
class VndnRouter
{
public:
  VndnRouter ();

  void
  Start ();

  void
  Stop ();

private:
  struct PendingRequest;

  void
  ProcessInterest (const ndn::Interest &interest);

  void
  RegisterP2pFaces ();

  void
  ResolveServerFace ();

  void
  ForwardInterestToServer (const ndn::Interest &interest, uint64_t returnFaceId);

  void
  OnServerData (const ndn::Interest &interest, const ndn::Data &data);

  void
  OnServerNack (const ndn::Interest &interest, const ndn::lp::Nack &nack);

  void
  OnServerTimeout (const ndn::Interest &interest);

  void
  SendP2pHandshake ();

  void
  OnP2pHandshakeInterest (const ndn::Interest &interest);

  void
  OnP2pHandshakeData (uint64_t outFaceId, const ndn::Interest &interest,
                      const ndn::Data &data);

  void
  OnP2pHandshakeNack (const ndn::Interest &interest, const ndn::lp::Nack &nack);

  void
  OnP2pHandshakeTimeout (const ndn::Interest &interest);

  void
  OnP2pHandshakeDataPush (const ndn::Interest &interest, const ndn::Data &data);

  void
  RelayRsuControlData (const ndn::Data &data);

  /** 处理当前 RSU 随 Interest 发来的神经网络回程路由指令。 */
  void
  OnNeuralRouteInstruction (const ndn::Data &data);

  /**
   * 通知目标 RSU 为原始业务 Interest 在无线 face 上创建 PIT。
   *
   * 控制报文只负责提前铺设反向路径，真正的业务 Data 仍保持原名称，
   * 到达目标 RSU 后由 NFD 按 PIT 的 in-record 自动发送到无线接口。
   */
  void
  SendNeuralPitPrepare (uint32_t targetRsuId, uint64_t targetFaceId,
                        uint32_t obuNodeId, uint64_t obuMac,
                        const ndn::Interest &originalInterest);

  /** 为尚未预备的神经网络目标 RSU 发送 PIT 控制报文。 */
  void
  PrepareNeuralReturnPits (PendingRequest &request);

  /** 用目标 RSU ID 覆盖指定请求的回程接口。 */
  bool
  ApplyNeuralReturnRoute (PendingRequest &request,
                          const std::vector<uint32_t> &returnRsuIds);

  void
  PushIdentityData (uint64_t faceId, uint32_t nodeId,
                    const std::string &role, const ndn::Name &name);

private:
  struct PendingRequest
  {
    /// 最初到达 Router 的车辆业务 Interest，保留 OBU ID/MAC 等 LP 标签。
    std::shared_ptr<const ndn::Interest> originalInterest;
    /// 服务器 Data 应被推送到的 RSU P2P face；双路径时包含两个 face。
    std::set<uint64_t> returnFaceIds;
    /// 与 returnFaceIds 对应的 RSU 节点 ID，供回程日志和标签使用。
    std::vector<uint32_t> requestedReturnRsuIds;
    /// 已发送过建 PIT 控制报文的 RSU，避免同名 Interest 聚合时重复预备。
    std::set<uint32_t> preparedReturnRsuIds;
  };

  ndn::Face m_face;
  bool m_active = false;
  ns3::Ptr<ns3::Node> m_thisNode;
  std::vector<uint64_t> m_p2pFaceIds;
  std::map<uint32_t, uint64_t> m_infrastructureRoutes;
  std::map<uint32_t, std::string> m_infrastructureRoles;
  std::set<uint32_t> m_seenInfrastructureNodes;
  ns3::EventId m_p2pHandshakeEvent;
  uint32_t m_p2pHandshakeRound = 0;
  uint64_t m_serverFaceId = 0;
  uint64_t m_neuralPitSequence = 0;
  std::map<ndn::Name, PendingRequest> m_pendingRequests;
  std::map<ndn::Name, std::vector<uint32_t>> m_neuralRouteInstructions;
};

} // namespace vanet

#endif // VNDN_ROUTER_H
