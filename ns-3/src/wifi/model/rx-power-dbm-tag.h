/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/*
 * Copyright (c) 2011-2018  Regents of the University of California.
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 as
 * published by the Free Software Foundation;
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 */

#ifndef WIFI_RX_POWER_DBM_TAG_H
#define WIFI_RX_POWER_DBM_TAG_H

#include "ns3/tag.h"
#include "ns3/tag-buffer.h"

namespace ns3 {

/**
 * \brief Packet tag carrying the received signal power (dBm).
 *
 * This tag is attached to an ns3::Packet by the WifiPhy layer when a frame is
 * successfully received. Downstream layers (e.g. NDN NetDeviceTransport) can
 * read this tag to obtain the per-packet receive signal power.
 */
class RxPowerDbmTag : public Tag
{
public:
  /**
   * \brief Get the type ID.
   * \return the object TypeId
   */
  static TypeId
  GetTypeId();

  // Inherited from Tag
  TypeId
  GetInstanceTypeId() const override;

  uint32_t
  GetSerializedSize() const override;

  void
  Serialize(TagBuffer i) const override;

  void
  Deserialize(TagBuffer i) override;

  void
  Print(std::ostream& os) const override;

  /**
   * \brief Set the received signal power.
   * \param rxPowerDbm signal power in dBm
   */
  void
  Set(double rxPowerDbm);

  /**
   * \brief Get the received signal power.
   * \return signal power in dBm
   */
  double
  Get() const;

private:
  double m_rxPowerDbm = 0.0; ///< received signal power in dBm
};

} // namespace ns3

#endif // WIFI_RX_POWER_DBM_TAG_H
