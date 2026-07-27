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

#include "rx-power-dbm-tag.h"

namespace ns3 {

NS_OBJECT_ENSURE_REGISTERED(RxPowerDbmTag);

TypeId
RxPowerDbmTag::GetTypeId()
{
  static TypeId tid = TypeId("ns3::RxPowerDbmTag")
                          .SetParent<Tag>()
                          .SetGroupName("Wifi")
                          .AddConstructor<RxPowerDbmTag>();
  return tid;
}

TypeId
RxPowerDbmTag::GetInstanceTypeId() const
{
  return GetTypeId();
}

uint32_t
RxPowerDbmTag::GetSerializedSize() const
{
  // a double is 8 bytes
  return 8;
}

void
RxPowerDbmTag::Serialize(TagBuffer i) const
{
  i.WriteDouble(m_rxPowerDbm);
}

void
RxPowerDbmTag::Deserialize(TagBuffer i)
{
  m_rxPowerDbm = i.ReadDouble();
}

void
RxPowerDbmTag::Print(std::ostream& os) const
{
  os << "RxPowerDbm=" << m_rxPowerDbm;
}

void
RxPowerDbmTag::Set(double rxPowerDbm)
{
  m_rxPowerDbm = rxPowerDbm;
}

double
RxPowerDbmTag::Get() const
{
  return m_rxPowerDbm;
}

} // namespace ns3
