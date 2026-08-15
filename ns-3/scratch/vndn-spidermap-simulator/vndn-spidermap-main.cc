#include "../vndn-map-simulator-common.h"

#include "ns3/log.h"

NS_LOG_COMPONENT_DEFINE ("vndn-spidermap-main");

int
main (int argc, char *argv[])
{
  ns3::ndn::VndnMapScenarioConfig scenario;
  scenario.scenarioName = "fgfxf-spider-map";
  scenario.routeFileName = "passenger_routes";
  scenario.sumoConfigFileName = "sim.sumocfg";
  scenario.logComponent = "vndn-spidermap-main";
  scenario.simulationTimeSeconds = 230;
  scenario.parkedNodeX = 400.0;
  scenario.parkedNodeY = 400.0;

  // 保留旧 spidermap 实验的无线传播和核心网时延参数。
  // Preserve the radio and core-network timing used by the legacy spider map.
  scenario.wifiTxPowerDbm = 13.0;
  scenario.wifiMinimumRssiDbm = -69.8;
  scenario.wifiSnrThresholdDb = -4.0;
  scenario.infrastructureDataRate = "50Mbps";
  scenario.rsuRouterDelay = "50ms";
  scenario.routerServerDelay = "90ms";
  scenario.routerPosition = ns3::Vector (150.0, 200.0, 1.2);
  scenario.serverPosition = ns3::Vector (198.0, 116.0, 1.2);
  return ns3::ndn::RunVndnMapScenario (argc, argv, scenario);
}
