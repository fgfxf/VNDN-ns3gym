/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#ifndef NN_ROUTER_APP_H
#define NN_ROUTER_APP_H

#include "nn-router.h"

#include "ns3/ndnSIM/helper/ndn-stack-helper.hpp"
#include "ns3/application.h"
#include <ns3/core-module.h>

#include <map>

namespace ns3 {

/**
 * @brief ns3::Application wrapper around NnRouter.
 *
 * The RSU id -> face id mapping is provided through AddRsuFace() because it
 * depends on the runtime face ids that are only known after the NDN stack is
 * installed. The example calls this after installing the stack.
 */
class NnRouterApp : public Application
{
public:
  static TypeId
  GetTypeId ()
  {
    static TypeId tid =
        TypeId ("ns3::nnhandover::NnRouterApp")
            .SetParent<Application> ()
            .SetGroupName ("NnHandover")
            .AddConstructor<NnRouterApp> ()
            .AddAttribute ("AppPrefix", "NDN application prefix", StringValue ("/ndn/nn/handover"),
                           MakeStringAccessor (&NnRouterApp::m_appPrefix), MakeStringChecker ())
            .AddAttribute ("NodeName", "Router node name", StringValue ("/ndn/router/router0"),
                           MakeStringAccessor (&NnRouterApp::m_nodeName), MakeStringChecker ())
            .AddAttribute ("DecisionModel", "Neural-network decision model",
                           PointerValue (nullptr),
                           MakePointerAccessor (&NnRouterApp::m_decisionModel),
                           MakePointerChecker<nnhandover::NnDecisionModel> ());
    return tid;
  }

  /// Register a mapping: RSU id -> face id on this router.
  void
  AddRsuFace (const std::string &rsuId, uint64_t faceId)
  {
    m_rsuFaceMap[rsuId] = faceId;
    if (m_instance)
      m_instance->AddRsuFace (rsuId, faceId);
  }

  virtual void
  StartApplication () override
  {
    if (!m_decisionModel)
      m_decisionModel = CreateObject<nnhandover::NnHeuristicDecisionModel> ();
    m_instance.reset (new nnhandover::NnRouter (ndn::Name (m_appPrefix), ndn::Name (m_nodeName),
                                                m_decisionModel));
    for (const auto &kv : m_rsuFaceMap)
      m_instance->AddRsuFace (kv.first, kv.second);
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
  std::unique_ptr<nnhandover::NnRouter> m_instance;
  std::string m_appPrefix;
  std::string m_nodeName;
  Ptr<nnhandover::NnDecisionModel> m_decisionModel;
  std::map<std::string, uint64_t> m_rsuFaceMap;
};

} // namespace ns3

#endif // NN_ROUTER_APP_H
