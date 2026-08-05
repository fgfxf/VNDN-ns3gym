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
  PushIdentityData (uint64_t faceId, uint32_t nodeId,
                    const std::string &role, const ndn::Name &name);

private:
  struct PendingRequest
  {
    std::shared_ptr<const ndn::Interest> originalInterest;
    std::set<uint64_t> returnFaceIds;
    // 未来由基站指定回程 RSU 时，可在这里保存目标 RSU nodeId，随后通过
    // m_infrastructureRoutes 将其解析为 returnFaceIds。
    int64_t requestedReturnRsuId = -1;
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
  std::map<ndn::Name, PendingRequest> m_pendingRequests;
};

} // namespace vanet

#endif // VNDN_ROUTER_H
