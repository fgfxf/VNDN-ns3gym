/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#ifndef VNDN_RSU_FORWARDING_POLICY_H
#define VNDN_RSU_FORWARDING_POLICY_H

#include "ns3/vector.h"

#include <cstdint>
#include <utility>
#include <vector>

namespace vanet {

/** Pure forwarding-policy helpers shared by RSU protocol code and tests. */
class VndnRsuForwardingPolicy
{
public:
  /** Return the node ID of the nearest RSU, or -1 when no candidate exists. */
  static int64_t
  SelectNearestRsu (
      const ns3::Vector &vehiclePosition,
      const std::vector<std::pair<uint32_t, ns3::Vector>> &rsuPositions);

  /**
   * Select the highest-probability RSU and optionally the runner-up when the
   * probability gap is no larger than dualPathGap.
   */
  static std::vector<uint32_t>
  SelectNeuralReturnRsus (const std::vector<uint32_t> &candidateRsuIds,
                          const std::vector<float> &probabilities,
                          double dualPathGap);
};

} // namespace vanet

#endif // VNDN_RSU_FORWARDING_POLICY_H
