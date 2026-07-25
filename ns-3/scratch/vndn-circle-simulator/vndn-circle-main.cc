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
#include "ns3/point-to-point-helper.h"
#include <functional>
#include <stdlib.h>
#include <stdio.h>
#include <exception>
#include <vector>
#include <iostream>
#include <sstream>
#include <ctime>
#include <iomanip>
#include <sys/stat.h>

#include "ns3/vndn-utils-helper.h"
#include "ns3/point-to-point-module.h"  // pcapwrite
#include "ns3/vndn-rsu-app.h"
#include "ns3/vndn-obu-app.h"



//for safe remove node in ns3 vis
std::map<uint32_t,ns3::Time> nodesDisable2Move;//nodeID  -- stopTime
void checkDisableNodes(){
    double endX = -1500.0;   //end node location
    double endY = -2500.0; 
    double endZ= 1.2; 
  for (auto it = nodesDisable2Move.begin (), it_next = it; it_next != nodesDisable2Move.end (); it = it_next) {
      ++it_next;
      ns3::Ptr<ns3::Node> exNode = ns3::NodeList::GetNode (it->first);
      // NOTE:we'll put the node in a new position, outside the simulation
      // communication range, but this is just for better visualization mode
      if ((ns3::Time) ns3::Simulator::Now ().GetSeconds () - it->second > 1) {
          ns3::Ptr< ns3::ConstantPositionMobilityModel> mob =
              exNode->GetObject< ns3::ConstantPositionMobilityModel> ();
          mob->SetPosition (ns3::Vector (endX - (rand()%25),  endY - (rand () % 25),endZ));
          nodesDisable2Move.erase (it);
        ns3::ObjectDeleter::Delete((ns3::Object*)&*exNode);
        }
    }
 ns3:: Simulator::Schedule (ns3::Seconds (1), &checkDisableNodes);
}



class PcapWriter
{
public:
  PcapWriter (const std::string &file)
  {
    ns3::PcapHelper helper;
    m_pcap = helper.CreateFile (file, std::ios::out, ns3::PcapHelper::DLT_PPP);
  }

  void
  TracePacket (ns3::Ptr<const ns3::Packet> packet)
  {
    static ns3::PppHeader pppHeader;
    pppHeader.SetProtocol (0x0077);
    m_pcap->Write (ns3::Simulator::Now (), pppHeader, packet);
  }

private:
  ns3::Ptr<ns3::PcapFileWrapper> m_pcap;
};

