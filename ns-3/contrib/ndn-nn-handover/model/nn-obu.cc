/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#include "nn-obu.h"

#include <ns3/log.h>
#include <ns3/node.h>
#include <ns3/node-list.h>
#include <ns3/simulator.h>
#include <ns3/mobility-model.h>

#include <cmath>
#include <limits>

NS_LOG_COMPONENT_DEFINE ("ndn.NnObu");

namespace ns3 {
namespace nnhandover {

NnObu::NnObu (const ndn::Name &appPrefix, const ndn::Name &nodeName, const std::string &routerId,
              const std::vector<RsuEntry> &rsus)
    : m_appPrefix (appPrefix),
      m_nodeName (nodeName),
      m_routerId (routerId),
      m_rsus (rsus),
      m_scheduler (m_face.getIoService ())
{
  // vehicle id = last component of the node name
  m_vehicleId = nodeName.empty () ? "veh" : nodeName.at (-1).toUri ();
}

void
NnObu::SetSampleIntervalMs (uint32_t ms)
{
  m_sampleIntervalMs = ms;
}

void
NnObu::Start ()
{
  NS_LOG_INFO ("NnObu[" << m_vehicleId << "] starting, router=" << m_routerId
                        << " #rsus=" << m_rsus.size ());
  // initial attachment: pick the best RSU right away
  const RsuEntry *best = BestRsu ();
  if (best)
    m_currentRsuId = best->rsuId;
  SampleAndDetect ();
}

void
NnObu::Stop ()
{
  NS_LOG_INFO ("NnObu[" << m_vehicleId << "] stopping");
  m_sampleEvent.cancel ();
}

double
NnObu::EstimateRssi (const Vector &rsuPos) const
{
  Ptr<Node> thisNode = NodeList::GetNode (Simulator::GetContext ());
  Ptr<MobilityModel> mob = thisNode->GetObject<MobilityModel> ();
  if (!mob)
    return -120.0;
  double dx = mob->GetPosition ().x - rsuPos.x;
  double dy = mob->GetPosition ().y - rsuPos.y;
  double dz = mob->GetPosition ().z - rsuPos.z;
  double dist = std::sqrt (dx * dx + dy * dy + dz * dz);
  if (dist < 1.0)
    dist = 1.0;
  // Simple free-space-like proxy: -40 dBm at 1m, 6 dB drop per doubling.
  return -40.0 - 20.0 * std::log10 (dist);
}

const RsuEntry *
NnObu::BestRsu () const
{
  const RsuEntry *best = nullptr;
  double bestRssi = -std::numeric_limits<double>::max ();
  for (const auto &r : m_rsus)
    {
      double rssi = EstimateRssi (r.position);
      if (rssi > bestRssi)
        {
          bestRssi = rssi;
          best = &r;
        }
    }
  return best;
}

void
NnObu::SampleAndDetect ()
{
  Ptr<Node> thisNode = NodeList::GetNode (Simulator::GetContext ());
  Ptr<MobilityModel> mob = thisNode->GetObject<MobilityModel> ();

  // refresh RSSI for every known RSU
  for (auto &r : m_rsus)
    r.rssi = EstimateRssi (r.position);

  const RsuEntry *best = BestRsu ();
  if (!best)
    {
      NS_LOG_WARN ("NnObu[" << m_vehicleId << "] no RSU visible");
      m_sampleEvent =
          m_scheduler.schedule (ndn::time::milliseconds (m_sampleIntervalMs),
                                [this] { SampleAndDetect (); });
      return;
    }

  std::string newRsuId = best->rsuId;
  if (m_currentRsuId.empty ())
    {
      m_currentRsuId = newRsuId;
      NS_LOG_INFO ("NnObu[" << m_vehicleId << "] initial attach to RSU " << m_currentRsuId);
    }
  else if (newRsuId != m_currentRsuId)
    {
      // ---- HANDOVER DETECTED ----
      NS_LOG_INFO ("NnObu[" << m_vehicleId << "] HANDOVER " << m_currentRsuId << " -> "
                            << newRsuId);

      VehicleMobilityInfo info;
      info.nodeId = thisNode->GetId ();
      info.vehicleId = m_vehicleId;
      if (mob)
        {
          info.position = mob->GetPosition ();
          info.velocity = mob->GetVelocity ();
          info.speed = std::sqrt (info.velocity.x * info.velocity.x +
                                  info.velocity.y * info.velocity.y +
                                  info.velocity.z * info.velocity.z);
          if (info.speed > 1e-6)
            info.heading = std::atan2 (info.velocity.y, info.velocity.x);
        }
      info.currentRsuId = m_currentRsuId;
      info.targetRsuId = newRsuId;
      for (const auto &r : m_rsus)
        {
          if (r.rsuId == m_currentRsuId)
            info.currentRssi = r.rssi;
          if (r.rsuId == newRsuId)
            info.targetRssi = r.rssi;
        }

      SendHandoverControl (info);
      m_currentRsuId = newRsuId;
    }

  m_sampleEvent = m_scheduler.schedule (ndn::time::milliseconds (m_sampleIntervalMs),
                                        [this] { SampleAndDetect (); });
}

void
NnObu::SendHandoverControl (const VehicleMobilityInfo &info)
{
  // /<appPrefix>/control/<routerId>/__veh__/<vehicleId>/<curRsu>/<tgtRsu>
  ndn::Name name = m_appPrefix;
  name.append ("control");
  name.append (m_routerId);
  name.append ("__veh__");
  name.append (m_vehicleId);
  name.append (info.currentRsuId);
  name.append (info.targetRsuId);

  ndn::Interest interest;
  interest.setName (name);
  interest.setInterestLifetime (ndn::time::milliseconds (1000));
  interest.setMustBeFresh (true);

  std::string payload = info.Serialize ();
  interest.setApplicationParameters (reinterpret_cast<const uint8_t *> (payload.data ()),
                                     payload.size ());

  NS_LOG_INFO ("NnObu[" << m_vehicleId << "] sending handover control: " << name);

  m_face.expressInterest (
      interest,
      [this] (const ndn::Interest &, const ndn::Data &data) {
        NS_LOG_INFO ("NnObu[" << m_vehicleId << "] control ack: "
                              << data.getName ().toUri ());
      },
      [this] (const ndn::Interest &, const ndn::lp::Nack &nack) {
        NS_LOG_WARN ("NnObu[" << m_vehicleId << "] control NACK: " << nack.getReason ());
      },
      [this] (const ndn::Interest &) {
        NS_LOG_WARN ("NnObu[" << m_vehicleId << "] control timeout");
      });
}

} // namespace nnhandover
} // namespace ns3
