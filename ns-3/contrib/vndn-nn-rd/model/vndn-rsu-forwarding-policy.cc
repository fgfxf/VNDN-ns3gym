/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include "vndn-rsu-forwarding-policy.h"

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

} // namespace vanet
