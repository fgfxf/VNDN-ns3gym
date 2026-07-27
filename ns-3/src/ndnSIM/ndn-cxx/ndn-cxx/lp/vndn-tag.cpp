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

#include "ndn-cxx/lp/vndn-tag.hpp"
#include "ndn-cxx/lp/tlv.hpp"

namespace ndn {
namespace lp {

VndnTag::VndnTag(const Block& block)
{
  wireDecode(block);
}

template<encoding::Tag TAG>
size_t
VndnTag::wireEncode(EncodingImpl<TAG>& encoder) const
{
  size_t length = 0;
  // Encode in reverse order (prepend)
  length += encoding::prependDoubleBlock(encoder, tlv::VndnRxPowerDbm, m_rxPowerDbm);
  length += encoding::prependNonNegativeIntegerBlock(encoder, tlv::VndnTargetMac, m_targetMac);
  length += encoding::prependNonNegativeIntegerBlock(encoder, tlv::VndnSenderMac, m_senderMac);
  length += encoding::prependNonNegativeIntegerBlock(encoder, tlv::VndnSenderNodeId, m_senderNodeId);
  length += encoder.prependVarNumber(length);
  length += encoder.prependVarNumber(tlv::VndnTag);
  return length;
}

template size_t
VndnTag::wireEncode<encoding::EncoderTag>(EncodingImpl<encoding::EncoderTag>& encoder) const;

template size_t
VndnTag::wireEncode<encoding::EstimatorTag>(EncodingImpl<encoding::EstimatorTag>& encoder) const;

const Block&
VndnTag::wireEncode() const
{
  if (m_wire.hasWire()) {
    return m_wire;
  }

  EncodingEstimator estimator;
  size_t estimatedSize = wireEncode(estimator);

  EncodingBuffer buffer(estimatedSize, 0);
  wireEncode(buffer);

  m_wire = buffer.block();

  return m_wire;
}

void
VndnTag::wireDecode(const Block& wire)
{
  if (wire.type() != tlv::VndnTag) {
    NDN_THROW(ndn::tlv::Error("expecting VndnTag block"));
  }

  m_wire = wire;
  m_wire.parse();

  // Reset to defaults
  m_senderNodeId = 0;
  m_senderMac = 0;
  m_targetMac = 0;
  m_rxPowerDbm = -999.0;

  for (const Block& element : m_wire.elements()) {
    switch (element.type()) {
      case tlv::VndnSenderNodeId:
        m_senderNodeId = static_cast<uint32_t>(readNonNegativeInteger(element));
        break;
      case tlv::VndnSenderMac:
        m_senderMac = readNonNegativeInteger(element);
        break;
      case tlv::VndnTargetMac:
        m_targetMac = readNonNegativeInteger(element);
        break;
      case tlv::VndnRxPowerDbm:
        m_rxPowerDbm = encoding::readDouble(element);
        break;
      default:
        // ignore unknown sub-TLVs
        break;
    }
  }
}

} // namespace lp
} // namespace ndn
