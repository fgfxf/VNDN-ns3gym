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
 * 当前仅注册根前缀并打印收到的 Interest，不发送 Data，也不主动发送 Interest。
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
  ndn::Face m_face;
  bool m_active = false;
  ns3::Ptr<ns3::Node> m_thisNode;
  std::vector<uint64_t> m_p2pFaceIds;
  std::map<uint32_t, uint64_t> m_infrastructureRoutes;
  std::map<uint32_t, std::string> m_infrastructureRoles;
  std::set<uint32_t> m_seenInfrastructureNodes;
  ns3::EventId m_p2pHandshakeEvent;
  uint32_t m_p2pHandshakeRound = 0;
};

} // namespace vanet

#endif // VNDN_ROUTER_H
