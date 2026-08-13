/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-rsu.h
 * \brief 路边单元（RSU）应用核心逻辑（重构版）。
 *
 * 本文件是 ndn4ivc 中 fgfxf-rsu 的精简重构版本，仅保留 NDN 应用通信框架：
 *   - 在 face 上注册前缀，接收并分发兴趣包
 *   - 提供 OnInterest / OnData / OnTimeout / OnNack 四个回调框架
 *   - 保留 SUMO TraciClient 引用，用于后续获取 RSU 位置等信息
 *
 * 原有的车辆注册管理、beacon 广播、核心网代理请求、强化学习等业务逻辑
 * 暂不移植，后续可在对应回调框架中逐步补充。
 */

#ifndef VNDN_RSU_H
#define VNDN_RSU_H

#include "ns3/ptr.h"
#include "ns3/traci-client.h"
#include "ns3/node-list.h"
#include "vndn-rsu-strategy.h"

#include <ndn-cxx/interest.hpp>
#include <ndn-cxx/face.hpp>
#include <ndn-cxx/data.hpp>
#include <ndn-cxx/util/scheduler.hpp>

#include "../src/json/single_include/nlohmann/json.hpp"

#include <map>
#include <array>
#include <deque>
#include <queue>
#include <set>
#include <string>
#include <vector>

namespace ns3 {
class OpenGymInterface;
class OpenGymSpace;
class OpenGymDataContainer;
}

namespace vanet {

/**
 * \brief 路边单元（RSU）NDN 应用核心类。
 *
 * 该类封装了 RSU 节点上 NDN 应用的基本通信框架。它通过 ndn::Face 与
 * 本地 NFD 转发器交互，注册兴趣前缀并处理收到的兴趣包与数据包。
 *
 * 当前版本仅保留框架，具体业务逻辑待后续补充。
 */
class VndnRsu
{
public:
  /**
   * \brief 构造函数。
   * \param traci SUMO TraciClient 指针引用，用于获取 RSU 相关数据。
   */
  VndnRsu (ns3::Ptr<ns3::TraciClient> &traci);

  /**
   * \brief 启动 RSU 应用。
   *        开始处理 NDN 事件，标记应用为活跃状态。
   */
  void
  Start ();

  /**
   * \brief 停止 RSU 应用。
   *        关闭 face，取消定时器，标记应用为非活跃状态。
   */
  void
  Stop ();

  void
  setRsuForwardStrategy (RsuForwardStrategy strategy);

  /** 设置共享 ns3-gym 端口；0 表示关闭。 */
  void
  setOpenGymPort (uint16_t openGymPort);

private:
  /**
   * \brief 遍历节点上的 NetDevice，区分 p2p 与无线接口并注册前缀。
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
   *        当本节点收到匹配前缀的兴趣包时被调用，后续在此实现具体响应逻辑。
   * \param interest 收到的兴趣包
   */
  void
  OnInterest (const ndn::Interest &interest);

  /**
   * \brief 收到数据包的回调框架。
   *        当本节点发出的兴趣包得到数据响应时被调用。
   * \param interest 对应的兴趣包
   * \param data 收到的数据包
   */
  void
  OnData (const ndn::Interest &interest, const ndn::Data &data);

  /**
   * \brief 收到同步信号响应数据包的处理函数。
   *        解析 OBU 上报的车辆信息（坐标、速度、加速度、角度、车道、次优基站），
   *        暂时仅打印日志，后续可实现车辆注册与更新。
   * \param interest 对应的同步信号兴趣包
   * \param data 收到的车辆信息数据包
   */
  void
  OnSyncSignalData (const ndn::Interest &interest, const ndn::Data &data);

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
  // 周期性同步信号广播（类似 5G Synchronization Signal）
  ////////////////////////////////////////////////////////////////////////

  /**
   * \brief 发送一个同步信号（SyncSignal）兴趣包。
   *        RSU 通过无线接口以广播方式周期性发送 /hello 兴趣包，
   *        附近车辆收到后可据此发现基站并完成驻留。类似 5G 基站
   *        周期发送 SSB（Synchronization Signal Block）的机制。
   */
  void
  SendSyncSignal ();

