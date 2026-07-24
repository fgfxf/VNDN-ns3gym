/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#ifndef NN_RSU_APP_H
#define NN_RSU_APP_H

#include "nn-rsu.h"

#include "ns3/ndnSIM/helper/ndn-stack-helper.hpp"
#include "ns3/application.h"
#include <ns3/core-module.h>

namespace ns3 {

/**
 * @brief ns3::Application wrapper around NnRsu.
 */
class NnRsuApp : public Application
{
public:
  static TypeId
  GetTypeId ()
  {
    static TypeId tid =
        TypeId ("ns3::nnhandover::NnRsuApp")
            .SetParent<Application> ()
            .SetGroupName ("NnHandover")
            .AddConstructor<NnRsuApp> ()
            .AddAttribute ("AppPrefix", "NDN application prefix", StringValue ("/ndn/nn/handover"),
                           MakeStringAccessor (&NnRsuApp::m_appPrefix), MakeStringChecker ())
            .AddAttribute ("NodeName", "RSU node name", StringValue ("/ndn/rsu/rsu0"),
                           MakeStringAccessor (&NnRsuApp::m_nodeName), MakeStringChecker ())
            .AddAttribute ("RouterId", "Id of the common backhaul router", StringValue ("router0"),
                           MakeStringAccessor (&NnRsuApp::m_routerId), MakeStringChecker ())
            .AddAttribute ("DataPrefix", "Prefix under which this RSU produces data",
                           StringValue ("/ndn/data/rsu0"),
                           MakeStringAccessor (&NnRsuApp::m_dataPrefix), MakeStringChecker ())
            .AddAttribute ("DecisionModel", "Neural-network decision model",
                           PointerValue (nullptr),
                           MakePointerAccessor (&NnRsuApp::m_decisionModel),
                           MakePointerChecker<nnhandover::NnDecisionModel> ());
    return tid;
  }

  virtual void
  StartApplication () override
  {
    if (!m_decisionModel)
      {
        // default to the heuristic stand-in if nothing was configured
        m_decisionModel = CreateObject<nnhandover::NnHeuristicDecisionModel> ();
      }
    m_instance.reset (new nnhandover::NnRsu (ndn::Name (m_appPrefix), ndn::Name (m_nodeName),
                                             m_decisionModel, m_routerId));
    m_instance->SetDataPrefix (ndn::Name (m_dataPrefix));
    m_instance->Start ();
  }

  virtual void
  StopApplication () override
  {
    if (m_instance)
      m_instance->Stop ();
    m_instance.reset ();
  }

private:
  std::unique_ptr<nnhandover::NnRsu> m_instance;
  std::string m_appPrefix;
  std::string m_nodeName;
  std::string m_routerId;
  std::string m_dataPrefix;
  Ptr<nnhandover::NnDecisionModel> m_decisionModel;
};

} // namespace ns3

#endif // NN_RSU_APP_H
