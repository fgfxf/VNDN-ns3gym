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
      : TestCase ("Neural return routing selects one or two RSUs from probability confidence")
  {
  }

private:
  void
  DoRun () override
  {
    const std::vector<uint32_t> rsus = {0, 1};
    // 第二名只有 0.04，既不接近第一名，也未达到最低可信度，应单路径。
    auto single = vanet::VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
        rsus, {0.96f, 0.04f}, 0.1, 0.1);
    NS_TEST_EXPECT_MSG_EQ (single.size (), 1, "A clear winner must use one return path");
    NS_TEST_EXPECT_MSG_EQ (single.at (0), 0, "The highest probability RSU must win");

    // 前两名概率差仅 0.06，即使排序相反也必须保留两个候选 RSU。
    auto dual = vanet::VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
        rsus, {0.47f, 0.53f}, 0.1, 0.1);
    NS_TEST_EXPECT_MSG_EQ (dual.size (), 2, "A small probability gap must use two paths");
    NS_TEST_EXPECT_MSG_EQ (dual.at (0), 1, "The highest probability path is primary");
    NS_TEST_EXPECT_MSG_EQ (dual.at (1), 0, "The runner-up is the second path");

    // 第二名达到 0.22；虽然与第一名相差较大，仍按放宽后的规则双路径。
    auto relaxedDual = vanet::VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
        rsus, {0.78f, 0.22f}, 0.1, 0.1);
    NS_TEST_EXPECT_MSG_EQ (
        relaxedDual.size (), 2,
        "A runner-up probability outside the 0.0x range must use two paths");

    // 明确验证用户所说的“0.0x”：第二名 0.09 且差值大时保持单路径。
    auto lowRunnerUp = vanet::VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
        rsus, {0.91f, 0.09f}, 0.1, 0.1);
    NS_TEST_EXPECT_MSG_EQ (
        lowRunnerUp.size (), 1,
        "A 0.0x runner-up with a large gap must keep one path");

    auto invalid = vanet::VndnRsuForwardingPolicy::SelectNeuralReturnRsus (
        rsus, {1.0f}, 0.1, 0.1);
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
