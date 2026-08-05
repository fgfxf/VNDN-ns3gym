/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include "vndn-router.h"
#include "ns3/vndn-router-app.h"

#include "ns3/log.h"

#include <functional>
#include <stdexcept>

NS_LOG_COMPONENT_DEFINE ("ndn.VndnRouter");

namespace vanet {

VndnRouter::VndnRouter ()
{
  m_face.setInterestFilter (
      "/", std::bind (&VndnRouter::ProcessInterest, this, std::placeholders::_2),
      [] (const ndn::Name &, const std::string &reason) {
        throw std::runtime_error ("Failed to register router interest prefix: " + reason);
      });
}

void
VndnRouter::Start ()
{
  m_face.processEvents ();
  m_active = true;
  NS_LOG_INFO ("VNDN Router 启动");
}

void
VndnRouter::Stop ()
{
  NS_LOG_INFO ("VNDN Router 关闭");
  m_face.shutdown ();
  m_active = false;
}

void
VndnRouter::ProcessInterest (const ndn::Interest &interest)
{
  if (!m_active)
    {
      return;
    }

  NS_LOG_INFO ("Router 收到来自基站的兴趣请求: " << interest.getName ());
}

} // namespace vanet

namespace ns3 {
NS_OBJECT_ENSURE_REGISTERED (VndnRouterApp);
} // namespace ns3
