/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#ifndef NN_RSU_H
#define NN_RSU_H

#include "nn-decision-model.h"
#include "vehicle-mobility-info.h"

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/util/scheduler.hpp>
#include <ndn-cxx/util/time.hpp>
#include <ns3/core-module.h>

#include <string>

namespace ns3 {
namespace nnhandover {

/**
 * @brief Road-Side Unit (base station) application.
 *
 * In this framework the RSU has two roles:
 *   1. It is a normal NDN producer for the data the vehicles consume.
 *   2. (Optional) It can act as a relay for handover control: when an OBU
 *      sends its handover control Interest to the RSU instead of directly to
 *      the common router, the RSU runs the NN decision model and forwards the
 *      resulting route hint to the common router.
 *
 * The common router (NnRouterApp) is the component that actually installs the
 * route hint into the NnRoutingStrategy. The RSU here is kept simple so that
 * the framework can be used in topologies where the router is not directly
 * reachable by the OBU.
 */
class NnRsu
{
public:
  NnRsu (const ndn::Name &appPrefix, const ndn::Name &nodeName,
         Ptr<NnDecisionModel> decisionModel, const std::string &routerId);

  void Start ();
  void Stop ();

  /// Prefix under which this RSU produces data, e.g. /ndn/data/rsu0
  void SetDataPrefix (const ndn::Name &dataPrefix);

private:
  /// Handle a handover control Interest from an OBU.
  void OnControlInterest (const ndn::Interest &interest);

  /// Handle a normal data Interest (producer role).
  void OnDataInterest (const ndn::Interest &interest);

  /// Forward the NN decision to the common router as a route-hint command.
  void ForwardRouteHint (const NnDecision &decision, const std::string &vehicleId);

  ndn::Name m_appPrefix;
  ndn::Name m_nodeName;
  std::string m_rsuId; ///< last component of m_nodeName
  std::string m_routerId;
  ndn::Name m_dataPrefix;

  Ptr<NnDecisionModel> m_decisionModel;

  ndn::Face m_face;
  ndn::Scheduler m_scheduler;
  ndn::KeyChain m_keyChain;
};

} // namespace nnhandover
} // namespace ns3

#endif // NN_RSU_H
