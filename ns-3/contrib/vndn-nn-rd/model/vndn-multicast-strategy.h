#ifndef VNDN_MULTICAST_STRATEGY_H
#define VNDN_MULTICAST_STRATEGY_H

#include "face/face.hpp"
#include "fw/strategy.hpp"
#include "fw/algorithm.hpp"
#include "fw/retx-suppression-exponential.hpp"

namespace nfd {
namespace fw {

/** @brief 基于 MulticastVanetStrategy 的 VANET 组播策略，
 *         额外对 /vndn/control 前缀的控制包（如基站同步信号）跳过重传抑制，
 *         使其每次到达都能转发给上层 app。
 */
class VndnMulticastStrategy : public Strategy
{
public:
  explicit VndnMulticastStrategy (Forwarder &forwarder, const Name &name = getStrategyName ());

  static const Name &getStrategyName ();

  void afterReceiveInterest (const FaceEndpoint &ingress, const Interest &interest,
                             const shared_ptr<pit::Entry> &pitEntry) override;

private:
  RetxSuppressionExponential m_retxSuppression;
  static const time::milliseconds RETX_SUPPRESSION_INITIAL;
  static const time::milliseconds RETX_SUPPRESSION_MAX;
};

} // namespace fw
} // namespace nfd

#endif // VNDN_MULTICAST_STRATEGY_H