int main(int argc,char *argv[]){
    using namespace ns3::ndn;

    std::string scenario_name = "circle-simple";
    std::string scenario_file = "circle";

    // 生成仿真数据输出目录 ./data/<scenario_name>/yyyyMMdd/hh-mm/
    auto t_now = std::time(nullptr);
    auto tm_now = std::localtime(&t_now);
    std::ostringstream dateDir, timeDir;
    dateDir << std::put_time(tm_now, "%Y%m%d");
    timeDir << std::put_time(tm_now, "%H-%M");
    std::string outputDir = "./data/" + scenario_name + "/" + dateDir.str() + "/" + timeDir.str() + "/";

    // 各类仿真数据输出路径
    std::string l3RateTracerFile = outputDir + "l3-rate-tracer.txt";      // L3速率追踪
    std::string pcapFile         = outputDir + "ndn-trace.pcap";          // PCAP抓包
    std::string appDelayFile     = outputDir + "app-delay-tracer.txt";    // 应用层时延追踪
    std::string csTracerFile     = outputDir + "cs-tracer.txt";           // 内容存储命中率追踪
    std::string netAnimFile      = outputDir + "netanim-animation.xml";   // NetAnim动画
    std::string sumoLogFile      = outputDir + "sumo.log";                // SUMO日志
    std::string aiTrainingTagDir = outputDir + "ai-training/";            // AI训练标签目录
    std::string aiTrainingTagFile= aiTrainingTagDir + "training-tag.csv"; // AI训练标签文件
   
    // {
    //     // 递归创建输出目录
    //     std::string cmd = "mkdir -p " + outputDir;
    //     if (system(cmd.c_str()) != 0) {
    //         std::cerr << "Warning: failed to create output directory: " << outputDir << std::endl;
    //     }
    //      // 创建AI训练标签子目录
    //     cmd = "mkdir -p " + aiTrainingTagDir;
    //     if (system(cmd.c_str()) != 0) {
    //         std::cerr << "Warning: failed to create AI training directory: " << aiTrainingTagDir << std::endl;
    //     }
    // }
    std::cout << "Output directory: " << outputDir << std::endl;

    const uint32_t nVehicles = VndnUtilsHelper::GetVehicleCount(VndnUtilsHelper::ndn4ivc_traces_folder,scenario_name,scenario_file);
    uint32_t NdnInterval = 1;//ms
    uint32_t simTime = 200;//s
    uint32_t nRSUs = 2;  //路边单元数量
    bool enPcap = false;
    bool enLog = true;
    bool enSumoGui = false;
    double startX = 300.0;//start node positon 刚开始没有使用的节点的位置
    double startY = 300.0;
    uint32_t usedNodeCounter = 0;//移动节点池   使用过的节点计数
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


    // 节点容器
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
    ns3::NetDeviceContainer devices = wifi.ConfigureDevices(nodePool,enPcap);

    //p2p
    ns3::PointToPointHelper p2p;
    // p2p.SetDeviceAttribute("DataRate",ns3::StringValue("100Mbps"));
    // p2p.SetChannelAttribute("Delay",ns3::StringValue("40ms"));
    // p2p.Install(nodePool.Get(0),nodePool.Get(1));//RSU之间逻辑链路,这个时延应当比经过核心网要大，因为我们是图省事直接建立的物理链路

    p2p.SetDeviceAttribute("DataRate",ns3::StringValue("100Mbps"));
    p2p.SetChannelAttribute("Delay",ns3::StringValue("20ms"));
    p2p.Install(nodePool.Get(0),routerNodes.Get(0));//RSU和核心网之间的链路
    p2p.Install(nodePool.Get(1),routerNodes.Get(0));//RSU和核心网之间的链路

    p2p.SetChannelAttribute("Delay",ns3::StringValue("60ms"));
    p2p.Install(routerNodes.Get(0),serverNodes.Get(0));//服务器和核心网之间的链路


    //安装ndn协议栈
    std::cout<<BLUE_CODE <<"安装ndn协议栈..."<<END_CODE<<std::endl;
    ns3::ndn::StackHelper ndnStackHelper;
    //修复ndn协议栈adhoc的id错误
    ndnStackHelper.AddFaceCreateCallback(ns3::WifiNetDevice::GetTypeId(),ns3::MakeCallback(ns3::FixLinkTypeAdhocCb));
    ndnStackHelper.setCsSize(10);
    ndnStackHelper.InstallAll();
    ns3::ndn::StrategyChoiceHelper::Install(nodePool,"/","/localhost/nfd/strategy/multicast-vanet");
    //安装sumo和mobility
    std::cout<<"配置sumo/Traci..." <<std::endl;
    ns3::MobilityHelper mobility;
    //刚开始没有使用的节点安放
    ns3::Ptr<ns3::UniformDiscPositionAllocator>  positonAlloc = ns3::CreateObject<ns3::UniformDiscPositionAllocator>();
    positonAlloc->SetX(startX + (rand()%10));
    positonAlloc->SetY(startY + (rand()%10));
    positonAlloc->SetZ(1.2);
    positonAlloc->SetRho(10.0);
    mobility.SetPositionAllocator(positonAlloc);
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(nodePool);
    mobility.Install(serverNodes);
    mobility.Install(routerNodes);
    //sumo traci安装
    ns3::Ptr<ns3::TraciClient> sumoClient = ns3::CreateObject<ns3::TraciClient>();
    sumoClient->SetAttribute("SumoConfigPath",ns3::StringValue(VndnUtilsHelper::ndn4ivc_traces_folder+"/"+scenario_name+"/" +scenario_file + ".sumo.cfg" ));
    sumoClient->SetAttribute("SumoBinaryPath",ns3::StringValue(""));
    sumoClient->SetAttribute("SynchInterval",ns3::TimeValue(ns3::MilliSeconds(NdnInterval)));////同步
    sumoClient->SetAttribute("StartTime",ns3::TimeValue(ns3::Seconds(0.0)));
    sumoClient->SetAttribute("SumoGUI",ns3::BooleanValue(enSumoGui));
    sumoClient->SetAttribute("SumoPort",ns3::UintegerValue(3400));
    sumoClient->SetAttribute("PenetrationRate",ns3::DoubleValue(1.0));
    sumoClient->SetAttribute("SumoLogFile",ns3::BooleanValue(false));
    sumoClient->SetAttribute("SumoStepLog",ns3::BooleanValue(false));
    sumoClient->SetAttribute("SumoSeed",ns3::IntegerValue(10));
    sumoClient->SetAttribute("SumoAdditionalCmdOptions",ns3::StringValue("--verbose true"));
    sumoClient->SetAttribute("SumoWaitForSocket",ns3::TimeValue(ns3::Seconds(2.0)));//等待sumo服务启动



    //call back 设置动态节点的生成和销毁
    std::function<ns3::Ptr<ns3::Node>()>  setupNewNode = [&]()->ns3::Ptr<ns3::Node>
    {
        if(usedNodeCounter >= nodePool.GetN()){
           NS_FATAL_ERROR ("Node Pool empty: " << usedNodeCounter << " nodes created.");
           return nullptr;
        }
        std::cout<<"ns3 Sumo setup node["<<usedNodeCounter<<"]!"<<std::endl;
        ns3::Ptr<ns3::Node> newNode = nodePool.Get(usedNodeCounter++);
        //ndn app
        ns3::Ptr<ns3::VndnObuApp>  ndnApp = ns3::CreateObject<ns3::VndnObuApp>();
        // ndnApp->SetAttribute("Frequency",ns3::DoubleValue(40.0));//频率
        ndnApp->SetAttribute("SumoClient",(ns3::PointerValue)(sumoClient));
        // ndnApp->SetAttribute("SaveDic",ns3::StringValue(aiTrainingTagDir));
        // ndnApp->SetAttribute("SaveFile",ns3::StringValue(aiTrainingTagFile));
        // ndnApp->SetAttribute("ExtendData",ns3::BooleanValue(ObuExtendData));
        // ndnApp->SetAttribute("TargetRsuId",ns3::IntegerValue(targetRsu));

        newNode->AddApplication(ndnApp);
        return newNode;
    };

    //////销毁回调
    std::function<void (ns3::Ptr<ns3::Node>)> shutdownSumoNode = [&](ns3::Ptr<ns3::Node> exNode)
    {
        std::cout<<"ns3 Sumo remove :["<<exNode->GetId() <<"]!"<<std::endl;
        ns3::Ptr<ns3::VndnObuApp> ndnApp = ns3::DynamicCast<ns3::VndnObuApp>(exNode->GetApplication(0));
        if(ndnApp){
            ndnApp->StopApplication();
        }
        for(uint32_t i=0;i<exNode->GetNDevices();i++){
            auto netDevices = exNode->GetDevice(i)->GetObject<ns3::WifiNetDevice>();
            if(netDevices)
                netDevices->GetPhy()->SetOffMode();//关掉节点中wifi设备
        }
        //为了确保节点安全移除，先不直接删除
        nodesDisable2Move.emplace(exNode->GetId(),(ns3::Time)ns3::Simulator::Now().GetSeconds());
    };

    //////////////RSU节点设置//////////////////////////
    ns3::ApplicationContainer  itsRsuNodes;
    ns3::ndn::AppHelper rsuApp("VndnRsuApp");
    rsuApp.SetAttribute("SumoClient",(ns3::PointerValue)(sumoClient));
    // rsuApp.SetAttribute("RsuForwardStrategy",ns3::EnumValue(strategy));
    // rsuApp.SetAttribute("OpenGymPort",ns3::UintegerValue(OpengymPort));/////////////////////这个设置神经网络

    ns3::Ptr<ns3::MobilityModel> rsuNode0 = nodePool.Get(0) ->GetObject<ns3::MobilityModel>();
    rsuNode0->SetPosition(ns3::Vector(-20,70,20));
    itsRsuNodes.Add (rsuApp.Install (nodePool.Get (0)));
    usedNodeCounter++;

    // rsuApp.SetAttribute("OpenGymPort",ns3::UintegerValue(0));m
    rsuNode0 = nodePool.Get(1) ->GetObject<ns3::MobilityModel>();
    rsuNode0->SetPosition(ns3::Vector(150,70,20));
    itsRsuNodes.Add (rsuApp.Install (nodePool.Get (1)));
    usedNodeCounter++;

    // rsuNode0 = nodePool.Get(2) ->GetObject<ns3::MobilityModel>();
    // rsuNode0->SetPosition(ns3::Vector(210,70,20));
    // itsRsuNodes.Add (rsuApp.Install (nodePool.Get (2)));
    // usedNodeCounter++;

    ///////////////服务器节点设置////////////////////
    ns3::Ptr<ns3::MobilityModel> serverNode = serverNodes.Get(0) ->GetObject<ns3::MobilityModel>();
    serverNode->SetPosition(ns3::Vector(65,-50,200));
    ns3::ndn::AppHelper producer("ns3::ndn::Producer");
    producer.SetPrefix("/com/baidu");
    producer.SetAttribute("PayloadSize",ns3::StringValue("10240"));
    ns3::ApplicationContainer producerApp =  producer.Install(serverNodes.Get(0));
    producerApp.Start(ns3::Seconds(0.0));

    ns3::Ptr<ns3::MobilityModel> routerNode = routerNodes.Get(0) ->GetObject<ns3::MobilityModel>();
    routerNode->SetPosition(ns3::Vector(65,0,200));


    //所有的基站，找不到缓存的数据前缀都向server请求。
    ns3::ndn::FibHelper::AddRoute(nodePool.Get (0),"/",routerNodes.Get(0),15);
    ns3::ndn::FibHelper::AddRoute(nodePool.Get (1),"/",routerNodes.Get(0),15);
    ns3::ndn::FibHelper::AddRoute(routerNodes.Get (0),"/",serverNodes.Get(0),15);
    //开始模拟前的最后设置
    ns3::Config::Set("/NodeList/*/DeviceList/*/$ns3::WifiNetDevice/Phy/ChannelNumber",ns3::UintegerValue(SCH1));
    sumoClient->SumoSetup(setupNewNode,shutdownSumoNode);
    ns3::Simulator::Schedule(ns3::Seconds(1.0),&checkDisableNodes);//延迟移除被sumo移除的节点

    ///////////追踪，获取仿真数据
    if (enPcap)
      {
        ns3::ndn::L3RateTracer::InstallAll (l3RateTracerFile, ns3::Seconds (1.0));
        PcapWriter trace (pcapFile);
        ns3::Config::ConnectWithoutContext (
            "/NodeList/*/DeviceList/*/$ns3::PointToPointNetDevice/MacTx",
            ns3::MakeCallback (&PcapWriter::TracePacket, &trace));
      }

    ns3::Simulator::Stop (ns3::Seconds (simTime));
    ns3::Simulator::Run();//正式运行
    ns3::Simulator::Destroy();
    return 0;
}


