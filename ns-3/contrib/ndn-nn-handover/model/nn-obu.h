/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#ifndef NN_OBU_H
#define NN_OBU_H

#include "vehicle-mobility-info.h"

#include <ndn-cxx/face.hpp>
#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/security/key-chain.hpp>
#include <ndn-cxx/util/scheduler.hpp>
#include <ndn-cxx/util/time.hpp>
#include <ns3/core-module.h>
#include <ns3/mobility-model.h>

#include <map>
#include <string>
#include <vector>

namespace ns3 {
namespace nnhandover {

/**
 * @brief Description of one RSU as seen by an OBU.
 *
 * The OBU keeps a small table of the RSUs it can hear. The RSSI is a simple
 * distance-based proxy when no real PHY measurement is available.
 */
struct RsuEntry
{
  std::string rsuId;        ///< unique RSU id (matches the RSU app NodeName)
  uint32_t nodeId = 0;      ///< ns-3 node id of the RSU
  Vector position;          ///< RSU position [m]
  double rssi = 0.0;        ///< current RSSI estimate [dBm]
};

/**
 * @brief On-Board Unit (vehicle) application.
 *
 * Responsibilities:
 *   1. Periodically sample its own mobility (position, velocity, speed).
 *   2. Estimate the RSSI of every known RSU and pick the "current" RSU (the
 *      one with the strongest signal).
 *   3. Detect a handover: the moment the best RSU changes from the previously
 *      attached one to a different one.
 *   4. On handover, build a VehicleMobilityInfo feature vector and send a
 *      control Interest to the COMMON ROUTER of the two RSUs. The control
 *      Interest carries the feature vector so that the router (or an RSU)
 *      can run the neural-network decision and install a route hint.
 *
 * The control Interest name convention is:
 *   /ndn/nn/handover/control/<routerId>/__veh__/<vehicleId>/<curRsu>/<tgtRsu>
 * and the feature vector is carried in ApplicationParameters.
 */
class NnObu
{
public:
  /**
   * @param appPrefix  application prefix (e.g. /ndn/nn/handover)
   * @param nodeName   vehicle name (e.g. /ndn/vehicle/car_0)
   * @param routerId   id of the common backhaul router to send control to
   * @param rsus       the list of RSUs this OBU may hand over between
   */
  NnObu (const ndn::Name &appPrefix, const ndn::Name &nodeName, const std::string &routerId,
        const std::vector<RsuEntry> &rsus);

  void Start ();
  void Stop ();

  /// Periodic sampling interval in milliseconds (configurable via the App).
  void SetSampleIntervalMs (uint32_t ms);

private:
  /// Periodic mobility + RSSI sampling and handover detection.
  void SampleAndDetect ();

  /// Send the handover control Interest to the common router.
  void SendHandoverControl (const VehicleMobilityInfo &info);

  /// Distance-based RSSI proxy: stronger when closer. rsuPos in [m].
  double EstimateRssi (const Vector &rsuPos) const;

  /// Find the RSU entry with the strongest current RSSI.
  const RsuEntry *BestRsu () const;

  ndn::Name m_appPrefix;
  ndn::Name m_nodeName;
  std::string m_vehicleId; ///< last component of m_nodeName
  std::string m_routerId;
  std::vector<RsuEntry> m_rsus;

  ndn::Face m_face;
  ndn::Scheduler m_scheduler;
  ndn::KeyChain m_keyChain;

  uint32_t m_sampleIntervalMs = 500;
  scheduler::EventId m_sampleEvent;

  std::string m_currentRsuId; ///< RSU the OBU is currently attached to
};

} // namespace nnhandover
} // namespace ns3

#endif // NN_OBU_H