  /** 在所有 P2P 接口上发布本节点身份。 */
  void
  SendP2pHandshake ();

  /** 处理其他基础设施节点发来的握手 Interest。 */
  void
  OnP2pHandshakeInterest (const ndn::Interest &interest);

  void
  OnP2pHandshakeData (uint64_t outFaceId, const ndn::Interest &interest,
                      const ndn::Data &data);

  void
  OnP2pHandshakeNack (const ndn::Interest &interest, const ndn::lp::Nack &nack);

  void
  OnP2pHandshakeTimeout (const ndn::Interest &interest);

  void
  OnP2pHandshakeDataPush (const ndn::Interest &interest, const ndn::Data &data);

  /**
   * 处理 Router 发来的 /vndn/control/neural-pit 预备控制报文。
   * 解出原始业务 Interest，并在本 RSU 的无线 face 上恢复 PIT in-record。
   */
  void
  OnNeuralPitPrepareData (const ndn::Data &data);

  void
  PushIdentityData (uint64_t faceId, uint32_t nodeId,
                    const std::string &role, const ndn::Name &name);

  void
  ForwardVehicleInterest (const ndn::Interest &interest, uint32_t obuNodeId,
                          uint64_t obuMac,
                          const std::vector<uint32_t> &returnRsuIds = {});

  void
  OnVehicleData (const ndn::Interest &interest, const ndn::Data &data);

  void
  SendDataToVehicle (const ndn::Data &data, uint32_t obuNodeId, uint64_t fallbackMac);

  void
  QueryVehicleLocation (uint32_t obuNodeId);

  void
  ForwardDataToRsu (uint32_t targetRsuId, uint32_t obuNodeId,
                    const ndn::Data &data);

  void
  OnRsuRelayData (const ndn::Data &data);

  /** 处理 Router 根据神经网络回程选择直接推送的业务 Data。 */
  void
  OnNeuralReturnData (const ndn::Data &data);

  void
  SendRelayData (const ndn::Name &name, const uint8_t *content, size_t contentSize);

  /** 将神经网络选择的 Data 回程 RSU 通知 Router。 */
  void
  SendNeuralRouteInstruction (const ndn::Name &interestName,
                              const std::vector<uint32_t> &returnRsuIds);

  uint64_t
  ResolveRouterFace () const;

  int64_t
  ResolveRealtimeTargetRsu (uint32_t obuNodeId) const;

  ////////////////////////////////////////////////////////////////////////
  // 共享 ns3-gym 神经网络回程决策接口
  ////////////////////////////////////////////////////////////////////////
  void
  InitializeOpenGym ();

  void
  RequestNeuralRoute (const ndn::Interest &interest, uint32_t obuNodeId,
                      uint64_t obuMac);

  std::vector<uint32_t>
  GetNeuralCandidateRsuIds () const;

  ns3::Ptr<ns3::OpenGymSpace>
  GetNeuralObservationSpace ();

  ns3::Ptr<ns3::OpenGymSpace>
  GetNeuralActionSpace ();

  bool
  GetNeuralGameOver ();

  ns3::Ptr<ns3::OpenGymDataContainer>
  GetNeuralObservation ();

  float
  GetNeuralReward ();

  std::string
  GetNeuralExtraInfo ();

  bool
  ExecuteNeuralAction (ns3::Ptr<ns3::OpenGymDataContainer> action);

private:
  struct PendingVehicleRequest
  {
    uint32_t obuNodeId = 0;
    uint64_t obuMac = 0;
  };

  struct NeuralRouteJob
  {
    VndnRsu *source = nullptr;
    std::shared_ptr<ndn::Interest> interest;
    uint32_t obuNodeId = 0;
    uint64_t obuMac = 0;
    std::vector<std::array<double, 6>> observations;
    std::vector<uint32_t> candidateRsuIds;
  };

