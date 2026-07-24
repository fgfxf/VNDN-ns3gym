/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */

// Neural-Network assisted NDN Interest routing for vehicular RSU handover.
//
// Topology:
//
//   OBU (vehicle, moving)  --wifi--  RSU0  --p2p--  Router  --p2p--  RSU1
//                                   \________________wifi________________/
//
// The vehicle moves on a straight line from RSU0 towards RSU1. As it crosses
// the midpoint, the OBU detects the handover (the best RSU changes) and sends
// a control Interest to the common Router. The Router runs the (heuristic)
// neural-network decision model and installs a per-vehicle route hint into the
// NnRoutingStrategy, so that subsequent Data for that vehicle is forwarded
// through the new RSU.
//
// Run:
//   ./waf --run nn-handover-example
//   NS_LOG=ndn.NnObu:ndn.NnRouter:ndn.NnRoutingStrategy ./waf --run nn-handover-example

#include "ns3/nn-obu-app.h"
#include "ns3/nn-rsu-app.h"
#include "ns3/nn-router-app.h"
#include "ns3/nn-decision-model.h"

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/mobility-module.h"
#include "ns3/wifi-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/ndnSIM-module.h"

#include "ns3/ndnSIM/model/ndn-l3-protocol.hpp"

#include <ns3/log.h>

#include <iostream>

