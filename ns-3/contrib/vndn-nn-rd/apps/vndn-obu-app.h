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

namespace ns3 {

/**
 * \brief OBU 应用的 ns-3 Application 包装类。
 *
 * 通过 AddAttribute 暴露 SumoClient 属性，在 StartApplication / StopApplication
 * 中创建并启停 vanet::VndnObu 实例。
 */
class VndnObuApp : public Application
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
        ns3::TypeId ("VndnObuApp").SetParent<Application> ().AddConstructor<VndnObuApp> ()
            .AddAttribute ("SumoClient", "TraCi client for SUMO",
                           ns3::PointerValue (0),
                           ns3::MakePointerAccessor (&VndnObuApp::m_traci),
                           ns3::MakePointerChecker<ns3::TraciClient> ());
    return tid;
  }

  /**
   * \brief 启动应用：创建 VndnObu 实例并调用 Start()。
   */
  virtual void
  StartApplication () override
  {
    m_instance.reset (new vanet::VndnObu (m_traci));
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
};

} // namespace ns3

#endif // VNDN_OBU_APP_H
