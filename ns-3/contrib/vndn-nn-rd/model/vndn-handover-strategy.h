/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-handover-strategy.h
 * \brief OBU 基站驻留切换策略枚举。
 *
 * 仿真时可选择是否启用"防止 ping-pong 切换"策略：
 *   - HandoverStrategy_Immediate：信号强度大于当前驻留基站即立即切换
 *   - HandoverStrategy_AntiPingPong：新基站信号强于当前驻留基站，
 *     且距离上次驻留切换时间大于阈值（默认 20ms）时才切换
 */

#ifndef VNDN_HANDOVER_STRATEGY_H
#define VNDN_HANDOVER_STRATEGY_H

namespace vanet {

/**
 * \brief 基站驻留切换策略枚举。
 */
enum HandoverStrategy {
  HandoverStrategy_Immediate = 0,    ///< 立即切换：信号强度优于当前驻留基站即切换
  HandoverStrategy_AntiPingPong = 1  ///< 防止 ping-pong 切换：需满足信号强度与时间阈值
};

} // namespace vanet

#endif // VNDN_HANDOVER_STRATEGY_H
