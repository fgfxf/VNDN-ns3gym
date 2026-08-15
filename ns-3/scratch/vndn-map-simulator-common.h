/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-map-simulator-common.h
 * \brief grid 与 spidermap 共用的 VNDN/SUMO 仿真运行骨架。
 *
 * 两个场景的协议栈、应用、统计输出和命令行参数必须保持一致，只有路网、
 * 无线范围以及固定基础设施的位置/链路参数不同。把公共流程集中在这里可防止
 * 后续修复只落到其中一个场景。circle 暂时保持原文件不变，以免影响现有实验。
 */

#ifndef VNDN_MAP_SIMULATOR_COMMON_H
#define VNDN_MAP_SIMULATOR_COMMON_H

#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/ndnSIM-module.h"
#include "ns3/netanim-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/traci-module.h"
#include "ns3/wifi-module.h"

#include "ns3/vndn-obu-app.h"
#include "ns3/vndn-pcap-writer.h"
#include "ns3/vndn-router-app.h"
#include "ns3/vndn-rsu-app.h"
#include "ns3/vndn-rsu-strategy.h"
#include "ns3/vndn-utils-helper.h"
#include "ns3/wifi-adhoc-helper.h"
#include "ns3/wifi-setup-helper.h"

#include <cstdlib>
#include <ctime>
#include <functional>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace ns3 {
namespace ndn {

/** 只保存地形相关参数；协议和数据采集逻辑在两个场景之间完全复用。 */
struct VndnMapScenarioConfig
{
  std::string scenarioName;
  std::string routeFileName;
  std::string sumoConfigFileName;
  std::string logComponent;
  uint32_t simulationTimeSeconds;
  double parkedNodeX;
  double parkedNodeY;
  double wifiTxPowerDbm;
  double wifiMinimumRssiDbm;
  double wifiSnrThresholdDb;
  std::string infrastructureDataRate;
  std::string rsuRouterDelay;
  std::string routerServerDelay;
  Vector routerPosition;
  Vector serverPosition;

