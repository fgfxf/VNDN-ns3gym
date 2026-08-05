/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#ifndef VNDN_ROUTER_APP_H
#define VNDN_ROUTER_APP_H

#include "ns3/application.h"
#include "ns3/vndn-router.h"

#include <memory>

namespace ns3 {

/** \brief 将 vanet::VndnRouter 包装为 ns-3 Application。 */
class VndnRouterApp : public Application
{
public:
  static TypeId
  GetTypeId ()
  {
    static TypeId tid = TypeId ("VndnRouterApp")
                            .SetParent<Application> ()
                            .AddConstructor<VndnRouterApp> ();
    return tid;
  }

private:
  void
  StartApplication () override
  {
    m_instance.reset (new vanet::VndnRouter ());
    m_instance->Start ();
  }

  void
  StopApplication () override
  {
    if (m_instance)
      {
        m_instance->Stop ();
        m_instance.reset ();
      }
  }

private:
  std::unique_ptr<vanet::VndnRouter> m_instance;
};

} // namespace ns3

#endif // VNDN_ROUTER_APP_H
