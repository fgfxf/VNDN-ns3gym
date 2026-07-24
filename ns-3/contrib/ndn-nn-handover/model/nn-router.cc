/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#include "nn-router.h"
#include "nn-routing-strategy.h"

#include "ns3/ndnSIM/model/ndn-l3-protocol.hpp"
#include "ns3/ndnSIM/NFD/daemon/fw/forwarder.hpp"

#include <ns3/log.h>
#include <ns3/node.h>
#include <ns3/node-list.h>
#include <ns3/simulator.h>

#include <cstring>

NS_LOG_COMPONENT_DEFINE ("ndn.NnRouter");

namespace ns3 {
namespace nnhandover {

NnRouter::NnRouter (const ndn::Name &appPrefix, const ndn::Name &nodeName,
                    Ptr<NnDecisionModel> decisionModel)
    : m_appPrefix (appPrefix),
      m_nodeName (nodeName),
      m_decisionModel (decisionModel),
      m_scheduler (m_face.getIoService ())
{
  m_routerId = nodeName.empty () ? "router" : nodeName.at (-1).toUri ();
}

void
NnRouter::AddRsuFace (const std::string &rsuId, uint64_t faceId)
{
  m_rsuFaceMap[rsuId] = faceId;
  NS_LOG_INFO ("NnRouter[" << m_routerId << "] mapped RSU " << rsuId << " -> face " << faceId);
}

void
NnRouter::Start ()
{
  NS_LOG_INFO ("NnRouter[" << m_routerId << "] starting");

  // /<appPrefix>/control/<routerId>  -> direct control from OBU
  ndn::Name ctrlPrefix = m_appPrefix;
  ctrlPrefix.append ("control");
  ctrlPrefix.append (m_routerId);
  m_face.setInterestFilter (ctrlPrefix,
                            std::bind (&NnRouter::OnControlInterest, this, _2),
                            [] (const ndn::Name &, const std::string &reason) {
                              NS_LOG_ERROR ("Router control filter failed: " << reason);
                            },
                            [] (const ndn::Name &) {});

  // /<appPrefix>/hint/<routerId>  -> pre-decided hint from an RSU
  ndn::Name hintPrefix = m_appPrefix;
  hintPrefix.append ("hint");
  hintPrefix.append (m_routerId);
  m_face.setInterestFilter (hintPrefix,
                            std::bind (&NnRouter::OnHintInterest, this, _2),
                            [] (const ndn::Name &, const std::string &reason) {
                              NS_LOG_ERROR ("Router hint filter failed: " << reason);
                            },
                            [] (const ndn::Name &) {});
}

void
NnRouter::Stop ()
{
  NS_LOG_INFO ("NnRouter[" << m_routerId << "] stopping, active hints=" << m_activeHints.size ());
}

::nfd::fw::NnRoutingStrategy *
NnRouter::GetStrategy () const
{
  Ptr<Node> thisNode = NodeList::GetNode (Simulator::GetContext ());
  auto l3 = thisNode->GetObject<ns3::ndn::L3Protocol> ();
  if (!l3)
    return nullptr;
  ::nfd::Forwarder &forwarder = *l3->getForwarder ();
  // The NnRoutingStrategy is installed on the root prefix "/" in the example.
  ::nfd::fw::Strategy &s = forwarder.getStrategyChoice ().findEffectiveStrategy (ndn::Name ("/"));
  return dynamic_cast<::nfd::fw::NnRoutingStrategy *> (&s);
}

void
NnRouter::OnControlInterest (const ndn::Interest &interest)
{
  // Name: /<appPrefix>/control/<routerId>/__veh__/<vehicleId>/<curRsu>/<tgtRsu>
  const ndn::Name &name = interest.getName ();
  NS_LOG_INFO ("NnRouter[" << m_routerId << "] control interest: " << name);

  std::string payload;
  payload.assign (reinterpret_cast<const char *> (interest.getApplicationParameters ().value ()),
                  interest.getApplicationParameters ().value_size ());
  VehicleMobilityInfo info = VehicleMobilityInfo::Deserialize (payload);

  NnDecision decision;
  if (m_decisionModel)
    {
      decision = m_decisionModel->Decide (info);
      NS_LOG_INFO ("NnRouter[" << m_routerId << "] NN decision for " << info.vehicleId
                               << ": choose RSU=" << decision.chosenRsuId << " conf="
                               << decision.confidence << " (" << decision.reason << ")");
    }
  else
    {
      decision.chosenRsuId = info.targetRsuId;
      decision.confidence = 1.0;
      decision.reason = "no-model-default-to-target";
    }

  ApplyRouteHint (info.vehicleId, decision.chosenRsuId, decision.confidence, decision.reason);

  // Acknowledge.
  auto data = std::make_shared<ndn::Data> (name);
  std::string ack = "ok";
  data->setContent (reinterpret_cast<const uint8_t *> (ack.data ()), ack.size ());
  data->setFreshnessPeriod (ndn::time::milliseconds (1000));
  m_keyChain.sign (*data);
  m_face.put (*data);
}

void
NnRouter::OnHintInterest (const ndn::Interest &interest)
{
  // Name: /<appPrefix>/hint/<routerId>/__veh__/<vehicleId>/<chosenRsu>
  const ndn::Name &name = interest.getName ();
  NS_LOG_INFO ("NnRouter[" << m_routerId << "] hint interest: " << name);

  // The chosen RSU is the last component; the vehicle id is after __veh__.
  std::string vehicleId;
  std::string chosenRsu;
  for (size_t i = 0; i + 1 < name.size (); ++i)
    {
      if (name.get (i).toUri () == "__veh__")
        {
          vehicleId = name.get (i + 1).toUri ();
          if (i + 2 < name.size ())
            chosenRsu = name.get (i + 2).toUri ();
          break;
        }
    }

  std::string confStr;
  confStr.assign (reinterpret_cast<const char *> (interest.getApplicationParameters ().value ()),
                  interest.getApplicationParameters ().value_size ());
  double confidence = 0.0;
  try
    {
      confidence = std::stod (confStr);
    }
  catch (...)
    {
    }

  ApplyRouteHint (vehicleId, chosenRsu, confidence, "rsu-relayed-hint");

  // Acknowledge.
  auto data = std::make_shared<ndn::Data> (name);
  std::string ack = "ok";
  data->setContent (reinterpret_cast<const uint8_t *> (ack.data ()), ack.size ());
  data->setFreshnessPeriod (ndn::time::milliseconds (1000));
  m_keyChain.sign (*data);
  m_face.put (*data);
}

void
NnRouter::ApplyRouteHint (const std::string &vehicleId, const std::string &chosenRsuId,
                          double confidence, const std::string &reason)
{
  if (vehicleId.empty () || chosenRsuId.empty ())
    {
      NS_LOG_WARN ("NnRouter[" << m_routerId << "] ignoring empty hint");
      return;
    }

  auto it = m_rsuFaceMap.find (chosenRsuId);
  if (it == m_rsuFaceMap.end ())
    {
      NS_LOG_WARN ("NnRouter[" << m_routerId << "] no face mapping for RSU " << chosenRsuId
                               << ", hint ignored");
      return;
    }
  uint64_t faceId = it->second;

  auto *strategy = GetStrategy ();
  if (!strategy)
    {
      NS_LOG_WARN ("NnRouter[" << m_routerId
                               << "] NnRoutingStrategy not installed, hint ignored");
      return;
    }

  strategy->SetRouteHint (vehicleId, faceId);
  m_activeHints[vehicleId] = chosenRsuId;

  NS_LOG_INFO ("NnRouter[" << m_routerId << "] APPLIED route hint: vehicle=" << vehicleId
                           << " -> RSU=" << chosenRsuId << " (face=" << faceId
                           << ", conf=" << confidence << ", " << reason << ")");
}

} // namespace nnhandover
} // namespace ns3
