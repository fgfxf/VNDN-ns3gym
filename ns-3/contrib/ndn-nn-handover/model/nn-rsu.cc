/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#include "nn-rsu.h"

#include <ns3/log.h>

#include <cstring>

NS_LOG_COMPONENT_DEFINE ("ndn.NnRsu");

namespace ns3 {
namespace nnhandover {

NnRsu::NnRsu (const ndn::Name &appPrefix, const ndn::Name &nodeName,
              Ptr<NnDecisionModel> decisionModel, const std::string &routerId)
    : m_appPrefix (appPrefix),
      m_nodeName (nodeName),
      m_routerId (routerId),
      m_decisionModel (decisionModel),
      m_scheduler (m_face.getIoService ())
{
  m_rsuId = nodeName.empty () ? "rsu" : nodeName.at (-1).toUri ();
  m_dataPrefix = ndn::Name ("/ndn/data").append (m_rsuId);
}

void
NnRsu::SetDataPrefix (const ndn::Name &dataPrefix)
{
  m_dataPrefix = dataPrefix;
}

void
NnRsu::Start ()
{
  NS_LOG_INFO ("NnRsu[" << m_rsuId << "] starting, router=" << m_routerId);

  // Register the handover control prefix: /<appPrefix>/control/<routerId>
  ndn::Name ctrlPrefix = m_appPrefix;
  ctrlPrefix.append ("control");
  m_face.setInterestFilter (ctrlPrefix,
                            std::bind (&NnRsu::OnControlInterest, this, _2),
                            [] (const ndn::Name &, const std::string &reason) {
                              NS_LOG_ERROR ("RSU control filter failed: " << reason);
                            },
                            [] (const ndn::Name &) {});

  // Register the data producer prefix.
  m_face.setInterestFilter (m_dataPrefix,
                            std::bind (&NnRsu::OnDataInterest, this, _2),
                            [] (const ndn::Name &, const std::string &reason) {
                              NS_LOG_ERROR ("RSU data filter failed: " << reason);
                            },
                            [] (const ndn::Name &) {});
}

void
NnRsu::Stop ()
{
  NS_LOG_INFO ("NnRsu[" << m_rsuId << "] stopping");
}

void
NnRsu::OnControlInterest (const ndn::Interest &interest)
{
  // Name: /<appPrefix>/control/<routerId>/__veh__/<vehicleId>/<curRsu>/<tgtRsu>
  const ndn::Name &name = interest.getName ();
  NS_LOG_INFO ("NnRsu[" << m_rsuId << "] control interest: " << name);

  // Decode the feature vector from ApplicationParameters.
  std::string payload;
  payload.assign (reinterpret_cast<const char *> (interest.getApplicationParameters ().value ()),
                  interest.getApplicationParameters ().value_size ());
  VehicleMobilityInfo info = VehicleMobilityInfo::Deserialize (payload);

  if (m_decisionModel)
    {
      NnDecision decision = m_decisionModel->Decide (info);
      NS_LOG_INFO ("NnRsu[" << m_rsuId << "] NN decision for " << info.vehicleId
                            << ": choose RSU=" << decision.chosenRsuId
                            << " conf=" << decision.confidence << " (" << decision.reason << ")");

      // Forward the route hint to the common router.
      ForwardRouteHint (decision, info.vehicleId);
    }

  // Acknowledge with a small Data so the OBU knows the control was received.
  auto data = std::make_shared<ndn::Data> (name);
  std::string ack = "ok";
  data->setContent (reinterpret_cast<const uint8_t *> (ack.data ()), ack.size ());
  data->setFreshnessPeriod (ndn::time::milliseconds (1000));
  m_keyChain.sign (*data);
  m_face.put (*data);
}

void
NnRsu::OnDataInterest (const ndn::Interest &interest)
{
  // Simple producer: reply with a small payload echoing the name.
  NS_LOG_DEBUG ("NnRsu[" << m_rsuId << "] data interest: " << interest.getName ());
  auto data = std::make_shared<ndn::Data> (interest.getName ());
  std::string payload = "data-from-" + m_rsuId;
  data->setContent (reinterpret_cast<const uint8_t *> (payload.data ()), payload.size ());
  data->setFreshnessPeriod (ndn::time::milliseconds (2000));
  m_keyChain.sign (*data);
  m_face.put (*data);
}

void
NnRsu::ForwardRouteHint (const NnDecision &decision, const std::string &vehicleId)
{
  // Send a route-hint command to the common router.
  // /<appPrefix>/hint/<routerId>/__veh__/<vehicleId>/<chosenRsu>
  ndn::Name name = m_appPrefix;
  name.append ("hint");
  name.append (m_routerId);
  name.append ("__veh__");
  name.append (vehicleId);
  name.append (decision.chosenRsuId);

  ndn::Interest interest;
  interest.setName (name);
  interest.setInterestLifetime (ndn::time::milliseconds (1000));
  interest.setMustBeFresh (true);

  // carry a tiny confidence payload for logging on the router side
  std::string conf = std::to_string (decision.confidence);
  interest.setApplicationParameters (reinterpret_cast<const uint8_t *> (conf.data ()),
                                     conf.size ());

  NS_LOG_INFO ("NnRsu[" << m_rsuId << "] forwarding route hint to router " << m_routerId
                        << ": " << name);
  m_face.expressInterest (
      interest, [] (const ndn::Interest &, const ndn::Data &) {},
      [] (const ndn::Interest &, const ndn::lp::Nack &) {}, [] (const ndn::Interest &) {});
}

} // namespace nnhandover
} // namespace ns3
