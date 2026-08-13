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
    const std::vector<float> &probabilities, double dualPathGap,
    double dualPathMinSecondProbability)
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

  // 第一名始终作为主回程 RSU；第二名只在切换边界存在一定不确定性时加入。
  std::vector<uint32_t> selected = {candidateRsuIds[order[0]]};
  if (order.size () > 1)
    {
      const float secondProbability = probabilities[order[1]];
      const float probabilityGap = probabilities[order[0]] - secondProbability;
      // gap 条件覆盖 0.53/0.47 这类近似平局；secondProbability 条件覆盖
      // 0.78/0.22 这类并非平局、但第二条路径仍有实际价值的情况。
      if (probabilityGap <= dualPathGap ||
          secondProbability >= dualPathMinSecondProbability)
        selected.push_back (candidateRsuIds[order[1]]);
    }
  return selected;
}

} // namespace vanet
