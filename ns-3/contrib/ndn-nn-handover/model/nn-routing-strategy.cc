/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#include "nn-routing-strategy.h"
#include "algorithm.hpp"
#include "common/logger.hpp"

namespace nfd {
namespace fw {

NFD_REGISTER_STRATEGY (NnRoutingStrategy);

NFD_LOG_INIT (NnRoutingStrategy);

const time::milliseconds NnRoutingStrategy::RETX_SUPPRESSION_INITIAL (10);
const time::milliseconds NnRoutingStrategy::RETX_SUPPRESSION_MAX (250);

// Name component that tags an Interest as belonging to a specific vehicle.
// Convention: /<prefix>/__veh__/<vehicleId>/...
static const std::string VEH_MARKER = "__veh__";

NnRoutingStrategy::NnRoutingStrategy (Forwarder &forwarder, const Name &name)
    : Strategy (forwarder),
      m_retxSuppression (RETX_SUPPRESSION_INITIAL,
                         RetxSuppressionExponential::DEFAULT_MULTIPLIER,
                         RETX_SUPPRESSION_MAX)
{
  this->setInstanceName (makeInstanceName (name, getStrategyName ()));
}

const Name &
NnRoutingStrategy::getStrategyName ()
{
  static Name strategyName ("/localhost/nfd/strategy/nn-routing/%FD%01");
  return strategyName;
}

std::string
NnRoutingStrategy::ExtractVehicleId (const Interest &interest)
{
  const Name &name = interest.getName ();
  for (size_t i = 0; i + 1 < name.size (); ++i)
    {
      if (name.get (i).toUri () == VEH_MARKER)
        return name.get (i + 1).toUri ();
    }
  return "";
}

void
NnRoutingStrategy::SetRouteHint (const std::string &vehicleId, uint64_t outFaceId)
{
  if (vehicleId.empty ())
    return;
  std::lock_guard<std::mutex> lock (m_hintMutex);
  if (outFaceId == 0)
    m_routeHints.erase (vehicleId);
  else
    m_routeHints[vehicleId] = outFaceId;
  NFD_LOG_DEBUG ("SetRouteHint vehicle=" << vehicleId << " face=" << outFaceId);
}

void
NnRoutingStrategy::ClearRouteHint (const std::string &vehicleId)
{
  std::lock_guard<std::mutex> lock (m_hintMutex);
  m_routeHints.erase (vehicleId);
  NFD_LOG_DEBUG ("ClearRouteHint vehicle=" << vehicleId);
}

size_t
NnRoutingStrategy::NumRouteHints () const
{
  std::lock_guard<std::mutex> lock (m_hintMutex);
  return m_routeHints.size ();
}

void
NnRoutingStrategy::afterReceiveInterest (const FaceEndpoint &ingress, const Interest &interest,
                                         const shared_ptr<pit::Entry> &pitEntry)
{
  const fib::Entry &fibEntry = this->lookupFib (*pitEntry);
  const fib::NextHopList &nexthops = fibEntry.getNextHops ();
  NFD_LOG_DEBUG ("Interest=" << interest << " inFaceId=" << ingress.face.getId ());

  // 1) Look up the neural-network route hint for this vehicle (if any).
  std::string vehicleId = ExtractVehicleId (interest);
  uint64_t hintedFace = 0;
  bool hasHint = false;
  if (!vehicleId.empty ())
    {
      std::lock_guard<std::mutex> lock (m_hintMutex);
      auto it = m_routeHints.find (vehicleId);
      if (it != m_routeHints.end ())
        {
          hintedFace = it->second;
          hasHint = true;
        }
    }

  int nEligibleNextHops = 0;
  bool isSuppressed = false;

  for (const auto &nexthop : nexthops)
    {
      Face &outFace = nexthop.getFace ();

      // If the NN gave us a hint, only forward to the hinted face.
      if (hasHint && outFace.getId () != hintedFace)
        continue;

      RetxSuppressionResult suppressResult =
          m_retxSuppression.decidePerUpstream (*pitEntry, outFace);

      if (suppressResult == RetxSuppressionResult::SUPPRESS)
        {
          NFD_LOG_DEBUG (interest << " from=" << ingress << " to=" << outFace.getId ()
                                  << " suppressed");
          isSuppressed = true;
          continue;
        }

      if ((outFace.getId () == ingress.face.getId () &&
           outFace.getLinkType () != ndn::nfd::LINK_TYPE_AD_HOC) ||
          wouldViolateScope (ingress.face, interest, outFace))
        {
          continue;
        }

      this->sendInterest (pitEntry, FaceEndpoint (outFace, 0), interest);
      NFD_LOG_DEBUG (interest << " from=" << ingress << " pitEntry-to=" << outFace.getId ()
                              << (hasHint ? " [NN-hint]" : ""));

      if (suppressResult == RetxSuppressionResult::FORWARD)
        {
          m_retxSuppression.incrementIntervalForOutRecord (*pitEntry->getOutRecord (outFace));
        }
      ++nEligibleNextHops;
    }

  if (nEligibleNextHops == 0 && !isSuppressed)
    {
      NFD_LOG_DEBUG (interest << " from=" << ingress << " noNextHop: rejectPendingInterest");
      this->rejectPendingInterest (pitEntry);
    }
}

} // namespace fw
} // namespace nfd
