/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#ifndef VEHICLE_MOBILITY_INFO_H
#define VEHICLE_MOBILITY_INFO_H

#include <ns3/core-module.h>
#include <ns3/mobility-model.h>

#include <string>

namespace ns3 {
namespace nnhandover {

/**
 * @brief Vehicle mobility information collected as the input feature vector
 *        for the neural-network routing decision.
 *
 * The fields here are the minimal set of "vehicle driving information" that
 * the OBU reports to the NN decision model when a handover between two RSUs
 * is about to happen. A real deployment would extend this structure with
 * more features (heading, acceleration, lane id, RSSI of each RSU, etc.).
 */
struct VehicleMobilityInfo
{
  uint32_t nodeId = 0;       ///< ns-3 node id of the vehicle (OBU)
  std::string vehicleId;     ///< human readable vehicle id (e.g. SUMO id)

  Vector position;           ///< current position (x, y, z) [m]
  Vector velocity;           ///< current velocity vector [m/s]
  double speed = 0.0;        ///< scalar speed [m/s]
  double heading = 0.0;      ///< heading angle [rad], 0 = east, CCW

  std::string currentRsuId;  ///< id of the RSU the OBU is currently attached to
  std::string targetRsuId;   ///< id of the RSU the OBU is handing over to
  double currentRssi = 0.0;  ///< signal strength from the current RSU [dBm]
  double targetRssi = 0.0;   ///< signal strength from the target RSU [dBm]

  /// Serialize the feature vector into a compact, parseable string.
  /// The format is a simple "key=value;..." list that is carried inside the
  /// NDN Interest ApplicationParameters so that the NN model on the router
  /// (or RSU) can decode it without extra dependencies.
  std::string
  Serialize () const
  {
    std::ostringstream os;
    os.precision (6);
    os << "node=" << nodeId << ";"
       << "vid=" << vehicleId << ";"
       << "px=" << position.x << ";"
       << "py=" << position.y << ";"
       << "pz=" << position.z << ";"
       << "vx=" << velocity.x << ";"
       << "vy=" << velocity.y << ";"
       << "vz=" << velocity.z << ";"
       << "speed=" << speed << ";"
       << "heading=" << heading << ";"
       << "curRsu=" << currentRsuId << ";"
       << "tgtRsu=" << targetRsuId << ";"
       << "curRssi=" << currentRssi << ";"
       << "tgtRssi=" << targetRssi;
    return os.str ();
  }

  /// Deserialize a feature vector produced by Serialize().
  static VehicleMobilityInfo
  Deserialize (const std::string &s)
  {
    VehicleMobilityInfo info;
    std::istringstream is (s);
    std::string token;
    while (std::getline (is, token, ';'))
      {
        auto eq = token.find ('=');
        if (eq == std::string::npos)
          continue;
        std::string key = token.substr (0, eq);
        std::string val = token.substr (eq + 1);
        if (key == "node")
          info.nodeId = std::stoul (val);
        else if (key == "vid")
          info.vehicleId = val;
        else if (key == "px")
          info.position.x = std::stod (val);
        else if (key == "py")
          info.position.y = std::stod (val);
        else if (key == "pz")
          info.position.z = std::stod (val);
        else if (key == "vx")
          info.velocity.x = std::stod (val);
        else if (key == "vy")
          info.velocity.y = std::stod (val);
        else if (key == "vz")
          info.velocity.z = std::stod (val);
        else if (key == "speed")
          info.speed = std::stod (val);
        else if (key == "heading")
          info.heading = std::stod (val);
        else if (key == "curRsu")
          info.currentRsuId = val;
        else if (key == "tgtRsu")
          info.targetRsuId = val;
        else if (key == "curRssi")
          info.currentRssi = std::stod (val);
        else if (key == "tgtRssi")
          info.targetRssi = std::stod (val);
      }
    return info;
  }
};

} // namespace nnhandover
} // namespace ns3

#endif // VEHICLE_MOBILITY_INFO_H
