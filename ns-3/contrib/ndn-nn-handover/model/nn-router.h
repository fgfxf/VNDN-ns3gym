/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#ifndef NN_ROUTER_H
#define NN_ROUTER_H

#include "nn-decision-model.h"
#include "vehicle-mobility-info.h"

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/util/scheduler.hpp>
#include <ndn-cxx/util/time.hpp>
#include <ns3/core-module.h>

#include <map>
#include <string>

namespace ns3 {
namespace nnhandover {

/**
 * @brief Common backhaul router application.
 *
 * This is the component that actually changes the backhaul route for the
 * subsequent Data packets. It runs on the router that is common to the two
 * RSUs between which a vehicle is handing over.
 *
 * Flow:
 *   OBU detects handover
 *     -> sends control Interest to the router (or to an RSU which relays it)
 *     -> NnRouter receives it, decodes the VehicleMobilityInfo
 *     -> runs the NnDecisionModel
 *     -> maps the chosen RSU id to a face id on this router
 *     -> calls NnRoutingStrategy::SetRouteHint(vehicleId, faceId)
 *
 * From that point on, the NnRoutingStrategy forwards Interests carrying that
 * vehicle id only to the NN-chosen RSU, so the downlink Data follows the
 * vehicle through the new RSU.
 */
class NnRouter
{
public:
  /**
   * @param appPrefix     application prefix (e.g. /ndn/nn/handover)
   * @param nodeName      router name (e.g. /ndn/router/router0)
   * @param decisionModel the NN decision model to use
   */
  NnRouter (const ndn::Name &appPrefix, const ndn::Name &nodeName,
            Ptr<NnDecisionModel> decisionModel);

  void Start ();
  void Stop ();

  /// Register a mapping: RSU id -> face id on this router.
  /// The router uses this to translate the NN decision (an RSU id) into the
  /// concrete face id that the NnRoutingStrategy understands.
  void AddRsuFace (const std::string &rsuId, uint64_t faceId);

private:
  /// Handle a handover control Interest coming directly from an OBU.
  void OnControlInterest (const ndn::Interest &interest);

  /// Handle a route-hint Interest coming from an RSU (already decided).
  void OnHintInterest (const ndn::Interest &interest);

  /// Install / update the route hint in the NnRoutingStrategy.
  void ApplyRouteHint (const std::string &vehicleId, const std::string &chosenRsuId,
                       double confidence, const std::string &reason);

  /// Get a pointer to the NnRoutingStrategy instance running on this node.
  /// Returns nullptr if the strategy is not installed.
  class ::nfd::fw::NnRoutingStrategy *GetStrategy () const;

  ndn::Name m_appPrefix;
  ndn::Name m_nodeName;
  std::string m_routerId;
  Ptr<NnDecisionModel> m_decisionModel;

  /// rsuId -> face id on this router
  std::map<std::string, uint64_t> m_rsuFaceMap;

  /// active route hints: vehicleId -> chosen RSU id (for logging / cleanup)
  std::map<std::string, std::string> m_activeHints;

  ndn::Face m_face;
  ndn::Scheduler m_scheduler;
  ndn::KeyChain m_keyChain;
};

} // namespace nnhandover
} // namespace ns3

#endif // NN_ROUTER_H