  VndnMapScenarioConfig ()
      : simulationTimeSeconds (230)
      , parkedNodeX (400.0)
      , parkedNodeY (400.0)
      , wifiTxPowerDbm (13.0)
      , wifiMinimumRssiDbm (-69.8)
      , wifiSnrThresholdDb (-4.0)
      , infrastructureDataRate ("50Mbps")
      , rsuRouterDelay ("50ms")
      , routerServerDelay ("90ms")
      , routerPosition (0.0, 0.0, 1.2)
      , serverPosition (0.0, 0.0, 1.2)
  {
  }
};

inline const char *
GetRsuForwardStrategyName (vanet::RsuForwardStrategy strategy)
{
  switch (strategy)
    {
    case vanet::RsuForwardStrategy_VTDF:
      return "VTDF";
    case vanet::RsuForwardStrategy_RealTimeVtdf:
      return "RealTimeVTDF";
    case vanet::RsuForwardStrategy_NeuralNetwork:
      return "NeuralNetwork";
    case vanet::RsuForwardStrategy_NoForward:
    default:
      return "NoForward";
    }
}

/**
 * 运行一个地图型 VNDN 场景。
 *
 * 新协议通过 router 中继 /vndn/control 报文，所以这里不会恢复旧代码中的
 * RSU--RSU 专用 P2P 旁路。所有 RSU 接到同一个 router，可确保 VTDF、RTVTDF
 * 和神经网络双路径共用同一套、已经在 circle 中验证过的回程逻辑。
 */
inline int
RunVndnMapScenario (int argc, char *argv[], const VndnMapScenarioConfig &scenario)
{
  const std::vector<Vector> rsuLocations =
      VndnUtilsHelper::GetRsuLocations (VndnUtilsHelper::ndn4ivc_traces_folder,
                                        scenario.scenarioName);
  if (rsuLocations.empty ())
    {
      std::cerr << "No RSU location found for scenario " << scenario.scenarioName
                << std::endl;
      return 2;
    }

  const uint32_t nVehicles =
      VndnUtilsHelper::GetVehicleCount (VndnUtilsHelper::ndn4ivc_traces_folder,
                                        scenario.scenarioName,
                                        scenario.routeFileName);
  if (nVehicles == 0)
    {
      std::cerr << "No vehicle found for scenario " << scenario.scenarioName << std::endl;
      return 2;
    }
  const uint32_t nRsus = static_cast<uint32_t> (rsuLocations.size ());

  uint32_t ndnIntervalMs = 1;
  uint32_t simulationTime = scenario.simulationTimeSeconds;
  bool enablePcap = false;
  bool enableLog = true;
  bool enableSumoGui = false;
  bool enableDataSave = true;
  uint32_t srandSeed = static_cast<uint32_t> (::time (nullptr));
  int sumoSeed = rand ();
  uint32_t openGymPort = 5555;
  vanet::CacheStrategy cacheStrategy = vanet::CacheStrategy_Participate;
  vanet::HandoverStrategy handoverStrategy = vanet::HandoverStrategy_Immediate;
  // 新地形尚未训练专用模型，默认 NoForward 可直接运行；需要神经网络时显式选 3。
  vanet::RsuForwardStrategy rsuForwardStrategy =
      vanet::RsuForwardStrategy_NoForward;
  uint32_t rsuForwardStrategyValue =
      static_cast<uint32_t> (rsuForwardStrategy);
  bool handoverFrequencyBoost = false;
  double obuFrequency = 40.0;
  double handoverFrequencyMultiplier = 4.0;

  CommandLine commandLine;
  commandLine.AddValue ("i", "Interest interval (milliseconds)", ndnIntervalMs);
  commandLine.AddValue ("s", "Simulation time (seconds)", simulationTime);
  commandLine.AddValue ("pcap", "Enable PCAP", enablePcap);
  commandLine.AddValue ("log", "Enable Log", enableLog);
  commandLine.AddValue ("sumo-gui", "Enable SUMO graphical interface", enableSumoGui);
  commandLine.AddValue ("save-data", "Enable simulation data output", enableDataSave);
  commandLine.AddValue ("sumo-seed", "SUMO random seed", sumoSeed);
  commandLine.AddValue ("srand-seed", "C rand() random seed", srandSeed);
  commandLine.AddValue ("open-gym-port", "Shared ns3-gym port", openGymPort);
  commandLine.AddValue (
      "rsu-forward-strategy",
      "RSU return strategy: 0=NoForward, 1=VTDF, 2=RealTimeVTDF, 3=NeuralNetwork",
      rsuForwardStrategyValue);
  commandLine.AddValue (
      "handover-frequency-boost",
      "Increase OBU request frequency when at least two RSUs are visible",
      handoverFrequencyBoost);
  commandLine.AddValue ("obu-frequency", "Normal OBU Interest frequency in Hz",
                        obuFrequency);
  commandLine.AddValue ("handover-frequency-multiplier",
                        "OBU frequency multiplier in handover areas",
                        handoverFrequencyMultiplier);
  commandLine.Parse (argc, argv);

  if (rsuForwardStrategyValue > 3)
    {
      std::cerr << "Invalid --rsu-forward-strategy value: "
                << rsuForwardStrategyValue << std::endl;
      return 2;
    }
  rsuForwardStrategy =
      static_cast<vanet::RsuForwardStrategy> (rsuForwardStrategyValue);
  // 用户给出的 srand 种子必须在仿真中首次实际使用 rand() 之前生效。
  srand (srandSeed);

  std::time_t now = std::time (nullptr);
  std::tm *localNow = std::localtime (&now);
  std::ostringstream dateDirectory;
  std::ostringstream timeDirectory;
  dateDirectory << std::put_time (localNow, "%Y%m%d");
  timeDirectory << std::put_time (localNow, "%H-%M-%S");
  const std::string outputDirectory =
      "./data/" + scenario.scenarioName + "/" + dateDirectory.str () + "/" +
      timeDirectory.str () + "/";
  const std::string aiTrainingDirectory = outputDirectory + "ai-training/";
  const std::string aiTrainingFile = aiTrainingDirectory + "training-tag.csv";
  const std::string l3RateTracerFile = outputDirectory + "l3-rate-tracer.txt";
  const std::string csTracerFile = outputDirectory + "cs-tracer.txt";
  const std::string netAnimFile = outputDirectory + "netanim-animation.xml";
  const std::string wifiPcapPrefix = outputDirectory + "ndn-trace";
  const std::string p2pPcapFile = outputDirectory + "ndn-trace.pcap";

  if (enableLog)
    {
      const std::vector<std::string> logComponents = {
          scenario.logComponent, "ndn.VndnObu", "ndn.VndnRsu", "ndn.VndnRouter"};
      for (const std::string &component : logComponents)
        {
          LogComponentEnable (component.c_str (), LOG_LEVEL_ALL);
          LogComponentEnable (component.c_str (), LOG_PREFIX_ALL);
        }
    }

  if (enableLog || enableDataSave || enablePcap)
    {
      if (std::system (("mkdir -p " + aiTrainingDirectory).c_str ()) != 0)
        std::cerr << "Warning: cannot create " << aiTrainingDirectory << std::endl;

      const char *cacheStrategyName =
          cacheStrategy == vanet::CacheStrategy_Participate ? "Participate" : "None";
      const char *handoverStrategyName =
          handoverStrategy == vanet::HandoverStrategy_Immediate ? "Immediate"
                                                                : "AntiPingPong";
      std::ostringstream obuFrequencyText;
      obuFrequencyText << obuFrequency;
      const std::vector<std::pair<std::string, std::string>> parameters = {
          {"CacheStrategy", cacheStrategyName},
          {"HandoverStrategy", handoverStrategyName},
          {"obuFrequency", obuFrequencyText.str ()},
          {"RsuForwardStrategy", GetRsuForwardStrategyName (rsuForwardStrategy)},
          {"OpenGymPort", std::to_string (openGymPort)},
          {"SumoSeed", std::to_string (sumoSeed)},
          {"SrandSeed", std::to_string (srandSeed)}};
      if (!VndnUtilsHelper::SaveSimulationConfig (outputDirectory, parameters))
        std::cerr << "Warning: cannot save " << outputDirectory
                  << "simulation-config.txt" << std::endl;
      std::cout << "Log and data output directory: " << outputDirectory << std::endl;
    }

  std::cout << "# nodes (vehicles) detected in SUMO scenario: " << nVehicles
            << std::endl;
  std::cout << "# Road Side Units (RSUs): " << nRsus << std::endl;

  NodeContainer nodePool;
  nodePool.Create (nVehicles + nRsus);
  NodeContainer routerNodes;
  routerNodes.Create (1);
  NodeContainer serverNodes;
  serverNodes.Create (1);

  WifiSetupHelper wifi;
  wifi.SetTxPower (scenario.wifiTxPowerDbm);
  wifi.SetMiniRssi (scenario.wifiMinimumRssiDbm);
  wifi.SetSnr (scenario.wifiSnrThresholdDb);
  wifi.ConfigureDevices (nodePool, enablePcap, wifiPcapPrefix);

  PointToPointHelper pointToPoint;
  pointToPoint.SetDeviceAttribute ("DataRate",
                                   StringValue (scenario.infrastructureDataRate));
  pointToPoint.SetChannelAttribute ("Delay", StringValue (scenario.rsuRouterDelay));
  for (uint32_t rsuIndex = 0; rsuIndex < nRsus; ++rsuIndex)
    pointToPoint.Install (nodePool.Get (rsuIndex), routerNodes.Get (0));
  pointToPoint.SetChannelAttribute ("Delay", StringValue (scenario.routerServerDelay));
  pointToPoint.Install (routerNodes.Get (0), serverNodes.Get (0));

  std::cout << BLUE_CODE << "安装 NDN 协议栈..." << END_CODE << std::endl;
  StackHelper stackHelper;
  stackHelper.AddFaceCreateCallback (WifiNetDevice::GetTypeId (),
                                     MakeCallback (FixLinkTypeAdhocCb));
  stackHelper.setCsSize (10);
  stackHelper.InstallAll ();
  StrategyChoiceHelper::Install (nodePool, "/",
                                 "/localhost/nfd/strategy/vndn-multicast");

  MobilityHelper mobility;
  Ptr<UniformDiscPositionAllocator> parkedPosition =
      CreateObject<UniformDiscPositionAllocator> ();
  parkedPosition->SetX (scenario.parkedNodeX + (rand () % 10));
  parkedPosition->SetY (scenario.parkedNodeY + (rand () % 10));
  parkedPosition->SetZ (1.2);
  parkedPosition->SetRho (10.0);
  mobility.SetPositionAllocator (parkedPosition);
  mobility.SetMobilityModel ("ns3::ConstantPositionMobilityModel");
  mobility.Install (nodePool);
  mobility.Install (routerNodes);
  mobility.Install (serverNodes);

  Ptr<TraciClient> sumoClient = CreateObject<TraciClient> ();
  const std::string sumoConfigPath =
      VndnUtilsHelper::ndn4ivc_traces_folder + "/" + scenario.scenarioName + "/" +
      scenario.sumoConfigFileName;
  sumoClient->SetAttribute ("SumoConfigPath", StringValue (sumoConfigPath));
  sumoClient->SetAttribute ("SumoBinaryPath", StringValue (""));
  sumoClient->SetAttribute ("SynchInterval", TimeValue (MilliSeconds (ndnIntervalMs)));
  sumoClient->SetAttribute ("StartTime", TimeValue (Seconds (0.0)));
  sumoClient->SetAttribute ("SumoGUI", BooleanValue (enableSumoGui));
  sumoClient->SetAttribute ("SumoPort", UintegerValue (3400));
  sumoClient->SetAttribute ("PenetrationRate", DoubleValue (1.0));
  sumoClient->SetAttribute ("SumoLogFile", BooleanValue (false));
  sumoClient->SetAttribute ("SumoStepLog", BooleanValue (false));
  sumoClient->SetAttribute ("SumoSeed", IntegerValue (sumoSeed));
  sumoClient->SetAttribute ("SumoAdditionalCmdOptions", StringValue ("--verbose true"));
  sumoClient->SetAttribute ("SumoWaitForSocket", TimeValue (Seconds (2.0)));

  uint32_t usedNodeCounter = 0;
  std::function<Ptr<Node> ()> setupNewNode = [&] () -> Ptr<Node> {
    if (usedNodeCounter >= nodePool.GetN ())
      NS_FATAL_ERROR ("Node pool empty: " << usedNodeCounter << " nodes created");
    Ptr<Node> node = nodePool.Get (usedNodeCounter++);
    Ptr<VndnObuApp> obu = CreateObject<VndnObuApp> ();
    obu->SetAttribute ("SumoClient", PointerValue (sumoClient));
    obu->SetAttribute ("Frequency", DoubleValue (obuFrequency));
    obu->SetAttribute ("HandoverFrequencyBoost", BooleanValue (handoverFrequencyBoost));
    obu->SetAttribute ("HandoverFrequencyMultiplier",
                       DoubleValue (handoverFrequencyMultiplier));
    obu->SetAttribute ("EnableDataSave", BooleanValue (enableDataSave));
    obu->SetAttribute ("SaveFile", StringValue (aiTrainingFile));
    obu->SetAttribute ("CacheStrategy", EnumValue (cacheStrategy));
    obu->SetAttribute ("HandoverStrategy", EnumValue (handoverStrategy));
    node->AddApplication (obu);

    const Time stopDelay =
        Seconds (simulationTime) - Simulator::Now () - NanoSeconds (1);
    if (stopDelay.IsPositive ())
      Simulator::ScheduleWithContext (node->GetId (), stopDelay,
                                      &VndnObuApp::StopApplication, obu);
    return node;
  };

  std::function<void (Ptr<Node>)> shutdownSumoNode = [&] (Ptr<Node> node) {
    Ptr<VndnObuApp> obu = DynamicCast<VndnObuApp> (node->GetApplication (0));
    if (obu != nullptr)
      obu->StopApplication ();
    for (uint32_t deviceIndex = 0; deviceIndex < node->GetNDevices (); ++deviceIndex)
      {
        Ptr<WifiNetDevice> wifiDevice =
            node->GetDevice (deviceIndex)->GetObject<WifiNetDevice> ();
        if (wifiDevice != nullptr)
          wifiDevice->GetPhy ()->SetOffMode ();
      }
    VndnUtilsHelper::nodesDisable2Move.emplace (
        node->GetId (), static_cast<Time> (Simulator::Now ().GetSeconds ()));
  };

  ApplicationContainer rsuApplications;
  AppHelper rsuHelper ("VndnRsuApp");
  rsuHelper.SetAttribute ("SumoClient", PointerValue (sumoClient));
  rsuHelper.SetAttribute ("RsuForwardStrategy", EnumValue (rsuForwardStrategy));
  rsuHelper.SetAttribute ("OpenGymPort", UintegerValue (openGymPort));
  for (uint32_t rsuIndex = 0; rsuIndex < nRsus; ++rsuIndex)
    {
      nodePool.Get (usedNodeCounter)->GetObject<MobilityModel> ()->SetPosition (
          rsuLocations.at (rsuIndex));
      rsuApplications.Add (rsuHelper.Install (nodePool.Get (usedNodeCounter)));
      ++usedNodeCounter;
    }

  serverNodes.Get (0)->GetObject<MobilityModel> ()->SetPosition (
      scenario.serverPosition);
  AppHelper producerHelper ("ns3::ndn::Producer");
  producerHelper.SetPrefix ("/com/baidu");
  producerHelper.SetAttribute ("PayloadSize", StringValue ("10240"));
  ApplicationContainer producerApplication = producerHelper.Install (serverNodes.Get (0));
  producerApplication.Start (Seconds (0.0));

  routerNodes.Get (0)->GetObject<MobilityModel> ()->SetPosition (
      scenario.routerPosition);
  AppHelper routerHelper ("VndnRouterApp");
  ApplicationContainer routerApplication = routerHelper.Install (routerNodes.Get (0));
  routerApplication.Start (Seconds (0.0));

  const Time applicationStopTime = Seconds (simulationTime) - NanoSeconds (1);
  for (uint32_t index = 0; index < rsuApplications.GetN (); ++index)
    {
      Ptr<VndnRsuApp> app = DynamicCast<VndnRsuApp> (rsuApplications.Get (index));
      Simulator::ScheduleWithContext (app->GetNode ()->GetId (), applicationStopTime,
                                      &VndnRsuApp::StopApplication, app);
    }
  routerApplication.Stop (applicationStopTime);
  producerApplication.Stop (applicationStopTime);

  for (uint32_t rsuIndex = 0; rsuIndex < nRsus; ++rsuIndex)
    FibHelper::AddRoute (nodePool.Get (rsuIndex), "/", routerNodes.Get (0), 15);
  FibHelper::AddRoute (routerNodes.Get (0), "/", serverNodes.Get (0), 15);

  Config::Set ("/NodeList/*/DeviceList/*/$ns3::WifiNetDevice/Phy/ChannelNumber",
               UintegerValue (SCH1));
  sumoClient->SumoSetup (setupNewNode, shutdownSumoNode);
  VndnUtilsHelper::ScheduleDisableNodesCheck ();

  std::unique_ptr<AnimationInterface> animation;
  std::unique_ptr<VndnPcapWriter> pcapWriter;
  if (enableDataSave)
    {
      L3RateTracer::InstallAll (l3RateTracerFile, Seconds (1.0));
      CsTracer::InstallAll (csTracerFile, Seconds (1.0));
      animation.reset (new AnimationInterface (netAnimFile));
    }
  if (enablePcap)
    {
      pcapWriter.reset (new VndnPcapWriter (p2pPcapFile));
      Config::ConnectWithoutContext (
          "/NodeList/*/DeviceList/*/$ns3::PointToPointNetDevice/MacTx",
          MakeCallback (&VndnPcapWriter::TracePacket, pcapWriter.get ()));
    }

  Simulator::Stop (Seconds (simulationTime));
  Simulator::Run ();
  Simulator::Destroy ();
  return 0;
}

} // namespace ndn
} // namespace ns3

#endif // VNDN_MAP_SIMULATOR_COMMON_H
