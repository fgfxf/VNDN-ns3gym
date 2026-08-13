/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include "vndn-rsu-forwarding-policy.h"

#include <algorithm>
#include <limits>

namespace vanet {

int64_t
VndnRsuForwardingPolicy::SelectNearestRsu (
    const ns3::Vector &vehiclePosition,
    const std::vector<std::pair<uint32_t, ns3::Vector>> &rsuPositions)
{
  int64_t nearestRsuId = -1;
  double nearestDistanceSquared = std::numeric_limits<double>::max ();
  for (const auto &rsu : rsuPositions)
    {
      const double dx = vehiclePosition.x - rsu.second.x;
      const double dy = vehiclePosition.y - rsu.second.y;
      const double dz = vehiclePosition.z - rsu.second.z;
      const double distanceSquared = dx * dx + dy * dy + dz * dz;
      if (distanceSquared < nearestDistanceSquared)
        {
          nearestDistanceSquared = distanceSquared;
          nearestRsuId = rsu.first;
        }
    }
  return nearestRsuId;
}

std::vector<uint32_t>
VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
    const std::vector<uint32_t> &candidateRsuIds,
    const std::vector<float> &probabilities, double dualPathGap)
{
  if (candidateRsuIds.empty () || candidateRsuIds.size () != probabilities.size ())
    return {};

  std::vector<uint32_t> order (probabilities.size ());
  for (uint32_t index = 0; index < order.size (); ++index)
    order[index] = index;
  std::sort (order.begin (), order.end (),
             [&probabilities] (uint32_t left, uint32_t right) {
               return probabilities[left] > probabilities[right];
             });

  std::vector<uint32_t> selected = {candidateRsuIds[order[0]]};
  if (order.size () > 1 &&
      probabilities[order[0]] - probabilities[order[1]] <= dualPathGap)
    selected.push_back (candidateRsuIds[order[1]]);
  return selected;
}

} // namespace vanet
