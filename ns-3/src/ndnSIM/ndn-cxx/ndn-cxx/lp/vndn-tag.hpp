/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Copyright (c) 2013-2019 Regents of the University of California.
 *
 * This file is part of ndn-cxx library (NDN C++ library with eXperimental eXtensions).
 *
 * ndn-cxx library is free software: you can redistribute it and/or modify it under the
 * terms of the GNU Lesser General Public License as published by the Free Software
 * Foundation, either version 3 of the License, or (at your option) any later version.
 *
 * ndn-cxx library is distributed in the hope that it will be useful, but WITHOUT ANY
 * WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
 * PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more details.
 *
 * You should have received copies of the GNU General Public License and GNU Lesser
 * General Public License along with ndn-cxx, e.g., in COPYING.md file.  If not, see
 * <http://www.gnu.org/licenses/>.
 */

#ifndef NDN_CXX_LP_VNDN_TAG_HPP
#define NDN_CXX_LP_VNDN_TAG_HPP

#include "ndn-cxx/encoding/block-helpers.hpp"
#include "ndn-cxx/encoding/encoding-buffer.hpp"
#include "ndn-cxx/tag.hpp"

#include <cstdint>

namespace ndn {
namespace lp {

/**
 * \brief represents a VndnTag header field carrying vehicular NDN metadata.
 *
 * This tag encapsulates sender node ID, sender MAC, target MAC, and unicast flag,
 * and can be attached to Interest, Data, and Nack packets. It is designed to be
 * serialized into the NDNLPv2 wire format, similar to GeoTag.
 */
class VndnTag : public Tag
{
public:
  static constexpr int
  getTypeId() noexcept
  {
    return 0x70000000;
  }

  VndnTag() = default;

  /**
   * \brief Constructor.
   * \param senderNodeId sender node ID
   * \param senderMac sender wireless MAC address (uint64)
   * \param targetMac target wireless MAC address (uint64, broadcast address for broadcast)
   * \param unicastFlag unicast flag (non-zero means unicast)
   */
  VndnTag(uint32_t senderNodeId, uint64_t senderMac,
          uint64_t targetMac, uint64_t unicastFlag)
    : m_senderNodeId(senderNodeId)
    , m_senderMac(senderMac)
    , m_targetMac(targetMac)
    , m_unicastFlag(unicastFlag)
  {
  }

  explicit
  VndnTag(const Block& block);

  /**
   * \brief prepend VndnTag to encoder
   */
  template<encoding::Tag TAG>
  size_t
  wireEncode(EncodingImpl<TAG>& encoder) const;

  /**
   * \brief encode VndnTag into wire format
   */
  const Block&
  wireEncode() const;

  /**
   * \brief get VndnTag from wire format
   */
  void
  wireDecode(const Block& wire);

public: // getters
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

public: // setters
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
  uint32_t m_senderNodeId = 0;  ///< sender node ID
  uint64_t m_senderMac = 0;     ///< sender wireless MAC address
  uint64_t m_targetMac = 0;     ///< target wireless MAC address
  uint64_t m_unicastFlag = 0;   ///< unicast flag (non-zero means unicast)
  mutable Block m_wire;
};

} // namespace lp
} // namespace ndn

#endif // NDN_CXX_LP_VNDN_TAG_HPP
