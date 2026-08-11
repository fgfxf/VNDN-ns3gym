/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#ifndef VNDN_RSU_STRATEGY_H
#define VNDN_RSU_STRATEGY_H

namespace vanet {

/** RSU 在车辆离开后的回程 Data 补救策略。 */
enum RsuForwardStrategy
{
  RsuForwardStrategy_NoForward = 0,
  RsuForwardStrategy_VTDF = 1,
  RsuForwardStrategy_RealTimeVtdf = 2
};

} // namespace vanet

#endif // VNDN_RSU_STRATEGY_H
