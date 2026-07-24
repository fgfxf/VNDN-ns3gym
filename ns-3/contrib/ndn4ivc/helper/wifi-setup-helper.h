#ifndef WIFISETUPHELPER_SETUP_H
#define WIFISETUPHELPER_SETUP_H
#include "ns3/core-module.h"
#include "ns3/wave-module.h"
#include "ns3/network-module.h"

namespace ns3 {
namespace ndn {
/** \brief This is a "utility class".
 */
class WifiSetupHelper
{
public:
  WifiSetupHelper ();
  virtual ~WifiSetupHelper ();

  // set function
  void SetTxPower (double power);
  void SetMinDistance (double distance);
  void SetMiniRssi (double rssi);
  void SetSnr (double snr);

  NetDeviceContainer ConfigureDevices (NodeContainer &n, bool enableLog);

private:
  /** Propagationa = TwoRayGroundPropagationLossModel && ConstantSpeedPropagationDelayModel***
  * 21dBm ~ 75m (radio coverage)
  * 33.8dbm ~ 200m  (radio coverage)
  * 45.6dbm~ 500m  (radio coverage)
  */
  double m_txPower_dBm = 45.6;   // dBm    //默认45.6 ~500米
  double m_MinDistance = 50;     // 低于这个距离可以认为绝对可以收到信号，因为自由空间衰减公式适用于50～1000m
  double m_MinimumRssi = -106;   // 最低信号检测
  double m_snr = 4.0;
  std::string phyMode = "OfdmRate6MbpsBW10MHz";
};
} // namespace ndn
} // namespace ns3
#endif