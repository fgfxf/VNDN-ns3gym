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
#include <memory>
#include <sys/stat.h>

#include "ns3/vndn-utils-helper.h"
#include "ns3/vndn-pcap-writer.h"
#include "ns3/point-to-point-module.h"  // pcapwrite
#include "ns3/vndn-rsu-app.h"
#include "ns3/vndn-rsu-strategy.h"
#include "ns3/vndn-obu-app.h"
#include "ns3/vndn-router-app.h"
#include "ns3/log.h"

NS_LOG_COMPONENT_DEFINE ("vndn-circle-main");

int main(int argc,char *argv[]){
    using namespace ns3::ndn;

    std::string scenario_name = "circle-simple";
    std::string scenario_file = "circle";

    // 生成仿真数据输出目录 ./data/<scenario_name>/yyyyMMdd/hh-mm-ss/
    auto t_now = std::time(nullptr);
    auto tm_now = std::localtime(&t_now);
    std::ostringstream dateDir, timeDir;
    dateDir << std::put_time(tm_now, "%Y%m%d");
    timeDir << std::put_time(tm_now, "%H-%M-%S");
    std::string outputDir = "./data/" + scenario_name + "/" + dateDir.str() + "/" + timeDir.str() + "/";

    // 各类仿真数据输出路径
    std::string l3RateTracerFile = outputDir + "l3-rate-tracer.txt";      // L3速率追踪
    std::string pcapFile         = outputDir + "ndn-trace";               // PCAP抓包前缀（ns3自动追加-节点号.pcap）
    std::string pcapWriterFile   = outputDir + "ndn-trace.pcap";          // PcapWriter输出文件（p2p链路抓包）
    std::string csTracerFile     = outputDir + "cs-tracer.txt";           // 内容存储命中率追踪
    std::string netAnimFile      = outputDir + "netanim-animation.xml";   // NetAnim动画
    std::string aiTrainingTagDir = outputDir + "ai-training/";            // AI训练标签目录
    std::string aiTrainingTagFile= aiTrainingTagDir + "training-tag.csv"; // AI训练标签文件
   


    const uint32_t nVehicles = VndnUtilsHelper::GetVehicleCount(VndnUtilsHelper::ndn4ivc_traces_folder,scenario_name,scenario_file);
    uint32_t NdnInterval = 1;//ms
    uint32_t simTime = 80;//s
    uint32_t nRSUs = 2;  //路边单元数量
    bool enPcap = false;
    bool enLog = true;
    bool enSumoGui = false;
    bool enDataSave = true;
    uint32_t srandSeed = ::time(NULL);
    int sumoSeed = rand();

    vanet::CacheStrategy cacheStrategy = vanet::CacheStrategy_Participate;
    vanet::HandoverStrategy handoverStrategy = vanet::HandoverStrategy_Immediate;
    vanet::RsuForwardStrategy rsuForwardStrategy =
        vanet::RsuForwardStrategy_VTDF; // 回程补救策略
    uint32_t rsuForwardStrategyValue = static_cast<uint32_t> (rsuForwardStrategy);
    bool handoverFrequencyBoost = false;
    double obuFrequency = 40.0;
    double handoverFrequencyMultiplier = 4.0;
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
    cmd.AddValue ("save-data", "Enable simulation data output", enDataSave);
    cmd.AddValue ("sumo-seed", "SUMO random seed", sumoSeed);
    cmd.AddValue ("srand-seed", "C rand() random seed", srandSeed);
    cmd.AddValue ("rsu-forward-strategy",
                  "RSU Data recovery strategy: 0=NoForward, 1=VTDF, 2=RealTimeVTDF",
                  rsuForwardStrategyValue);
    cmd.AddValue ("handover-frequency-boost",
                  "Increase OBU request frequency when at least two RSUs are visible",
                  handoverFrequencyBoost);
    cmd.AddValue ("obu-frequency", "Normal OBU Interest frequency in Hz", obuFrequency);
    cmd.AddValue ("handover-frequency-multiplier",
                  "OBU request frequency multiplier in handover areas",
                  handoverFrequencyMultiplier);
    cmd.Parse (argc, argv);

    if (rsuForwardStrategyValue > 2)
      {
        std::cerr << "Invalid --rsu-forward-strategy value: "
                  << rsuForwardStrategyValue << std::endl;
        return 2;
      }
    rsuForwardStrategy =
        static_cast<vanet::RsuForwardStrategy> (rsuForwardStrategyValue);

    // 在仿真中首次使用 rand() 之前应用用户设置的 C 随机种子。
    srand (srandSeed);

    if (enLog || enDataSave || enPcap)
      {
        if (enLog)
          {
            // 记录 circle-main、OBU、RSU、Router 四个组件的全部级别日志
            std::vector<std::string> componentsLogLevelAll;
            componentsLogLevelAll.push_back ("vndn-circle-main");
            componentsLogLevelAll.push_back ("ndn.VndnObu");
            componentsLogLevelAll.push_back ("ndn.VndnRsu");
            componentsLogLevelAll.push_back ("ndn.VndnRouter");
            for (auto const &c : componentsLogLevelAll)
              {
                ns3::LogComponentEnable (c.c_str (), ns3::LOG_LEVEL_ALL);
                ns3::LogComponentEnable (c.c_str (), ns3::LOG_PREFIX_ALL);
              }
          }

        {
          // 递归创建输出目录
          std::string cmd = "mkdir -p " + outputDir;
          if (system (cmd.c_str ()) != 0)
            {
              std::cerr << "Warning: failed to create output directory: " << outputDir << std::endl;
            }
          // 创建AI训练标签子目录
          cmd = "mkdir -p " + aiTrainingTagDir;
          if (system (cmd.c_str ()) != 0)
            {
              std::cerr << "Warning: failed to create AI training directory: " << aiTrainingTagDir
                        << std::endl;
            }

          const char *cacheStrategyName =
              cacheStrategy == vanet::CacheStrategy_Participate ? "Participate" : "None";
          const char *handoverStrategyName =
              handoverStrategy == vanet::HandoverStrategy_Immediate
                  ? "Immediate"
                  : "AntiPingPong";
          const char *rsuForwardStrategyName = "NoForward";
          if (rsuForwardStrategy == vanet::RsuForwardStrategy_VTDF)
            rsuForwardStrategyName = "VTDF";
          else if (rsuForwardStrategy == vanet::RsuForwardStrategy_RealTimeVtdf)
            rsuForwardStrategyName = "RealTimeVTDF";

          std::ostringstream obuFrequencyValue;
          obuFrequencyValue << obuFrequency;
          std::vector<std::pair<std::string, std::string>> simulationParameters = {
              {"CacheStrategy", cacheStrategyName},
              {"HandoverStrategy", handoverStrategyName},
              {"obuFrequency", obuFrequencyValue.str ()},
              {"RsuForwardStrategy", rsuForwardStrategyName},
              {"SumoSeed", std::to_string (sumoSeed)},
              {"SrandSeed", std::to_string (srandSeed)}};
          if (!VndnUtilsHelper::SaveSimulationConfig (outputDir, simulationParameters))
            {
              std::cerr << "Warning: failed to create simulation config file: "
                        << outputDir << "simulation-config.txt" << std::endl;
            }
        }
        std::cout << "Log and data Output directory: " << outputDir << std::endl;
      }

    // 节点容器
    ns3::NodeContainer nodePool;
    nodePool.Create(nVehicles  + nRSUs);//车辆和基站节点
    ns3::NodeContainer serverNodes;  //服务器节点
    serverNodes.Create(1);
    ns3::NodeContainer routerNodes; //路由器节点
    routerNodes.Create(1);
    //wifi
    // 车联网基站切换场景参数说明：
    //   发射功率 23 dBm（约 200mW），对应 TwoRayGround 模型约 300m 覆盖范围，
    //   使车辆在两个 RSU 之间存在重叠覆盖区域，从而产生切换。
    //   接收灵敏度 -96 dBm，符合 IEEE 802.11p OFDM 6Mbps 模式的典型值。
    //   前导检测 SNR 阈值 4.0 dB，保证可靠的前导检测。
    ns3::ndn::WifiSetupHelper wifi;
    wifi.SetTxPower(10);     //发射功率 23 dBm ~ 300m 覆盖
    wifi.SetMiniRssi(-78);   //最低接收信号（802.11p 典型灵敏度 -96  dBm）
    wifi.SetSnr(4.0);        //前导检测 SNR 阈值 4.0 dB
    ns3::NetDeviceContainer devices = wifi.ConfigureDevices(nodePool,enPcap,pcapFile);

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
    ns3::ndn::StrategyChoiceHelper::Install(nodePool,"/","/localhost/nfd/strategy/vndn-multicast");
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
    sumoClient->SetAttribute("SumoSeed",ns3::IntegerValue(sumoSeed));
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
        ndnApp->SetAttribute("Frequency",ns3::DoubleValue(obuFrequency));
        ndnApp->SetAttribute("HandoverFrequencyBoost",ns3::BooleanValue(handoverFrequencyBoost));
        ndnApp->SetAttribute("HandoverFrequencyMultiplier",ns3::DoubleValue(handoverFrequencyMultiplier));
        ndnApp->SetAttribute("EnableDataSave",ns3::BooleanValue(enDataSave));
        ndnApp->SetAttribute("SaveFile",ns3::StringValue(aiTrainingTagFile));
        ndnApp->SetAttribute("CacheStrategy",ns3::EnumValue(cacheStrategy));
        ndnApp->SetAttribute("HandoverStrategy",ns3::EnumValue(handoverStrategy));
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
        VndnUtilsHelper::nodesDisable2Move.emplace(exNode->GetId(),(ns3::Time)ns3::Simulator::Now().GetSeconds());
    };

    //////////////RSU节点设置//////////////////////////
    ns3::ApplicationContainer  itsRsuNodes;
    ns3::ndn::AppHelper rsuApp("VndnRsuApp");
    rsuApp.SetAttribute("SumoClient",(ns3::PointerValue)(sumoClient));
    rsuApp.SetAttribute("RsuForwardStrategy",ns3::EnumValue(rsuForwardStrategy));
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
    ns3::ndn::AppHelper router("VndnRouterApp");
    ns3::ApplicationContainer routerApp = router.Install(routerNodes.Get(0));
    routerApp.Start(ns3::Seconds(0.0));


    //所有的基站，找不到缓存的数据前缀都向server请求。
    ns3::ndn::FibHelper::AddRoute(nodePool.Get (0),"/",routerNodes.Get(0),15);
    ns3::ndn::FibHelper::AddRoute(nodePool.Get (1),"/",routerNodes.Get(0),15);
    ns3::ndn::FibHelper::AddRoute(routerNodes.Get (0),"/",serverNodes.Get(0),15);
    //开始模拟前的最后设置
    ns3::Config::Set("/NodeList/*/DeviceList/*/$ns3::WifiNetDevice/Phy/ChannelNumber",ns3::UintegerValue(SCH1));
    sumoClient->SumoSetup(setupNewNode,shutdownSumoNode);
    ns3::Simulator::Schedule(ns3::Seconds(1.0),&VndnUtilsHelper::checkDisableNodes);//延迟移除被sumo移除的节点

    ///////////追踪，获取仿真数据
    std::unique_ptr<ns3::AnimationInterface> animation;
    std::unique_ptr<ns3::ndn::VndnPcapWriter> pcapWriter;
    if (enDataSave)
      {
        ns3::ndn::L3RateTracer::InstallAll (l3RateTracerFile, ns3::Seconds (1.0));
        ns3::ndn::CsTracer::InstallAll (csTracerFile, ns3::Seconds (1.0));
        animation.reset (new ns3::AnimationInterface (netAnimFile));
      }
    if (enPcap)
      {
        pcapWriter.reset (new ns3::ndn::VndnPcapWriter (pcapWriterFile));
        ns3::Config::ConnectWithoutContext (
            "/NodeList/*/DeviceList/*/$ns3::PointToPointNetDevice/MacTx",
            ns3::MakeCallback (&ns3::ndn::VndnPcapWriter::TracePacket, pcapWriter.get ()));
      }

    ns3::Simulator::Stop (ns3::Seconds (simTime));
    ns3::Simulator::Run();//正式运行
    // SUMO 尚未移除、但在仿真结束时仍活跃的 OBU 也必须落盘最终统计。
    for (uint32_t i = 0; i < nodePool.GetN (); ++i)
      {
        ns3::Ptr<ns3::Node> node = nodePool.Get (i);
        for (uint32_t j = 0; j < node->GetNApplications (); ++j)
          {
            ns3::Ptr<ns3::VndnObuApp> obuApp =
                ns3::DynamicCast<ns3::VndnObuApp> (node->GetApplication (j));
            if (obuApp != nullptr)
              {
                obuApp->StopApplication ();
              }
          }
      }
    ns3::Simulator::Destroy();
    return 0;
}
