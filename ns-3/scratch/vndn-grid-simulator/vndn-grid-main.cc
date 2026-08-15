#include "../vndn-map-simulator-common.h"

#include "ns3/log.h"

NS_LOG_COMPONENT_DEFINE ("vndn-grid-main");

int
main (int argc, char *argv[])
{
  ns3::ndn::VndnMapScenarioConfig scenario;
  scenario.scenarioName = "grid-vanet-test";
  scenario.routeFileName = "passenger_routes";
  scenario.sumoConfigFileName = "sim.sumocfg";
  scenario.logComponent = "vndn-grid-main";
  scenario.simulationTimeSeconds = 230;
  scenario.parkedNodeX = 300.0;
  scenario.parkedNodeY = 300.0;

  // 保留旧 grid 实验的无线传播和核心网时延参数。
  // Preserve the radio and core-network timing used by the legacy grid scenario.
  scenario.wifiTxPowerDbm = 12.0;
  scenario.wifiMinimumRssiDbm = -69.8;
  scenario.wifiSnrThresholdDb = -4.0;
  scenario.infrastructureDataRate = "50Mbps";
  scenario.rsuRouterDelay = "50ms";
  scenario.routerServerDelay = "90ms";

  // 新协议让 7 个 RSU 共用一个 router，避免跨 router 的控制 PIT 不完整。
  // All seven RSUs share one router under the new control-plane architecture.
  scenario.routerPosition = ns3::Vector (150.0, 38.28, 12.0);
  scenario.serverPosition = ns3::Vector (150.0, 50.28, 12.0);
  return ns3::ndn::RunVndnMapScenario (argc, argv, scenario);
}
