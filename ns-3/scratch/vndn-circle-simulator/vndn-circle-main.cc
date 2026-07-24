#include "ns3/wifi-module.h"
#include "ns3/mobility-module.h"
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/ndnSIM-module.h"
#include "ns3/internet-module.h"
#include "ns3/wifi-setup-helper.h"
#include "ns3/wifi-adhoc-helper.h"
#include "ns3/traci-module.h"
#include "ns3/netanim-module.h"
#include <functional>
#include <stdlib.h>
#include <stdio.h>
#include <exception>
#include <vector>
#include <iostream>
#include <sstream>

#include"ns3/vndn-utils-helper.h"
int main(int argc,char *argv[]){
    using namespace ns3::ndn;

    std::string scenario_name = "circle-simple";
    std::string scenario_file = "circle";
    const uint32_t nVehicles = VndnUtilsHelper::GetVehicleCount(VndnUtilsHelper::ndn4ivc_traces_folder,scenario_name,scenario_file);
    const uint32_t NdnInterval = 1;//ms
    uint32_t simTime = 200;//s
    uint32_t nRSUs = 2;  //路边单元数量
    bool enPcap = false;
    bool enLog = true;
    bool enSumoGui = false;


    std::cout << "# nodes (vehicles) detected in SUMO scenario: " << nVehicles << std::endl;
    std::cout << "# Road Side Units (RSUs): " << nRSUs << std::endl;


    //cmd
    ns3::CommandLine cmd;
    cmd.AddValue ("i", "Interest interval (milliseconds)", NdnInterval);
    cmd.AddValue ("s", "Simulation time (seconds)", simTime);
    cmd.AddValue ("pcap", "Enable PCAP", enPcap);
    cmd.AddValue ("log", "Enable Log", enLog);
    cmd.AddValue ("sumo-gui", "Enable SUMO with graphical user interface", enSumoGui);
    cmd.Parse (argc, argv);


 //节点容器
    ns3::NodeContainer nodePool;
    nodePool.Create(nVehicles  + nRSUs);//车辆和基站节点
    ns3::NodeContainer serverNodes;  //服务器节点
    serverNodes.Create(1);
    ns3::NodeContainer routerNodes; //路由器节点
    routerNodes.Create(1);
    //wifi
    ns3::ndn::WifiSetupHelper wifi;
    wifi.SetTxPower(12);//发射功率  dBm
    wifi.SetMiniRssi(-78);//最低接受 dBm
    wifi.SetSnr(-4);//信噪比
    ns3::NetDeviceContainer devices = wifi.ConfigureDevices(nodePool,enPcap,"wifipacp10240");


    return 0;
}