  ndn::Face m_face;                          ///< 应用层与 NFD 交互的 face
  ndn::Scheduler m_scheduler;                ///< NDN 定时器
  ns3::Ptr<ns3::TraciClient> m_traci;        ///< SUMO 交通数据客户端
  ns3::Ptr<ns3::Node> m_thisNode = nullptr;  ///< 本节点指针
  bool m_active = false;                     ///< 应用是否处于活跃状态
  ns3::Ptr<ns3::NetDevice> m_wirelessDevice = nullptr; ///< 无线网络设备
  uint64_t m_wirelessFaceId = 0;             ///< 无线链路对应的 faceId
  std::vector<uint64_t> m_p2pFaceIds;        ///< 本节点所有 P2P face
  std::map<uint32_t, uint64_t> m_infrastructureRoutes; ///< 基础设施节点ID -> 出接口
  std::map<uint32_t, std::string> m_infrastructureRoles; ///< 基础设施节点ID -> 角色
  std::set<uint32_t> m_seenInfrastructureNodes; ///< 已传播的身份公告
  ns3::EventId m_p2pHandshakeEvent;          ///< 启动阶段握手事件
  uint32_t m_p2pHandshakeRound = 0;           ///< 当前握手轮次
  RsuForwardStrategy m_forwardStrategy = RsuForwardStrategy_NoForward;
  uint16_t m_openGymPort = 0;
  bool m_openGymRegistered = false;
  uint32_t m_neuralSequenceLength = 10;
  /// 前两名概率足够接近时使用双路径的最大概率差。
  double m_neuralDualPathProbabilityGap = 0.10;
  /** 第二名概率达到 0.10（不再是 0.0x）时也启用双路径。 */
  double m_neuralDualPathMinSecondProbability = 0.10;
  uint64_t m_relaySequence = 0;
  std::map<ndn::Name, PendingVehicleRequest> m_pendingVehicleRequests;
  std::map<uint32_t, std::vector<std::shared_ptr<ndn::Data>>> m_waitingForwardData;
  std::map<uint32_t, std::vector<std::shared_ptr<ndn::Data>>>
      m_relayDataWaitingForVehicle;
  std::map<uint32_t, uint32_t> m_resolvedVehicleRsu;

  // 同步信号广播相关成员
  ndn::scheduler::EventId m_sendSyncSignal;  ///< 同步信号发送定时器
  uint32_t m_syncSignalIntervalMs;           ///< hello 同步信号发送间隔（毫秒）
  ns3::Address m_wirelessAddress;            ///< 无线接口地址
  uint64_t m_wirelessMac = 0;                ///< 无线 MAC 地址（uint64 形式）
  uint64_t m_broadcastMac = 0;               ///< 广播地址 ff:ff:ff:ff:ff:ff 的 uint64 形式

  ////////////////////////////////////////////////////////////////////////
  // 车辆缓存映射相关成员
  ////////////////////////////////////////////////////////////////////////
  /// 车辆节点ID -> 该车辆缓存的名称集合
  std::map<int64_t, std::set<std::string>> m_vehicleToCs;
  /// 缓存名称 -> 持有该缓存的车辆节点ID集合
  std::map<std::string, std::set<int64_t>> m_csToVehicles;
  /// 车辆节点ID -> 最近一次回复时间戳（毫秒）
  std::map<int64_t, uint64_t> m_vehicleLastReplyMs;
  /// 车辆节点ID -> 最后一次 hello 回复中的无线 MAC
  std::map<int64_t, uint64_t> m_vehicleMac;
  /// 车辆节点ID -> 最后一次 hello 上报的次优 RSU（超时后仍保留）
  std::map<int64_t, int64_t> m_vehicleNextRsu;
  /// 车辆节点ID -> 最近的 hello 特征序列，顺序与训练 CSV 一致
  std::map<int64_t, std::deque<std::array<double, 6>>> m_vehicleObservationHistory;
  /// 车辆超时时间（毫秒），超过该时间未回复则视为离开
  uint32_t m_vehicleTimeoutMs;

  /** 所有 RSU 共用一个阻塞式 ns3-gym 连接和决策队列。 */
  static ns3::Ptr<ns3::OpenGymInterface> s_openGym;
  static VndnRsu *s_openGymOwner;
  static std::queue<NeuralRouteJob> s_neuralRouteJobs;
  static uint32_t s_openGymUserCount;
};

} // namespace vanet

#endif // VNDN_RSU_H
