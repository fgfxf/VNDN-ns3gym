/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#ifndef NN_ROUTING_STRATEGY_H
#define NN_ROUTING_STRATEGY_H

#include "vehicle-mobility-info.h"

#include "face/face.hpp"
#include "fw/strategy.hpp"
#include "fw/algorithm.hpp"
#include "fw/retx-suppression-exponential.hpp"

#include <ndn-cxx/name.hpp>

#include <map>
#include <mutex>
#include <string>

namespace nfd {
namespace fw {

/**
 * @brief NDN forwarding strategy that applies a neural-network decision to
 *        Interest routing on the common backhaul router.
 *
 * The common router sits between two (or more) RSUs. For a given content
 * prefix it normally has one FIB next-hop per RSU. When a vehicle hands over,
 * the NnRouterApp installs a per-vehicle "route hint" (vehicleId -> chosen
 * RSU face id) into this strategy through SetRouteHint(). The strategy then:
 *
 *   - For Interests whose name carries a vehicle id component that matches a
 *     known hint, forwards only to the hinted face (the NN-chosen RSU), so
 *     that the subsequent Data follows the vehicle.
 *   - For all other Interests, falls back to the normal multicast behaviour
 *     (forward to every eligible next-hop), which is the safe default.
 *
 * This keeps the NN decision out of the critical FIB data structure and lets
 * the strategy apply it purely in the forwarding plane, exactly as the task
 * describes ("change the backhaul route for the subsequent data packets").
 */
class NnRoutingStrategy : public Strategy
{
public:
  explicit NnRoutingStrategy (Forwarder &forwarder, const Name &name = getStrategyName ());

  static const Name &getStrategyName ();

  void
  afterReceiveInterest (const FaceEndpoint &ingress, const Interest &interest,
                        const shared_ptr<pit::Entry> &pitEntry) override;

  /// @name Neural-network route hint API (called by NnRouterApp)
  ///@{
  /**
   * @brief Install / update a per-vehicle route hint.
   *
   * After this call, Interests carrying \p vehicleId will be forwarded only
   * to \p outFaceId (the NN-chosen RSU face). Pass faceId=0 to clear a hint.
   */
  void SetRouteHint (const std::string &vehicleId, uint64_t outFaceId);

  /// Remove a per-vehicle route hint (e.g. when the handover completes).
  void ClearRouteHint (const std::string &vehicleId);

  /// Number of currently active route hints (for logging / testing).
  size_t NumRouteHints () const;
  ///@}

private:
  /// Extract the vehicle id from an Interest name, or "" if not present.
  /// The convention is: /<prefix>/__veh__/<vehicleId>/...
  static std::string ExtractVehicleId (const Interest &interest);

  RetxSuppressionExponential m_retxSuppression;
  static const time::milliseconds RETX_SUPPRESSION_INITIAL;
  static const time::milliseconds RETX_SUPPRESSION_MAX;

  /// vehicleId -> chosen RSU face id (0 means "no hint")
  std::map<std::string, uint64_t> m_routeHints;
  mutable std::mutex m_hintMutex;
};

} // namespace fw
} // namespace nfd

#endif // NN_ROUTING_STRATEGY_H
