/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#ifndef VNDN_RSU_FORWARDING_POLICY_H
#define VNDN_RSU_FORWARDING_POLICY_H

#include "ns3/vector.h"

#include <cstdint>
#include <utility>
#include <vector>

namespace vanet {

/** RSU 协议代码与单元测试共用的无状态转发决策工具。 */
class VndnRsuForwardingPolicy
{
public:
  /** 返回距离车辆最近的 RSU 节点 ID；没有候选节点时返回 -1。 */
  static int64_t
  SelectNearestRsu (
      const ns3::Vector &vehiclePosition,
      const std::vector<std::pair<uint32_t, ns3::Vector>> &rsuPositions);

  /**
   * 选择概率最高的 RSU，并根据置信度决定是否同时选择第二名。
   * 当前两名概率差不大于 dualPathGap，或者第二名概率不小于
   * dualPathMinSecondProbability 时启用双路径。
   */
  static std::vector<uint32_t>
  SelectNeuralReturnRsus (const std::vector<uint32_t> &candidateRsuIds,
                          const std::vector<float> &probabilities,
                          double dualPathGap,
                          double dualPathMinSecondProbability = 1.0);
};

} // namespace vanet

#endif // VNDN_RSU_FORWARDING_POLICY_H
