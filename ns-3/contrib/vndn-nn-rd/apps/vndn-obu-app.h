/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-obu-app.h
 * \brief 车载单元（OBU）ns-3 Application 包装类（重构版）。
 *
 * 将 vanet::VndnObu 核心逻辑包装为 ns3::Application，以便通过 AppHelper
 * 在节点上安装。仅保留 SumoClient 属性与必要的启停逻辑。
 */

#ifndef VNDN_OBU_APP_H
#define VNDN_OBU_APP_H

#include "ns3/vndn-obu.h"
#include "ns3/application.h"
#include "ns3/traci-client.h"
#include "ns3/enum.h"
#include "ns3/boolean.h"
#include "ns3/double.h"
#include "ns3/string.h"

namespace ns3 {

/**
 * \brief OBU 应用的 ns-3 Application 包装类。
 *
 * 通过 AddAttribute 暴露 SumoClient 与 HandoverStrategy 属性，
 * 在 StartApplication / StopApplication 中创建并启停 vanet::VndnObu 实例。
 */
class VndnObuApp : public Application
{
public:
  /**
   * \brief 获取 TypeId。
   *        注册 SumoClient、HandoverStrategy 属性与构造函数。
   */
  static ns3::TypeId
  GetTypeId ()
  {
    static ns3::TypeId tid =
        ns3::TypeId ("VndnObuApp").SetParent<Application> ().AddConstructor<VndnObuApp> ()
            .AddAttribute ("SumoClient", "TraCi client for SUMO",
                           ns3::PointerValue (0),
                           ns3::MakePointerAccessor (&VndnObuApp::m_traci),
                           ns3::MakePointerChecker<ns3::TraciClient> ())
            .AddAttribute ("HandoverStrategy",
                           "Base station handover strategy: 0=Immediate, 1=AntiPingPong",
                           ns3::EnumValue (vanet::HandoverStrategy_AntiPingPong),
                           ns3::MakeEnumAccessor (&VndnObuApp::m_handoverStrategy),
                           ns3::MakeEnumChecker (vanet::HandoverStrategy_Immediate, "Immediate",
                                                 vanet::HandoverStrategy_AntiPingPong, "AntiPingPong"))
            .AddAttribute ("CacheStrategy",
                           "Cache response strategy: 0=None, 1=Participate",
                           ns3::EnumValue (vanet::CacheStrategy_None),
                           ns3::MakeEnumAccessor (&VndnObuApp::m_cacheStrategy),
                           ns3::MakeEnumChecker (vanet::CacheStrategy_None, "None",
                                                 vanet::CacheStrategy_Participate, "Participate"))
            .AddAttribute ("Frequency", "Normal Interest request frequency in Hz",
                           ns3::DoubleValue (40.0),
                           ns3::MakeDoubleAccessor (&VndnObuApp::m_frequency),
                           ns3::MakeDoubleChecker<double> (0.0))
            .AddAttribute ("HandoverFrequencyBoost",
                           "Increase request frequency when at least two RSUs are visible",
                           ns3::BooleanValue (false),
                           ns3::MakeBooleanAccessor (&VndnObuApp::m_handoverFrequencyBoost),
                           ns3::MakeBooleanChecker ())
            .AddAttribute ("HandoverFrequencyMultiplier",
                           "Frequency multiplier in a handover overlap area",
                           ns3::DoubleValue (4.0),
                           ns3::MakeDoubleAccessor (&VndnObuApp::m_handoverFrequencyMultiplier),
                           ns3::MakeDoubleChecker<double> (1.0))
            .AddAttribute ("EnableDataSave", "Save per-request OBU simulation data",
                           ns3::BooleanValue (false),
                           ns3::MakeBooleanAccessor (&VndnObuApp::m_enableDataSave),
                           ns3::MakeBooleanChecker ())
            .AddAttribute ("SaveFile", "Per-request CSV output path",
                           ns3::StringValue (""),
                           ns3::MakeStringAccessor (&VndnObuApp::m_saveFile),
                           ns3::MakeStringChecker ());
    return tid;
  }

  /**
   * \brief 启动应用：创建 VndnObu 实例，设置切换策略并调用 Start()。
   */
  virtual void
  StartApplication () override
  {
    m_instance.reset (new vanet::VndnObu (m_traci));
    m_instance->setHandoverStrategy (m_handoverStrategy);
    m_instance->setCacheStrategy (m_cacheStrategy);
    m_instance->setFrequency (m_frequency);
    m_instance->setHandoverFrequencyBoost (m_handoverFrequencyBoost,
                                            m_handoverFrequencyMultiplier);
    m_instance->setDataSave (m_enableDataSave, m_saveFile);
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
  std::unique_ptr<vanet::VndnObu> m_instance; ///< OBU 核心逻辑实例
  ns3::Ptr<ns3::TraciClient> m_traci;         ///< SUMO TraciClient 指针
  vanet::HandoverStrategy m_handoverStrategy = vanet::HandoverStrategy_AntiPingPong; ///< 切换策略
  vanet::CacheStrategy m_cacheStrategy = vanet::CacheStrategy_None; ///< 缓存响应策略
  double m_frequency = 40.0;
  bool m_handoverFrequencyBoost = false;
  double m_handoverFrequencyMultiplier = 4.0;
  bool m_enableDataSave = false;
  std::string m_saveFile;
};

} // namespace ns3

#endif // VNDN_OBU_APP_H
