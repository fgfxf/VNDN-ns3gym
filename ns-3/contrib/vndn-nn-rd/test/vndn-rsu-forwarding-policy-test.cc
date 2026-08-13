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

class NeuralReturnSelectionTestCase : public ns3::TestCase
{
public:
  NeuralReturnSelectionTestCase ()
      : TestCase ("Neural return routing selects one or two RSUs from probability gap")
  {
  }

private:
  void
  DoRun () override
  {
    const std::vector<uint32_t> rsus = {0, 1};
    auto single = vanet::VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
        rsus, {0.8f, 0.2f}, 0.1);
    NS_TEST_EXPECT_MSG_EQ (single.size (), 1, "A clear winner must use one return path");
    NS_TEST_EXPECT_MSG_EQ (single.at (0), 0, "The highest probability RSU must win");

    auto dual = vanet::VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
        rsus, {0.47f, 0.53f}, 0.1);
    NS_TEST_EXPECT_MSG_EQ (dual.size (), 2, "A small probability gap must use two paths");
    NS_TEST_EXPECT_MSG_EQ (dual.at (0), 1, "The highest probability path is primary");
    NS_TEST_EXPECT_MSG_EQ (dual.at (1), 0, "The runner-up is the second path");

    auto invalid = vanet::VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
        rsus, {1.0f}, 0.1);
    NS_TEST_EXPECT_MSG_EQ (invalid.empty (), true,
                           "Mismatched candidates and probabilities must be rejected");
  }
};

class NeuralReturnSelectionTestSuite : public ns3::TestSuite
{
public:
  NeuralReturnSelectionTestSuite ()
      : TestSuite ("vndn-neural-return-selection", UNIT)
  {
    AddTestCase (new NeuralReturnSelectionTestCase, TestCase::QUICK);
  }
};

static VndnRsuForwardingPolicyTestSuite g_vndnRsuForwardingPolicyTestSuite;
static NeuralReturnSelectionTestSuite g_neuralReturnSelectionTestSuite;

} // namespace