namespace ns3 {

NS_LOG_COMPONENT_DEFINE ("nn-handover-example");

// Helper: get the NDN face id that corresponds to a given NetDevice on a node.
static uint64_t
GetFaceIdForNetDevice (Ptr<Node> node, Ptr<NetDevice> dev)
{
  auto l3 = node->GetObject<ndn::L3Protocol> ();
  auto face = l3->getFaceByNetDevice (dev);
  return face ? face->getId () : 0;
}

int
main (int argc, char *argv[])
{
  bool enableLog = true;
  double simTime = 30.0;
  CommandLine cmd;
  cmd.AddValue ("log", "Enable logging", enableLog);
  cmd.AddValue ("s", "Simulation time (seconds)", simTime);
  cmd.Parse (argc, argv);

  if (enableLog)
    {
      LogComponentEnable ("nn-handover-example", LOG_LEVEL_INFO);
      LogComponentEnable ("ndn.NnObu", LOG_LEVEL_INFO);
      LogComponentEnable ("ndn.NnRsu", LOG_LEVEL_INFO);
      LogComponentEnable ("ndn.NnRouter", LOG_LEVEL_INFO);
      LogComponentEnable ("ndn.NnRoutingStrategy", LOG_LEVEL_INFO);
      LogComponentEnable ("ndn.NnDecisionModel", LOG_LEVEL_INFO);
    }

  std::cout << "=== NN-assisted NDN handover example ===" << std::endl;

  // ---- Nodes -------------------------------------------------------------
  // 0: OBU (vehicle), 1: RSU0, 2: Router, 3: RSU1
  NodeContainer nodes;
  nodes.Create (4);
  Ptr<Node> obu = nodes.Get (0);
  Ptr<Node> rsu0 = nodes.Get (1);
  Ptr<Node> router = nodes.Get (2);
  Ptr<Node> rsu1 = nodes.Get (3);

  // ---- Wired links: RSU0 -- Router -- RSU1 -------------------------------
  Config::SetDefault ("ns3::PointToPointNetDevice::DataRate", StringValue ("10Mbps"));
  Config::SetDefault ("ns3::PointToPointChannel::Delay", StringValue ("2ms"));

  PointToPointHelper p2p;
  NetDeviceContainer rsu0RouterDev = p2p.Install (rsu0, router);
  NetDeviceContainer routerRsu1Dev = p2p.Install (router, rsu1);

  // ---- Wireless link: OBU <-> RSU0, OBU <-> RSU1 -------------------------
  // We use one shared wifi channel so the OBU can talk to both RSUs.
  WifiHelper wifi;
  wifi.SetStandard (WIFI_STANDARD_80211p);

  YansWifiPhyHelper wifiPhy;
  YansWifiChannelHelper wifiChannel = YansWifiChannelHelper::Default ();
  wifiPhy.SetChannel (wifiChannel.Create ());

  WifiMacHelper wifiMac;
  wifiMac.SetType ("ns3::AdhocWifiMac");

  wifi.SetRemoteStationManager ("ns3::ConstantRateWifiManager", "DataMode",
                                StringValue ("OfdmRate6MbpsBW10MHz"));

  // OBU has one wifi device.
  NetDeviceContainer obuDev = wifi.Install (wifiPhy, wifiMac, obu);
  // Each RSU has one wifi device on the same channel.
  NetDeviceContainer rsu0WifiDev = wifi.Install (wifiPhy, wifiMac, rsu0);
  NetDeviceContainer rsu1WifiDev = wifi.Install (wifiPhy, wifiMac, rsu1);

  // ---- Mobility ----------------------------------------------------------
  // RSU0 at x=0, RSU1 at x=200, both fixed. Router fixed at x=100 (height).
  MobilityHelper mob;
  mob.SetMobilityModel ("ns3::ConstantPositionMobilityModel");
  mob.Install (rsu0);
  mob.Install (rsu1);
  mob.Install (router);
  rsu0->GetObject<MobilityModel> ()->SetPosition (Vector (0.0, 0.0, 5.0));
  rsu1->GetObject<MobilityModel> ()->SetPosition (Vector (200.0, 0.0, 5.0));
  router->GetObject<MobilityModel> ()->SetPosition (Vector (100.0, 50.0, 0.0));

  // OBU moves from x=-20 to x=220 along y=0 at 10 m/s -> crosses midpoint at t~12s.
  mob.SetMobilityModel ("ns3::ConstantVelocityMobilityModel");
  mob.Install (obu);
  obu->GetObject<MobilityModel> ()->SetPosition (Vector (-20.0, 0.0, 1.5));
  obu->GetObject<ConstantVelocityMobilityModel> ()->SetVelocity (Vector (10.0, 0.0, 0.0));

  // ---- NDN stack ---------------------------------------------------------
  ndn::StackHelper ndnHelper;
  ndnHelper.SetDefaultRoutes (true);
  ndnHelper.InstallAll ();

  // Install the NN routing strategy on the router for the data prefix.
  ndn::StrategyChoiceHelper::Install (router, "/", "/localhost/nfd/strategy/nn-routing");
  // RSUs and OBU use the default multicast strategy.

  // ---- FIB routes --------------------------------------------------------
  // OBU: route /ndn/nn/handover towards both RSUs (multicast) so the control
  // Interest reaches the router through either RSU.
  ndn::FibHelper::AddRoute (obu, "/ndn/nn/handover", rsu0, 1);
  ndn::FibHelper::AddRoute (obu, "/ndn/nn/handover", rsu1, 1);

  // RSU0 -> Router for the handover control / hint prefixes.
  ndn::FibHelper::AddRoute (rsu0, "/ndn/nn/handover", router, 1);
  ndn::FibHelper::AddRoute (rsu1, "/ndn/nn/handover", router, 1);

  // Router -> RSU0 and RSU1 for the data prefix (so it can multicast by default
  // and, after a hint, forward to the chosen RSU only).
  ndn::FibHelper::AddRoute (router, "/ndn/data", rsu0, 1);
  ndn::FibHelper::AddRoute (router, "/ndn/data", rsu1, 1);

  // ---- Applications ------------------------------------------------------
  // Decision model: the heuristic stand-in (replace with a real NN backend).
  Ptr<nnhandover::NnDecisionModel> decision = CreateObject<nnhandover::NnHeuristicDecisionModel> ();

  // Router app.
  Ptr<nnhandover::NnRouterApp> routerApp = CreateObject<nnhandover::NnRouterApp> ();
  routerApp->SetAttribute ("AppPrefix", StringValue ("/ndn/nn/handover"));
  routerApp->SetAttribute ("NodeName", StringValue ("/ndn/router/router0"));
  routerApp->SetAttribute ("DecisionModel", PointerValue (decision));
  router->AddApplication (routerApp);
  routerApp->SetStartTime (Seconds (0.5));

  // RSU apps.
  Ptr<nnhandover::NnRsuApp> rsu0App = CreateObject<nnhandover::NnRsuApp> ();
  rsu0App->SetAttribute ("AppPrefix", StringValue ("/ndn/nn/handover"));
  rsu0App->SetAttribute ("NodeName", StringValue ("/ndn/rsu/rsu0"));
  rsu0App->SetAttribute ("RouterId", StringValue ("router0"));
  rsu0App->SetAttribute ("DataPrefix", StringValue ("/ndn/data/rsu0"));
  rsu0App->SetAttribute ("DecisionModel", PointerValue (decision));
  rsu0->AddApplication (rsu0App);
  rsu0App->SetStartTime (Seconds (0.6));

  Ptr<nnhandover::NnRsuApp> rsu1App = CreateObject<nnhandover::NnRsuApp> ();
  rsu1App->SetAttribute ("AppPrefix", StringValue ("/ndn/nn/handover"));
  rsu1App->SetAttribute ("NodeName", StringValue ("/ndn/rsu/rsu1"));
  rsu1App->SetAttribute ("RouterId", StringValue ("router0"));
  rsu1App->SetAttribute ("DataPrefix", StringValue ("/ndn/data/rsu1"));
  rsu1App->SetAttribute ("DecisionModel", PointerValue (decision));
  rsu1->AddApplication (rsu1App);
  rsu1App->SetStartTime (Seconds (0.6));

  // OBU app. Give it the list of RSUs (id + position) so it can estimate RSSI
  // and detect the handover.
  std::vector<nnhandover::RsuEntry> rsuList;
  nnhandover::RsuEntry e0;
  e0.rsuId = "rsu0";
  e0.nodeId = rsu0->GetId ();
  e0.position = rsu0->GetObject<MobilityModel> ()->GetPosition ();
  rsuList.push_back (e0);
  nnhandover::RsuEntry e1;
  e1.rsuId = "rsu1";
  e1.nodeId = rsu1->GetId ();
  e1.position = rsu1->GetObject<MobilityModel> ()->GetPosition ();
  rsuList.push_back (e1);

  Ptr<nnhandover::NnObuApp> obuApp = CreateObject<nnhandover::NnObuApp> ();
  obuApp->SetAttribute ("AppPrefix", StringValue ("/ndn/nn/handover"));
  obuApp->SetAttribute ("NodeName", StringValue ("/ndn/vehicle/car_0"));
  obuApp->SetAttribute ("RouterId", StringValue ("router0"));
  obuApp->SetAttribute ("SampleIntervalMs", UintegerValue (500));
  obuApp->SetRsuList (rsuList);
  obu->AddApplication (obuApp);
  obuApp->SetStartTime (Seconds (1.0));

  // ---- Tell the router which face leads to which RSU ---------------------
  // The router has two p2p devices: rsu0RouterDev.Get(1) towards RSU0, and
  // routerRsu1Dev.Get(0) towards RSU1.
  uint64_t routerFaceToRsu0 = GetFaceIdForNetDevice (router, rsu0RouterDev.Get (1));
  uint64_t routerFaceToRsu1 = GetFaceIdForNetDevice (router, routerRsu1Dev.Get (0));

  // These are set after the apps start; schedule the mapping installation.
  Simulator::Schedule (Seconds (0.7), [routerApp, routerFaceToRsu0, routerFaceToRsu1] () {
    routerApp->AddRsuFace ("rsu0", routerFaceToRsu0);
    routerApp->AddRsuFace ("rsu1", routerFaceToRsu1);
  });

  std::cout << "Router face -> RSU0: " << routerFaceToRsu0 << ", -> RSU1: " << routerFaceToRsu1
            << std::endl;

  // ---- Run ---------------------------------------------------------------
  Simulator::Stop (Seconds (simTime));
  Simulator::Run ();
  Simulator::Destroy ();

  std::cout << "=== Simulation finished ===" << std::endl;
  return 0;
}

} // namespace ns3

int
main (int argc, char *argv[])
{
  return ns3::main (argc, argv);
}
