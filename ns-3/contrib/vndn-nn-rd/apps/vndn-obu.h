/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-obu.h
 * \brief 车载单元（OBU）应用核心逻辑（重构版）。
 *
 * 本文件是 ndn4ivc 中 fgfxf-obu 的精简重构版本，仅保留 NDN 应用通信框架：
 *   - 在 face 上注册前缀，接收并分发兴趣包
 *   - 提供 OnInterest / OnData / OnTimeout / OnNack 四个回调框架
 *   - 保留 SUMO TraciClient 引用，用于后续获取车辆交通信息
 *
 * 原有的基站驻留切换、AI 训练数据采集、主动请求发送等业务逻辑暂不移植，
 * 后续可在对应回调框架中逐步补充。
 */

#ifndef VNDN_OBU_H
#define VNDN_OBU_H

#include "ns3/ptr.h"
#include "ns3/traci-client.h"

#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/face.hpp>
#include <ndn-cxx/data.hpp>
#include <ndn-cxx/util/scheduler.hpp>

namespace vanet {

/**
 * \brief 车载单元（OBU）NDN 应用核心类。
 *
 * 该类封装了 OBU 节点上 NDN 应用的基本通信框架。它通过 ndn::Face 与
 * 本地 NFD 转发器交互，注册兴趣前缀并处理收到的兴趣包与数据包。
 *
 * 当前版本仅保留框架，具体业务逻辑待后续补充。
 */
class VndnObu
{
public:
  /**
   * \brief 构造函数。
   * \param traci SUMO TraciClient 指针引用，用于获取车辆交通数据。
   */
  VndnObu (ns3::Ptr<ns3::TraciClient> &traci);

  /**
   * \brief 启动 OBU 应用。
   *        开始处理 NDN 事件，标记应用为活跃状态。
   */
  void
  Start ();

  /**
   * \brief 停止 OBU 应用。
   *        关闭 face，取消定时器，标记应用为非活跃状态。
   */
  void
  Stop ();

private:
  /**
   * \brief 遍历节点上的 NetDevice，区分无线接口并注册前缀。
   *        同时记录无线设备地址与 faceId，供后续业务使用。
   */
  void
  RegisterFacePrefixs ();

  /**
   * \brief 兴趣包分发入口。
   *        根据兴趣包名称前缀，将兴趣包路由到对应的 OnInterest 处理函数。
   * \param interest 收到的兴趣包
   */
  void
  ProcessInterest (const ndn::Interest &interest);

  /**
   * \brief 从兴趣包中提取 IncomingFaceId 标签。
   * \param interest 收到的兴趣包
   * \return 入向 faceId，若标签不存在则返回 0（表示来自本节点上层）
   */
  uint64_t
  ExtractIncomingFace (const ndn::Interest &interest);

  ////////////////////////////////////////////////////////////////////////
  // NDN 通信回调框架（仅保留骨架，业务逻辑待补充）
  ////////////////////////////////////////////////////////////////////////

  /**
   * \brief 收到兴趣包的回调框架。
   *        当本节点收到匹配前缀的兴趣包时被调用，按前缀分发到具体处理函数。
   * \param interest 收到的兴趣包
   */
  void
  OnInterest (const ndn::Interest &interest);

  /**
   * \brief 收到基站同步信号（/vndn/control/hello）的处理函数。
   *        从兴趣包的 VndnTag 中提取发送者节点 ID、MAC、目标 MAC、单播标记并打印。
   * \param interest 收到的同步信号兴趣包
   */
  void
  OnSyncSignalInterest (const ndn::Interest &interest);

  /**
   * \brief 收到数据包的回调框架。
   *        当本节点发出的兴趣包得到数据响应时被调用。
   * \param interest 对应的兴趣包
   * \param data 收到的数据包
   */
  void
  OnData (const ndn::Interest &interest, const ndn::Data &data);

  /**
   * \brief 兴趣包超时的回调框架。
   *        当本节点发出的兴趣包在生命周期内未收到响应时被调用。
   * \param interest 超时的兴趣包
   */
  void
  OnTimeout (const ndn::Interest &interest);

  /**
   * \brief 收到 NACK 的回调框架。
   *        当本节点发出的兴趣包被下游节点拒绝时被调用。
   * \param interest 对应的兴趣包
   * \param nack 收到的 NACK 包
   */
  void
  OnNack (const ndn::Interest &interest, const ndn::lp::Nack &nack);

  ////////////////////////////////////////////////////////////////////////
  // 周期性请求发送（模拟用户高频访问）
  ////////////////////////////////////////////////////////////////////////

  /**
   * \brief 调度下一次兴趣包发送。
   *        根据请求频率计算下一次发送时刻并设置定时器。
   */
  void
  ScheduleNextPacket ();

  /**
   * \brief 发送一个兴趣包。
   *        构造兴趣包并通过 face 发出，随后调度下一次发送。
   */
  void
  SendPacket ();

private:
  ndn::Face m_face;                          ///< 应用层与 NFD 交互的 face
  ndn::Scheduler m_scheduler;                ///< NDN 定时器
  ns3::Ptr<ns3::TraciClient> m_traci;        ///< SUMO 交通数据客户端
  ns3::Ptr<ns3::Node> m_thisNode = nullptr;  ///< 本节点指针
  bool m_active = false;                     ///< 应用是否处于活跃状态
  ns3::Ptr<ns3::NetDevice> m_wirelessDevice = nullptr; ///< 无线网络设备
  uint64_t m_wirelessFaceId = 0;             ///< 无线链路对应的 faceId

  // 周期性请求相关成员
  double m_frequency = 40.0;                 ///< 请求频率（Hz），即每秒发送兴趣包次数
  ns3::EventId m_requestScheduler;           ///< 请求发送定时器
  uint32_t m_seq = 0;                        ///< 顺序递增的兴趣包序号
};

} // namespace vanet

#endif // VNDN_OBU_H
