/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include "ns3/test.h"
#include "ns3/vndn-rsu-forwarding-policy.h"

namespace {

class NearestRsuSelectionTestCase : public ns3::TestCase
{
public:
  NearestRsuSelectionTestCase ()
      : TestCase ("RealTimeVTDF selects the RSU nearest to the live vehicle position")
  {
  }

private:
  void
  DoRun () override
  {
    const std::vector<std::pair<uint32_t, ns3::Vector>> rsus = {
        {0, ns3::Vector (-20.0, 70.0, 20.0)},
        {1, ns3::Vector (150.0, 70.0, 20.0)}};

    NS_TEST_EXPECT_MSG_EQ (
        vanet::VndnRsuForwardingPolicy::SelectNearestRsu (
            ns3::Vector (59.0, 141.0, 1.2), rsus),
        0, "The handover position near RSU 0 must select RSU 0");
    NS_TEST_EXPECT_MSG_EQ (
        vanet::VndnRsuForwardingPolicy::SelectNearestRsu (
            ns3::Vector (72.0, 0.0, 1.2), rsus),
        1, "The handover position near RSU 1 must select RSU 1");
    NS_TEST_EXPECT_MSG_EQ (
        vanet::VndnRsuForwardingPolicy::SelectNearestRsu (
            ns3::Vector (), {}),
        -1, "An empty candidate set must not invent an RSU");
  }
};

class VndnRsuForwardingPolicyTestSuite : public ns3::TestSuite
{
public:
  VndnRsuForwardingPolicyTestSuite ()
      : TestSuite ("vndn-rsu-forwarding-policy", UNIT)
  {
    AddTestCase (new NearestRsuSelectionTestCase, TestCase::QUICK);
  }
};

static VndnRsuForwardingPolicyTestSuite g_vndnRsuForwardingPolicyTestSuite;

} // namespace
