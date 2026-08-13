/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-rsu-app.h
 * \brief 路边单元（RSU）ns-3 Application 包装类（重构版）。
 *
 * 将 vanet::VndnRsu 核心逻辑包装为 ns3::Application，以便通过 AppHelper
 * 在节点上安装。仅保留 SumoClient 属性与必要的启停逻辑。
 */

#ifndef VNDN_RSU_APP_H
#define VNDN_RSU_APP_H

#include "ns3/vndn-rsu.h"
#include "ns3/vndn-rsu-strategy.h"
#include "ns3/application.h"
#include "ns3/traci-client.h"
#include "ns3/enum.h"
#include "ns3/uinteger.h"

namespace ns3 {

/**
 * \brief RSU 应用的 ns-3 Application 包装类。
 *
 * 通过 AddAttribute 暴露 SumoClient 属性，在 StartApplication / StopApplication
 * 中创建并启停 vanet::VndnRsu 实例。
 */
class VndnRsuApp : public Application
{
public:
  /**
   * \brief 获取 TypeId。
   *        仅注册 SumoClient 属性与构造函数。
   */
  static ns3::TypeId
  GetTypeId ()
  {
    static ns3::TypeId tid =
        ns3::TypeId ("VndnRsuApp").SetParent<Application> ().AddConstructor<VndnRsuApp> ()
            .AddAttribute ("SumoClient", "TraCi client for SUMO",
                           ns3::PointerValue (0),
                           ns3::MakePointerAccessor (&VndnRsuApp::m_traci),
                           ns3::MakePointerChecker<ns3::TraciClient> ())
            .AddAttribute (
                "RsuForwardStrategy",
                "Vehicle Data return strategy: NoForward, VTDF, RealTimeVTDF, or NeuralNetwork",
                ns3::EnumValue (vanet::RsuForwardStrategy_NoForward),
                ns3::MakeEnumAccessor (&VndnRsuApp::m_forwardStrategy),
                ns3::MakeEnumChecker (vanet::RsuForwardStrategy_NoForward, "NoForward",
                                      vanet::RsuForwardStrategy_VTDF, "VTDF",
                                      vanet::RsuForwardStrategy_RealTimeVtdf,
                                      "RealTimeVTDF",
                                      vanet::RsuForwardStrategy_NeuralNetwork,
                                      "NeuralNetwork"))
            .AddAttribute (
                "OpenGymPort",
                "Shared ns3-gym port used by the NeuralNetwork return strategy; 0 disables it",
                ns3::UintegerValue (0),
                ns3::MakeUintegerAccessor (&VndnRsuApp::m_openGymPort),
                ns3::MakeUintegerChecker<uint16_t> (0, 65535));
    return tid;
  }

  /**
   * \brief 启动应用：创建 VndnRsu 实例并调用 Start()。
   */
  virtual void
  StartApplication () override
  {
    m_instance.reset (new vanet::VndnRsu (m_traci));
    m_instance->setRsuForwardStrategy (m_forwardStrategy);
    m_instance->setOpenGymPort (m_openGymPort);
    m_instance->Start ();
  }

  /**
   * \brief 停止应用：调用 Stop() 并释放实例。
   */
  virtual void
  StopApplication () override
  {
    if (m_instance)
      {
        m_instance->Stop ();
        m_instance.reset ();
      }
  }

private:
  std::unique_ptr<vanet::VndnRsu> m_instance; ///< RSU 核心逻辑实例
  ns3::Ptr<ns3::TraciClient> m_traci;         ///< SUMO TraciClient 指针
  vanet::RsuForwardStrategy m_forwardStrategy =
      vanet::RsuForwardStrategy_NoForward;
  uint16_t m_openGymPort = 0;
};

} // namespace ns3

#endif // VNDN_RSU_APP_H
