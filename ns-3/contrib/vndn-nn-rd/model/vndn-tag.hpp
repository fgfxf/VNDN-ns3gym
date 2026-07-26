/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-tag.hpp
 * \brief 车联网 NDN 自定义数据包标签。
 *
 * 本文件定义了 vndn-nn-rd 模块专用的 NDN 数据包标签类 VndnTag，用于在
 * 兴趣包 / 数据包 / NACK 上携带车联网通信所需的元信息：
 *   - 发送者节点 ID
 *   - 发送者无线 MAC 地址
 *   - 目标无线 MAC 地址（广播或单播）
 *   - 单播标记
 *
 * 设计参考 ndn::lp::GeoTag，将多个字段合并到同一个 Tag 类中，
 * 通过 getter / setter 访问各字段。TypeId 使用独立值 0x70000000，
 * 避免与 ndn-cxx 内置标签及 ndn4ivc 旧标签冲突。
 */

#ifndef VNDN_TAG_HPP
#define VNDN_TAG_HPP

#include "ndn-cxx/tag.hpp"

#include <cstdint>

namespace vanet {
namespace lp {

/**
 * \brief 车联网 NDN 数据包标签。
 *
 * 封装发送者节点 ID、发送者 / 目标无线 MAC 地址、单播标记等元信息。
 * 可附加于 Interest、Data、Nack。
 */
class VndnTag : public ndn::Tag
{
public:
  static constexpr int
  getTypeId() noexcept
  {
    return 0x70000000;
  }

  VndnTag() = default;

  /**
   * \brief 构造函数。
   * \param senderNodeId 发送者节点 ID
   * \param senderMac 发送者无线 MAC 地址（uint64）
   * \param targetMac 目标无线 MAC 地址（uint64，广播时为广播地址）
   * \param unicastFlag 单播标记（非零表示单播）
   */
  VndnTag(uint32_t senderNodeId, uint64_t senderMac,
          uint64_t targetMac, uint64_t unicastFlag)
    : m_senderNodeId(senderNodeId)
    , m_senderMac(senderMac)
    , m_targetMac(targetMac)
    , m_unicastFlag(unicastFlag)
  {
  }

public: // getter
  uint32_t
  getSenderNodeId() const noexcept
  {
    return m_senderNodeId;
  }

  uint64_t
  getSenderMac() const noexcept
  {
    return m_senderMac;
  }

  uint64_t
  getTargetMac() const noexcept
  {
    return m_targetMac;
  }

  uint64_t
  getUnicastFlag() const noexcept
  {
    return m_unicastFlag;
  }

public: // setter
  void
  setSenderNodeId(uint32_t nodeId) noexcept
  {
    m_senderNodeId = nodeId;
  }

  void
  setSenderMac(uint64_t mac) noexcept
  {
    m_senderMac = mac;
  }

  void
  setTargetMac(uint64_t mac) noexcept
  {
    m_targetMac = mac;
  }

  void
  setUnicastFlag(uint64_t flag) noexcept
  {
    m_unicastFlag = flag;
  }

private:
  uint32_t m_senderNodeId = 0;  ///< 发送者节点 ID
  uint64_t m_senderMac = 0;     ///< 发送者无线 MAC 地址
  uint64_t m_targetMac = 0;     ///< 目标无线 MAC 地址
  uint64_t m_unicastFlag = 0;   ///< 单播标记（非零为单播）
};

} // namespace lp
} // namespace vanet

#endif // VNDN_TAG_HPP
