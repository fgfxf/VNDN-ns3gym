/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

#ifndef NN_OBU_APP_H
#define NN_OBU_APP_H

#include "nn-obu.h"

#include "ns3/ndnSIM/helper/ndn-stack-helper.hpp"
#include "ns3/application.h"
#include <ns3/core-module.h>

#include <vector>

namespace ns3 {

/**
 * @brief ns3::Application wrapper around NnObu.
 *
 * Mirrors the ItsCarApp pattern from ndn4ivc: a thin Application that owns a
 * unique_ptr to the NDN application object and configures it from ns-3
 * attributes. The list of RSUs is provided through a helper setter because
 * ns-3 attributes cannot easily carry a vector of custom structs.
 */
class NnObuApp : public Application
{
public:
  static TypeId
  GetTypeId ()
  {
    static TypeId tid =
        TypeId ("ns3::nnhandover::NnObuApp")
            .SetParent<Application> ()
            .SetGroupName ("NnHandover")
            .AddConstructor<NnObuApp> ()
            .AddAttribute ("AppPrefix", "NDN application prefix", StringValue ("/ndn/nn/handover"),
                           MakeStringAccessor (&NnObuApp::m_appPrefix), MakeStringChecker ())
            .AddAttribute ("NodeName", "Vehicle node name", StringValue ("/ndn/vehicle/car_0"),
                           MakeStringAccessor (&NnObuApp::m_nodeName), MakeStringChecker ())
            .AddAttribute ("RouterId", "Id of the common backhaul router", StringValue ("router0"),
                           MakeStringAccessor (&NnObuApp::m_routerId), MakeStringChecker ())
            .AddAttribute ("SampleIntervalMs", "Mobility sampling interval (ms)",
                           UintegerValue (500),
                           MakeUintegerAccessor (&NnObuApp::m_sampleIntervalMs),
                           MakeUintegerChecker<uint32_t> ());
    return tid;
  }

  /// Provide the list of RSUs the OBU may hand over between.
  void
  SetRsuList (const std::vector<nnhandover::RsuEntry> &rsus)
  {
    m_rsus = rsus;
  }

  virtual void
  StartApplication () override
  {
    m_instance.reset (new nnhandover::NnObu (ndn::Name (m_appPrefix), ndn::Name (m_nodeName),
                                             m_routerId, m_rsus));
    m_instance->SetSampleIntervalMs (m_sampleIntervalMs);
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
  std::unique_ptr<nnhandover::NnObu> m_instance;
  std::string m_appPrefix;
  std::string m_nodeName;
  std::string m_routerId;
  uint32_t m_sampleIntervalMs = 500;
  std::vector<nnhandover::RsuEntry> m_rsus;
};

} // namespace ns3

#endif // NN_OBU_APP_H
